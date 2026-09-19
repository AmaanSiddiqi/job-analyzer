"""Cost pricing and the hard cap. The cap is the guardrail on a runaway
backfill, so these test the abort path as carefully as the happy path."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.extraction.cost import (
    BATCH_DISCOUNT,
    CostCapExceeded,
    check_cap,
    price_call,
    record_usage,
)


def _db(spent: Decimal | float = 0):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=spent)
    session.add = MagicMock()
    return session


class TestPricing:
    def test_sonnet_5_list_price(self):
        # 1M in + 1M out at $3/$15
        assert price_call("claude-sonnet-5", 1_000_000, 1_000_000) == Decimal("18.00")

    def test_typical_listing_is_fractions_of_a_cent(self):
        cost = price_call("claude-sonnet-5", 5_000, 800)
        assert Decimal("0.02") < cost < Decimal("0.04")

    def test_batch_is_half_price(self):
        live = price_call("claude-sonnet-5", 10_000, 1_000)
        batch = price_call("claude-sonnet-5", 10_000, 1_000, batch=True)
        assert batch == live * BATCH_DISCOUNT

    def test_unknown_model_prices_at_the_highest_known_rate(self):
        """Under-counting spend would let a run blow past its cap, so an
        unrecognized model must price high, never at zero."""
        unknown = price_call("claude-future-9", 1_000_000, 1_000_000)
        assert unknown >= price_call("claude-opus-5", 1_000_000, 1_000_000)
        assert unknown > 0

    def test_zero_tokens_is_free(self):
        assert price_call("claude-sonnet-5", 0, 0) == Decimal(0)


class TestCap:
    async def test_under_cap_returns_spend(self):
        spent = await check_cap(_db(Decimal("3.50")), "run-1", 15.0)
        assert spent == Decimal("3.50")

    async def test_at_cap_aborts(self):
        with pytest.raises(CostCapExceeded, match="aborting"):
            await check_cap(_db(Decimal("15.00")), "run-1", 15.0)

    async def test_over_cap_aborts(self):
        with pytest.raises(CostCapExceeded):
            await check_cap(_db(Decimal("15.01")), "run-1", 15.0)

    async def test_no_spend_yet_is_fine(self):
        assert await check_cap(_db(None), "run-1", 15.0) == Decimal(0)


class TestLedger:
    async def test_record_usage_adds_a_row_and_returns_cost(self):
        db = _db()
        cost = await record_usage(
            db,
            run_id="run-1",
            purpose="extraction",
            model="claude-sonnet-5",
            prompt_version="v1",
            input_tokens=5_000,
            output_tokens=800,
        )
        db.add.assert_called_once()
        row = db.add.call_args.args[0]
        assert row.run_id == "run-1"
        assert row.cost_usd == cost
        assert row.input_tokens == 5_000


class TestCachePricing:
    """Cached reads are billed at a tenth of the input rate and cache writes at
    1.25x. `usage.input_tokens` excludes both, so ignoring them reports cached
    calls as cheaper than they are — the direction this module must never err."""

    def test_cache_reads_are_not_free(self):
        plain = price_call("claude-sonnet-5", 1_000, 500)
        cached = price_call("claude-sonnet-5", 1_000, 500, cache_read_tokens=10_000)
        assert cached > plain
        # 10k read tokens at 0.1x the $3/MTok input rate = $0.003
        assert cached - plain == Decimal("0.003")

    def test_cache_writes_cost_a_premium(self):
        plain = price_call("claude-sonnet-5", 1_000, 500)
        written = price_call("claude-sonnet-5", 1_000, 500, cache_write_tokens=10_000)
        # 10k write tokens at 1.25x the $3/MTok input rate = $0.0375
        assert written - plain == Decimal("0.0375")

    def test_batch_discount_applies_to_cache_components_too(self):
        live = price_call("claude-sonnet-5", 1_000, 500, cache_read_tokens=10_000)
        batched = price_call(
            "claude-sonnet-5", 1_000, 500, cache_read_tokens=10_000, batch=True
        )
        assert batched == live * Decimal("0.5")
