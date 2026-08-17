"""Admin-gated extraction trigger.

Runs in the background: even a 50-listing batch takes minutes, and a backfill
takes far longer than any HTTP request should live. Progress is observable via
GET /admin/extraction-status.
"""

import logging
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..auth import require_admin_key
from ..database import AsyncSessionLocal
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
