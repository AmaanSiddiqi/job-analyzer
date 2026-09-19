"""Batch extraction — the path the backfill and all steady-state extraction run
through, so every way it can spend money twice (or not at all) is pinned here.

No network: the Anthropic client is a stub, and the DB is a mock whose queries
are fed in order.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic.types import Message, TextBlock, Usage

from app.extraction import batch as batch_mod
from app.extraction.batch import (
    _collect_one,
    build_batch_params,
    collect_batches,
    submit_batch,
)
from app.extraction.client import ExtractionFailed, ExtractionResult, output_format_param
from app.extraction.prompts import PROMPT_VERSION
from app.extraction.schema import JobComponents
from app.models import DeadLetter, ExtractionBatch, ListingComponent
from app.settings import Settings


def _settings(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "extraction_model": "claude-sonnet-5",
        "extraction_thinking": False,
        "extraction_effort": "low",
        "extraction_cost_cap_usd": 15.0,
        "extraction_est_batch_cost_per_listing_usd": 0.015,
    }
    values.update(over)
    return Settings(**values)


def _raw(listing_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=listing_id,
        title="Backend Engineer",
        company="Acme",
        location="Toronto, ON",
        description="We use Python. 3+ years of experience required.",
        source_url=f"https://example.test/{listing_id}",
        posted_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


GOOD = JobComponents(title_normalized="Backend Engineer", company_canonical="Acme")


def _message(body: str, stop_reason: str = "end_turn") -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[TextBlock(type="text", text=body)],
        stop_reason=stop_reason,  # type: ignore[arg-type]
        stop_sequence=None,
        usage=Usage(
            input_tokens=1_300,
            output_tokens=650,
            cache_read_input_tokens=2_299,
            cache_creation_input_tokens=0,
        ),
    )


def _succeeded(listing_id: int, body: str | None = None, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        custom_id=str(listing_id),
        result=SimpleNamespace(
            type="succeeded",
            message=_message(body if body is not None else GOOD.model_dump_json(), stop_reason),
        ),
    )


def _failed(listing_id: int, kind: str = "errored"):
    return SimpleNamespace(custom_id=str(listing_id), result=SimpleNamespace(type=kind))


class _AsyncIter:
    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _client(results=(), processing_status: str = "ended", batch_id: str = "msgbatch_1"):
    client = MagicMock()
    batches = client.messages.batches
    batches.create = AsyncMock(return_value=SimpleNamespace(id=batch_id))
    batches.cancel = AsyncMock()
    batches.retrieve = AsyncMock(return_value=SimpleNamespace(processing_status=processing_status))
    batches.results = AsyncMock(side_effect=lambda _id: _AsyncIter(results))
    client.messages.create = AsyncMock(return_value=SimpleNamespace(
        model="claude-sonnet-5",
        usage=Usage(input_tokens=6, output_tokens=16, cache_read_input_tokens=4_322,
                    cache_creation_input_tokens=0),
    ))
    return client


def _rows(items):
    result = MagicMock()
    result.scalars.return_value = iter(items)
    return result


def _open_batch(ids: list[int]) -> ExtractionBatch:
    return ExtractionBatch(
        id=7,
        anthropic_batch_id="msgbatch_1",
        status="submitted",
        model="claude-sonnet-5",
        prompt_version=PROMPT_VERSION,
        raw_listing_ids=ids,
        request_count=len(ids),
        estimated_cost_usd=Decimal("0.01"),
        succeeded=0,
        fell_back_to_live=0,
        dead_lettered=0,
    )


def _collect_db(raws, already_done=()):
    """A session whose two collection queries return the batch's raws, then the
    ids already extracted."""
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=Decimal(0))  # check_cap's spend-so-far
    db.execute = AsyncMock(side_effect=[_rows(raws), _rows(list(already_done))])
    return db


def _added(db, kind):
    return [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], kind)]


# ---------------------------------------------------------------- requests


class TestBatchRequest:
    def test_carries_the_structured_output_format_parse_would_send(self):
        params = build_batch_params(_settings(), _raw(1))
        assert params["output_config"]["format"] == output_format_param()
        assert params["output_config"]["format"]["type"] == "json_schema"

    def test_keeps_effort_alongside_the_format(self):
        params = build_batch_params(_settings(extraction_effort="low"), _raw(1))
        assert params["output_config"]["effort"] == "low"

    def test_omits_effort_for_models_that_reject_it(self):
        params = build_batch_params(_settings(extraction_effort=""), _raw(1))
        assert "effort" not in params["output_config"]

    def test_caches_the_shared_prefix_for_an_hour_and_sets_thinking_explicitly(self):
        """1h, not 5m: the warm-up written before submission must outlive the
        batch's processing time, which can exceed 5 minutes."""
        params = build_batch_params(_settings(), _raw(1))
        assert params["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert params["thinking"] == {"type": "disabled"}

    def test_live_path_keeps_the_5_minute_cache(self):
        """Sequential live calls hit reliably within 5m; the 2x 1h write would
        only cost more there."""
        from app.extraction.client import build_request

        req = build_request(_settings(), "T", "C", None, "body")
        assert req["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_nested_models_still_lead_after_the_sdk_transform(self):
        """Field order decides whether the schema compiles (schema.py). The
        batch path sends the transformed schema directly, so it must survive
        transform_schema with the nested models first."""
        props = list(output_format_param()["schema"]["properties"])
        assert props[:4] == ["compensation", "location", "eligibility", "visa"]


# ---------------------------------------------------------------- submit


def _submit_db(lock: bool = True, last_status: str | None = None):
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[lock, last_status])
    return db


class TestSubmit:
    async def test_warms_the_cache_with_the_batch_prefix_before_submitting(self):
        """Measured: an unwarmed batch got 0/6 cache reads and cost as much as
        live; warmed, 5/5 reads at half the price. The warm-up must share the
        exact prefix — system, schema, model — or it warms the wrong key."""
        db, client = _submit_db(), _client()
        order: list[str] = []
        client.messages.create = AsyncMock(side_effect=lambda **kw: order.append("warm") or SimpleNamespace(
            model="claude-sonnet-5",
            usage=Usage(input_tokens=6, output_tokens=16, cache_read_input_tokens=0,
                        cache_creation_input_tokens=4_322),
        ))
        client.messages.batches.create = AsyncMock(
            side_effect=lambda **kw: order.append("batch") or SimpleNamespace(id="msgbatch_1")
        )
        with (
            patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])),
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.03"))) as usage,
        ):
            await submit_batch(db, client, settings=_settings())
        assert order == ["warm", "batch"]
        warm = client.messages.create.call_args.kwargs
        request = client.messages.batches.create.call_args.kwargs["requests"][0]["params"]
        for key in ("model", "system", "output_config", "thinking"):
            assert warm[key] == request[key], key
        usage.assert_awaited_once()  # the warm-up is a billed call; it's ledgered

    async def test_a_failed_warm_up_still_submits(self):
        """Warming is an optimisation; the cap is already sized for no cache."""
        db, client = _submit_db(), _client()
        client.messages.create = AsyncMock(side_effect=ConnectionError("blip"))
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])):
            assert await submit_batch(db, client, settings=_settings()) is not None
        client.messages.batches.create.assert_awaited_once()

    async def test_records_the_batch_with_its_postings(self):
        db, client = _submit_db(), _client()
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1), _raw(2)])):
            row = await submit_batch(db, client, settings=_settings())
        assert row is not None
        assert row.anthropic_batch_id == "msgbatch_1"
        assert row.raw_listing_ids == [1, 2]
        sent = client.messages.batches.create.call_args.kwargs["requests"]
        assert [r["custom_id"] for r in sent] == ["1", "2"]
        db.commit.assert_awaited()

    async def test_trims_to_fit_the_cost_cap_before_sending(self):
        # $0.015 per batched listing; a $0.075 cap affords exactly 5.
        db, client = _submit_db(), _client()
        listings = [_raw(i) for i in range(1, 11)]
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=listings)):
            row = await submit_batch(
                db, client, settings=_settings(extraction_cost_cap_usd=0.075)
            )
        assert row is not None and row.request_count == 5
        assert len(client.messages.batches.create.call_args.kwargs["requests"]) == 5

    async def test_nothing_pending_sends_nothing(self):
        db, client = _submit_db(), _client()
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[])):
            assert await submit_batch(db, client, settings=_settings()) is None
        client.messages.batches.create.assert_not_awaited()

    async def test_concurrent_submission_is_refused(self):
        """Two submitters selecting the same pending postings would pay twice."""
        db, client = _submit_db(lock=False), _client()
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])):
            assert await submit_batch(db, client, settings=_settings()) is None
        client.messages.batches.create.assert_not_awaited()

    async def test_tripped_breaker_blocks_scheduled_submission(self):
        db, client = _submit_db(last_status="failed"), _client()
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])):
            assert await submit_batch(db, client, settings=_settings()) is None
        client.messages.batches.create.assert_not_awaited()

    async def test_force_resumes_past_the_breaker(self):
        db, client = _submit_db(), _client()
        db.scalar = AsyncMock(side_effect=[True])  # lock only; breaker not consulted
        with patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])):
            row = await submit_batch(db, client, settings=_settings(), force=True)
        assert row is not None

    async def test_unrecorded_batch_is_cancelled_rather_than_orphaned(self):
        """A batch nothing records would never be collected — paid for and lost."""
        db, client = _submit_db(), _client()
        db.commit = AsyncMock(side_effect=RuntimeError("db down"))
        with (
            patch.object(batch_mod, "pending_listings", AsyncMock(return_value=[_raw(1)])),
            pytest.raises(RuntimeError),
        ):
            await submit_batch(db, client, settings=_settings())
        client.messages.batches.cancel.assert_awaited_once_with("msgbatch_1")


