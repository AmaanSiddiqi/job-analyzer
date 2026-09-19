"""Admin-gated extraction trigger.

Runs in the background: even a 50-listing batch takes minutes, and a backfill
takes far longer than any HTTP request should live. Progress is observable via
GET /admin/extraction-status.
"""

import logging
import os

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import require_admin_key
from ..database import AsyncSessionLocal
from ..extraction.batch import collect_batches, submit_batch
from ..extraction.service import run_extraction
from ..rate_limit import limiter
from ..settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extract"])


class ExtractStarted(BaseModel):
    status: str
    detail: str


async def _run_extraction_bg(limit: int) -> None:
    try:
        async with AsyncSessionLocal() as db:
            stats = await run_extraction(db, limit=limit)
        log.info(
            "background extraction finished: run=%s extracted=%d dead=%d cost=$%.4f%s",
            stats.run_id, stats.extracted, stats.dead_lettered, stats.cost_usd,
            f" ABORTED: {stats.aborted_reason}" if stats.aborted_reason else "",
        )
    except Exception:
        log.exception("background extraction failed")


@router.post("", response_model=ExtractStarted, dependencies=[Depends(require_admin_key)])
@limiter.limit("2/minute")
async def start_extraction(
    request: Request,
    background_tasks: BackgroundTasks,
    limit: int = Query(50, ge=1, le=1000, description="listings to extract this run"),
) -> ExtractStarted:
    settings = get_settings()
    if not settings.enable_llm_extraction:
        raise HTTPException(
            status_code=503,
            detail="LLM extraction is disabled. Set ENABLE_LLM_EXTRACTION=true to enable.",
        )
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured — extraction cannot run.",
        )
    background_tasks.add_task(_run_extraction_bg, limit)
    return ExtractStarted(
        status="started",
        detail=(
            f"Extracting up to {limit} listings with {settings.extraction_model} "
            f"(cap ${settings.extraction_cost_cap_usd:.2f}/run). "
            "Watch GET /admin/extraction-status."
        ),
    )


def _require_extraction_enabled() -> None:
    if not get_settings().enable_llm_extraction:
        raise HTTPException(
            status_code=503,
            detail="LLM extraction is disabled. Set ENABLE_LLM_EXTRACTION=true to enable.",
        )
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured — extraction cannot run.",
        )


class BatchSubmitted(BaseModel):
    submitted: bool
    anthropic_batch_id: str | None = None
    postings: int = 0
    estimated_cost_usd: float = 0.0
    detail: str


@router.post("/batch", response_model=BatchSubmitted, dependencies=[Depends(require_admin_key)])
@limiter.limit("2/minute")
async def start_batch(
    request: Request,
    limit: int = Query(2000, ge=1, le=10000, description="most postings to submit"),
) -> BatchSubmitted:
    """Submit pending postings as a Message Batch (half the live price).

    The backfill path, and the way to resume after the circuit breaker trips:
    this forces past the breaker, on the assumption that a person has looked at
    why the last batch failed. Submission returns in seconds; results are
    collected by the hourly job, or by POST /extract/collect.
    """
    _require_extraction_enabled()
    async with AsyncSessionLocal() as db, anthropic.AsyncAnthropic() as client:
        batch = await submit_batch(db, client, limit=limit, force=True)
    if batch is None:
        return BatchSubmitted(
            submitted=False,
            detail="Nothing pending, or another submission is in progress.",
        )
    return BatchSubmitted(
        submitted=True,
        anthropic_batch_id=batch.anthropic_batch_id,
        postings=batch.request_count,
        estimated_cost_usd=float(batch.estimated_cost_usd),
        detail="Submitted. Most batches finish within an hour.",
    )


class BatchesCollected(BaseModel):
    batches_collected: int
    batches_failed: int
    still_processing: int
    extracted: int
    fell_back_to_live: int
    dead_lettered: int
    cost_usd: float
    errors: list[str]


@router.post(
    "/collect", response_model=BatchesCollected, dependencies=[Depends(require_admin_key)]
)
@limiter.limit("6/minute")
async def collect(request: Request) -> BatchesCollected:
    """Collect finished batches now instead of waiting for the hourly job.

    Can spend money: failed results get one live retry each. The circuit
    breaker bounds that — a batch with a high failure rate retries nothing.
    """
    _require_extraction_enabled()
    async with AsyncSessionLocal() as db, anthropic.AsyncAnthropic() as client:
        stats = await collect_batches(db, client)
    return BatchesCollected(
        batches_collected=stats.batches_collected,
        batches_failed=stats.batches_failed,
        still_processing=stats.still_processing,
        extracted=stats.extracted,
        fell_back_to_live=stats.fell_back_to_live,
        dead_lettered=stats.dead_lettered,
        cost_usd=float(stats.cost_usd),
        errors=stats.errors[:20],
    )
