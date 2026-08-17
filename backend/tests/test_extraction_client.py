"""extract_one: request shape, retry-with-error, refusal, dead-letter path.

The Anthropic client is stubbed — CLAUDE.md forbids live network in unit
tests, and stubbing lets us assert the retry actually carries the error text
back to the model rather than silently re-asking the same question.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from anthropic.types import TextBlock

from app.extraction.client import (
    MAX_DESCRIPTION_CHARS,
    ExtractionFailed,
    build_request,
    extract_one,
)
from app.extraction.prompts import PROMPT_VERSION
from app.extraction.schema import JobComponents, Seniority
from app.settings import Settings

GOOD = JobComponents(
    title_raw="Senior Software Engineer, Platform",
    title_normalized="Senior Software Engineer",
    seniority=Seniority.SENIOR,
    company_raw="Cohere Inc.",
    company_canonical="Cohere",
    skills=["python", "aws"],
    extraction_confidence=0.9,
)


def _settings(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "extraction_model": "claude-sonnet-5",
        "extraction_max_tokens": 4096,
        "extraction_effort": "low",
        "extraction_thinking": True,
    }
    values.update(over)
    return Settings(**values)


def _response(parsed, *, usage=(5000, 800), stop_reason="end_turn", text="{}"):
    """Stub response. `content` holds a real TextBlock, not a look-alike: the
    client narrows content blocks by type, so a duck-typed stub would pass here
    while the raw-response capture silently returned None in production."""
    return SimpleNamespace(
        parsed_output=parsed,
        content=[TextBlock(type="text", text=text, citations=None)],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
        model="claude-sonnet-5",
        stop_reason=stop_reason,
        stop_details=None,
    )


def _client(*responses):
    """Stub whose parse() yields the given responses/exceptions in order."""
    client = SimpleNamespace()
    client.messages = SimpleNamespace()

    async def parse(**kwargs):
        result = responses[parse.calls]
        parse.calls += 1
        parse.seen.append(kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    parse.calls = 0
    parse.seen = []
    client.messages.parse = parse
    return client


class TestBuildRequest:
    def test_caches_the_system_prefix(self):
        """The instructions + 200-id skill list are identical for every listing;
        without cache_control we'd pay full price for them 7,000 times."""
        req = build_request(_settings(), "T", "C", "Toronto", "body")
        assert req["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_truncates_enormous_descriptions(self):
        req = build_request(_settings(), "T", "C", None, "x" * (MAX_DESCRIPTION_CHARS + 5_000))
        assert len(req["messages"][0]["content"]) < MAX_DESCRIPTION_CHARS + 500

    def test_thinking_disabled_only_when_configured(self):
        assert "thinking" not in build_request(_settings(), "T", "C", None, "b")
        off = build_request(_settings(extraction_thinking=False), "T", "C", None, "b")
        assert off["thinking"] == {"type": "disabled"}

    def test_effort_passed_through(self):
        req = build_request(_settings(extraction_effort="medium"), "T", "C", None, "b")
        assert req["output_config"]["effort"] == "medium"


class TestExtractOne:
    async def test_happy_path_returns_components_and_usage(self):
        client = _client(_response(GOOD))
        result = await extract_one(
            client, _settings(), title="T", company="C", location="Toronto", description="body"
        )
        assert result.components.company_canonical == "Cohere"
        assert (result.input_tokens, result.output_tokens) == (5000, 800)
        assert result.attempts == 1
        assert result.prompt_version == PROMPT_VERSION

    async def test_retry_includes_the_error_text(self):
        """A blind retry would just re-ask the same question — the point is that
        the model is told what was wrong."""
        client = _client(_response(None), _response(GOOD))
        result = await extract_one(
            client, _settings(), title="T", company="C", location=None, description="body"
        )
        assert result.attempts == 2
        retry_messages = client.messages.parse.seen[1]["messages"]
        assert len(retry_messages) == 2
        assert "rejected" in retry_messages[-1]["content"]
        assert "evidence" in retry_messages[-1]["content"]

    async def test_dead_letters_after_two_failures_and_keeps_raw_response(self):
        client = _client(_response(None, text="I couldn't do that"), _response(None, text="nope"))
        with pytest.raises(ExtractionFailed) as exc:
            await extract_one(
                client, _settings(), title="T", company="C", location=None, description="body"
            )
        assert client.messages.parse.calls == 2
        # The raw response is what makes a dead letter debuggable later.
        assert exc.value.raw_response == "nope"

    async def test_refusal_fails_immediately_without_retrying(self):
        """Retrying a refusal just spends money to be refused again."""
        client = _client(_response(GOOD, stop_reason="refusal"))
        with pytest.raises(ExtractionFailed, match="refused"):
            await extract_one(
                client, _settings(), title="T", company="C", location=None, description="body"
            )
        assert client.messages.parse.calls == 1

    async def test_api_error_is_retried(self):
        err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x.test"))
        client = _client(err, _response(GOOD))
        result = await extract_one(
            client, _settings(), title="T", company="C", location=None, description="body"
        )
        assert result.attempts == 2

    async def test_validator_failure_is_retried_then_dead_letters(self):
        """Structured outputs guarantee the schema but not our extra rules, so
        an evidence-less visa flag arrives here as a validation error."""
        bad = {
            "title_raw": "T",
            "title_normalized": "T",
            "company_raw": "C",
            "company_canonical": "C",
            "visa": {"sponsorship_available": True, "evidence": []},
        }
        client = _client(_response(bad), _response(bad))
        with pytest.raises(ExtractionFailed):
            await extract_one(
                client, _settings(), title="T", company="C", location=None, description="body"
            )
        assert client.messages.parse.calls == 2


async def test_stub_client_is_never_a_real_client():
    """Guard against a future refactor accidentally instantiating a real client
    in tests (which would need a key and hit the network)."""
    assert not isinstance(_client(_response(GOOD)), anthropic.AsyncAnthropic)
    assert isinstance(AsyncMock(), AsyncMock)
