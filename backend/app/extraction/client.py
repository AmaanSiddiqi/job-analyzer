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
    # Excluded from input_tokens by the API, and priced differently — see cost.py.
    cache_read_tokens: int
    cache_write_tokens: int
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
    }
    # Not every model accepts `effort` — Haiku 4.5 rejects the whole request
    # with a 400 rather than ignoring it, which silently cost a 150-listing
    # eval run. Empty string means "don't send it".
    if settings.extraction_effort:
        kwargs["output_config"] = {"effort": settings.extraction_effort}
    # Both branches are explicit on purpose. Omitting `thinking` entirely does
    # NOT turn it on — it takes the API default, which measured as a median of
    # +0 output tokens versus thinking-off, silently making the first "thinking
    # on vs off" eval a comparison of one setting against itself.
    #
    # Sonnet 5 wants "adaptive", not the older "enabled" + budget_tokens shape:
    #   400 '"thinking.type.enabled" is not supported for this model. Use
    #        "thinking.type.adaptive" and "output_config.effort"'
    # How *much* it thinks is then governed by effort above, not by a budget.
    kwargs["thinking"] = (
        {"type": "adaptive"} if settings.extraction_thinking else {"type": "disabled"}
    )
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
    # Only set when the *model* produced something we rejected. A transport
    # error means it never answered, and telling it "your previous response was
    # rejected: APIConnectionError" would be nonsense the model then tries to
    # act on.
    correction: str | None = None

    for attempt in (1, 2):
        messages = list(base["messages"])
        if correction:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response was rejected: "
                        f"{correction}\n\nReturn a corrected extraction. Remember that "
                        "any visa or eligibility flag set to \"yes\" or \"no\" requires a "
                        "verbatim quote in `evidence`, that anything the posting does "
                        "not state is \"not_stated\" / \"\" / 0 / \"unknown\" rather than "
                        "a guess, and that compensation amounts require a currency."
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
            correction = None
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
            last_error = correction = "response did not parse into JobComponents"
            log.warning("extraction attempt %d: %s", attempt, last_error)
            continue

        try:
            components = JobComponents.model_validate(parsed, strict=False)
        except ValidationError as e:
            # Structured outputs guarantee the schema, not our extra rules
            # (evidence-required, comp needs a currency) — those land here.
            last_error = correction = str(e)
            log.warning("extraction attempt %d rejected by validators: %s", attempt, last_error)
            continue

        return ExtractionResult(
            components=components,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            model=response.model,
            prompt_version=PROMPT_VERSION,
            attempts=attempt,
        )

    raise ExtractionFailed(
        f"extraction failed after 2 attempts: {last_error}", raw_response=last_raw
    )