# ---------------------------------------------------------------- collect


def _live_ok():
    return AsyncMock(
        return_value=ExtractionResult(
            components=GOOD,
            input_tokens=3_500,
            output_tokens=650,
            cache_read_tokens=0,
            cache_write_tokens=0,
            model="claude-sonnet-5",
            prompt_version=PROMPT_VERSION,
            attempts=1,
        )
    )


class TestCollect:
    async def test_succeeded_results_are_written_and_billed_at_batch_rates(self):
        raws = [_raw(1), _raw(2)]
        db, batch = _collect_db(raws), _open_batch([1, 2])
        client = _client([_succeeded(1), _succeeded(2)])
        stats = batch_mod.CollectStats()
        with patch.object(
            batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.007"))
        ) as usage:
            await _collect_one(db, client, _settings(), batch, stats)
        assert stats.extracted == 2
        assert len(_added(db, ListingComponent)) == 2
        assert batch.status == "collected"
        assert all(c.kwargs["batch"] is True for c in usage.call_args_list)
        # cache reads are billed, not dropped (cost.py)
        assert usage.call_args_list[0].kwargs["cache_read_tokens"] == 2_299

    async def test_invalid_output_gets_one_live_retry(self):
        db, batch = _collect_db([_raw(1)]), _open_batch([1])
        bad = json.dumps({"title_normalized": "T", "company_canonical": "C",
                          "visa": {"sponsorship_available": "yes", "evidence": []}})
        client = _client([_succeeded(1, body=bad)])
        stats = batch_mod.CollectStats()
        with (
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.01"))),
            patch.object(batch_mod, "extract_one", _live_ok()) as live,
        ):
            await _collect_one(db, client, _settings(), batch, stats)
        live.assert_awaited_once()
        assert stats.fell_back_to_live == 1 and batch.fell_back_to_live == 1
        assert len(_added(db, ListingComponent)) == 1

    async def test_truncated_or_expired_results_also_retry_live(self):
        db, batch = _collect_db([_raw(1), _raw(2)]), _open_batch([1, 2])
        client = _client(
            [_succeeded(1, body='{"title_norm', stop_reason="max_tokens"), _succeeded(2)]
        )
        stats = batch_mod.CollectStats()
        with (
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.01"))),
            patch.object(batch_mod, "extract_one", _live_ok()) as live,
        ):
            await _collect_one(db, client, _settings(), batch, stats)
        assert live.await_count == 1
        assert stats.extracted == 1 and stats.fell_back_to_live == 1

    async def test_third_failure_dead_letters_with_the_attempt_count(self):
        # 1 failure in 5 stays under the breaker's 20% threshold.
        ids = [1, 2, 3, 4, 5]
        db, batch = _collect_db([_raw(i) for i in ids]), _open_batch(ids)
        client = _client([_failed(1, "expired")] + [_succeeded(i) for i in ids[1:]])
        stats = batch_mod.CollectStats()
        with (
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.01"))),
            patch.object(
                batch_mod,
                "extract_one",
                AsyncMock(side_effect=ExtractionFailed("still bad", raw_response="{}")),
            ),
        ):
            await _collect_one(db, client, _settings(), batch, stats)
        [dead] = _added(db, DeadLetter)
        assert dead.attempts == 3
        assert dead.payload["prompt_version"] == PROMPT_VERSION
        assert batch.dead_lettered == 1

    async def test_an_unexpected_exception_dead_letters_instead_of_wedging(self):
        """Anything escaping here would leave the batch 'submitted' and fail on
        the same posting every hour, forever."""
        ids = [1, 2, 3, 4, 5]
        db, batch = _collect_db([_raw(i) for i in ids]), _open_batch(ids)
        client = _client([_failed(1)] + [_succeeded(i) for i in ids[1:]])
        stats = batch_mod.CollectStats()
        with (
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.01"))),
            patch.object(batch_mod, "extract_one", AsyncMock(side_effect=KeyError("boom"))),
        ):
            await _collect_one(db, client, _settings(), batch, stats)
        assert batch.status == "collected"
        assert "KeyError" in _added(db, DeadLetter)[0].error

    async def test_systematic_failure_trips_the_breaker_and_retries_nothing(self):
        """If the schema were rejected, every request fails; retrying each one
        live would re-run the whole backlog at twice the price."""
        db, batch = _collect_db([]), _open_batch([1, 2, 3, 4, 5])
        client = _client([_failed(i) for i in range(1, 5)] + [_succeeded(5)])
        stats = batch_mod.CollectStats()
        with patch.object(batch_mod, "extract_one", AsyncMock()) as live:
            await _collect_one(db, client, _settings(), batch, stats)
        live.assert_not_awaited()
        assert batch.status == "failed"
        assert "4/5" in (batch.error or "")
        assert stats.batches_failed == 1

    async def test_recollecting_skips_postings_already_written(self):
        """A crash mid-collection is re-run from the top; nothing is duplicated."""
        db, batch = _collect_db([_raw(1), _raw(2)], already_done=[1]), _open_batch([1, 2])
        client = _client([_succeeded(1), _succeeded(2)])
        stats = batch_mod.CollectStats()
        with patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.007"))):
            await _collect_one(db, client, _settings(), batch, stats)
        assert stats.extracted == 1
        assert len(_added(db, ListingComponent)) == 1

    async def test_cost_cap_leaves_the_retry_pending_not_dead(self):
        """Hitting the cap isn't a failure of the posting; it stays eligible."""
        ids = [1, 2, 3, 4, 5]
        db, batch = _collect_db([_raw(i) for i in ids]), _open_batch(ids)
        db.scalar = AsyncMock(return_value=Decimal("99"))  # already past the cap
        client = _client([_failed(1)] + [_succeeded(i) for i in ids[1:]])
        stats = batch_mod.CollectStats()
        with (
            patch.object(batch_mod, "record_usage", AsyncMock(return_value=Decimal("0.007"))),
            patch.object(batch_mod, "extract_one", AsyncMock()) as live,
        ):
            await _collect_one(db, client, _settings(), batch, stats)
        live.assert_not_awaited()
        assert _added(db, DeadLetter) == []

    async def test_batches_still_processing_are_left_alone(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_open_batch([1])])))
        ))
        client = _client(processing_status="in_progress")
        stats = await collect_batches(db, client, _settings())
        assert stats.still_processing == 1
        client.messages.batches.results.assert_not_awaited()


