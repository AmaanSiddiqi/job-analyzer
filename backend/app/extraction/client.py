"""The extraction call itself: one listing in, validated JobComponents out.

Structured outputs make a malformed shape nearly impossible, so the retry path
exists for the residual cases (validation failure from our own extra rules,
refusals, transient API errors). Per CLAUDE.md: one retry with the error
appended, then dead-letter with the raw response stored.
"""

import logging
from dataclasses import dataclass

import anthropic
from anthropic.types import TextBlock
from anthropic.types.parsed_message import ParsedTextBlock
from pydantic import ValidationError

from ..settings import Settings
from .prompts import PROMPT_VERSION, system_prompt, user_prompt
from .schema import JobComponents

log = logging.getLogger(__name__)

# Postings past this are truncated. 50k chars ≈ the baseline extractor's own
# guard; real board descriptions average ~7k, so this only bites on outliers.
MAX_DESCRIPTION_CHARS = 50_000


class ExtractionFailed(RuntimeError):
    """Both attempts failed. `raw_response` is stored on the dead letter."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class ExtractionResult:
    components: JobComponents
    input_tokens: int
    output_tokens: int
    model: str
    prompt_version: str
    attempts: int


def build_request(
    settings: Settings, title: str, company: str, location: str | None, description: str
) -> dict:
    """Request kwargs shared by the live and batch paths, so a batch backfill
    can't drift from what the eval measured."""
    kwargs: dict = {
        "model": settings.extraction_model,
        "max_tokens": settings.extraction_max_tokens,
        "system": [
            {
                "type": "text",
                "text": system_prompt(),
                # The instructions + 200-id skill list are identical across
                # every listing; caching that prefix is most of the cost win.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": user_prompt(
                    title, company, location, description[:MAX_DESCRIPTION_CHARS]
                ),
            }
        ],
        "output_config": {"effort": settings.extraction_effort},
    }
    if not settings.extraction_thinking:
        kwargs["thinking"] = {"type": "disabled"}
    return kwargs


async def extract_one(
    client: anthropic.AsyncAnthropic,
    settings: Settings,
    *,
    title: str,
    company: str,
    location: str | None,
    description: str,
) -> ExtractionResult:
    """Extract one listing, with a single retry that includes the error."""
    base = build_request(settings, title, company, location, description)
    last_error: str | None = None
    last_raw: str | None = None

    for attempt in (1, 2):
        messages = list(base["messages"])
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was rejected: "
                        f"{last_error}\n\nReturn a corrected extraction. Remember that "
                        "any visa flag which is not null requires a verbatim quote in "
                        "`evidence`, and that unstated fields must be null."
                    ),
                }
            )
        try:
            response = await client.messages.parse(
                **{**base, "messages": messages},
                output_format=JobComponents,
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            # Transport/status problems: retry once, then dead-letter. The SDK
            # already retried 429/5xx internally before raising.
            last_error = f"{type(e).__name__}: {e}"
            log.warning("extraction attempt %d failed: %s", attempt, last_error)
            continue

        if response.stop_reason == "refusal":
            raise ExtractionFailed(
                f"model refused: {getattr(response.stop_details, 'category', None)}"
            )

        # Keep the raw text for the dead-letter record. Content is a union of
        # block types; only text blocks carry `.text`.
        last_raw = next(
            (b.text for b in response.content if isinstance(b, TextBlock | ParsedTextBlock)),
            None,
        )
        parsed = response.parsed_output
        if parsed is None:
            last_error = "response did not parse into JobComponents"
            log.warning("extraction attempt %d: %s", attempt, last_error)
            continue

        try:
            components = JobComponents.model_validate(parsed, strict=False)
        except ValidationError as e:
            # Structured outputs guarantee the schema, not our extra rules
            # (evidence-required, comp needs a currency) — those land here.
            last_error = str(e)
            log.warning("extraction attempt %d rejected by validators: %s", attempt, last_error)
            continue

        return ExtractionResult(
            components=components,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            prompt_version=PROMPT_VERSION,
            attempts=attempt,
        )

    raise ExtractionFailed(
        f"extraction failed after 2 attempts: {last_error}", raw_response=last_raw
    )
