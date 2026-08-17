"""LLM spend accounting and the hard per-run cost cap.

Every call is written to llm_usage; before each call the run's spend so far is
checked against the cap and the run aborts if it would be exceeded. The cap is
a stop, not a warning — a runaway backfill is the expensive failure mode this
exists to prevent (CLAUDE.md: hard abort past cap, default $15/run).
"""

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LlmUsage

log = logging.getLogger(__name__)

# USD per million tokens. Hardcoded deliberately: a wrong number here silently
# mis-bills the cap, so it should change only via a reviewed commit.
# Sonnet 5 list price is $3/$15 per MTok; the introductory $2/$10 runs through
# 2026-08-31, so list price is used here to avoid under-counting when it ends.
_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}
_MILLION = Decimal(1_000_000)

# The Batch API bills at 50% of standard rates.
BATCH_DISCOUNT = Decimal("0.5")


class CostCapExceeded(RuntimeError):
    """Raised to abort a run that has reached its spend cap."""


def price_call(
    model: str, input_tokens: int, output_tokens: int, *, batch: bool = False
) -> Decimal:
    """USD cost of one call. Unknown models price at the most expensive known
    rate rather than 0 — under-counting spend is the dangerous direction."""
    if model in _PRICES:
        in_rate, out_rate = _PRICES[model]
    else:
        in_rate, out_rate = max(_PRICES.values(), key=lambda p: p[1])
        log.warning("unknown model %s — pricing at the highest known rate", model)
    cost = (Decimal(input_tokens) * in_rate + Decimal(output_tokens) * out_rate) / _MILLION
    return cost * BATCH_DISCOUNT if batch else cost


async def run_spend(db: AsyncSession, run_id: str) -> Decimal:
    """Total USD recorded for a run so far."""
    total = await db.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(LlmUsage.run_id == run_id)
    )
    return Decimal(str(total or 0))


async def check_cap(db: AsyncSession, run_id: str, cap_usd: float) -> Decimal:
    """Raise CostCapExceeded if the run has already hit its cap.

    Called before each call rather than after, so the cap bounds what we spend
    instead of merely reporting that we overspent.
    """
    spent = await run_spend(db, run_id)
    if spent >= Decimal(str(cap_usd)):
        raise CostCapExceeded(
            f"run {run_id} has spent ${spent:.4f} of its ${cap_usd:.2f} cap — aborting"
        )
    return spent


async def record_usage(
    db: AsyncSession,
    *,
    run_id: str,
    purpose: str,
    model: str,
    prompt_version: str | None,
    input_tokens: int,
    output_tokens: int,
    batch: bool = False,
) -> Decimal:
    """Append one call to the ledger and return its cost."""
    cost = price_call(model, input_tokens, output_tokens, batch=batch)
    db.add(
        LlmUsage(
            run_id=run_id,
            purpose=purpose,
            model=model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
    )
    return cost