# ---------------------------------------------------------------- scheduling


class TestScheduling:
    def test_needs_both_the_flag_and_the_key(self, monkeypatch):
        from app import scheduler
        from app.settings import get_settings

        monkeypatch.setenv("ENABLE_LLM_EXTRACTION", "true")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        get_settings.cache_clear()
        assert scheduler.llm_extraction_enabled() is False

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        get_settings.cache_clear()
        assert scheduler.llm_extraction_enabled() is True

        monkeypatch.setenv("ENABLE_LLM_EXTRACTION", "false")
        get_settings.cache_clear()
        assert scheduler.llm_extraction_enabled() is False


class TestIsolation:
    """One bad batch must not wedge extraction: collect runs before submit in
    every cycle, so an exception here would block all new work, hourly."""

    def _db_with(self, batches):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=batches)))
        ))
        return db

    async def test_a_batch_gone_at_anthropic_is_failed_not_retried_forever(self):
        import anthropic
        import httpx

        batch = _open_batch([1])
        client = _client()
        client.messages.batches.retrieve = AsyncMock(side_effect=anthropic.NotFoundError(
            "not found",
            response=httpx.Response(404, request=httpx.Request("GET", "https://x")),
            body=None,
        ))
        stats = await collect_batches(self._db_with([batch]), client, _settings())
        assert batch.status == "failed"
        assert stats.batches_failed == 1

    async def test_a_transient_error_leaves_the_batch_for_next_tick(self):
        first, second = _open_batch([1]), _open_batch([2])
        second.anthropic_batch_id = "msgbatch_2"
        client = _client(processing_status="in_progress")
        client.messages.batches.retrieve = AsyncMock(side_effect=[
            ConnectionError("blip"),
            SimpleNamespace(processing_status="in_progress"),
        ])
        stats = await collect_batches(self._db_with([first, second]), client, _settings())
        assert first.status == "submitted"  # untouched, retried next tick
        assert stats.still_processing == 1  # the second batch was still checked
        assert any("ConnectionError" in e for e in stats.errors)


def test_default_cap_sizing_holds_even_with_zero_cache_hits():
    """The measured no-cache batch cost was $0.0149/listing. The default
    estimate must be at least that, or a $15 cap can overshoot ~2x."""
    settings = Settings()
    assert settings.extraction_est_batch_cost_per_listing_usd >= 0.0149
    affordable = int(settings.extraction_cost_cap_usd / settings.extraction_est_batch_cost_per_listing_usd)
    assert affordable * 0.0149 <= settings.extraction_cost_cap_usd
