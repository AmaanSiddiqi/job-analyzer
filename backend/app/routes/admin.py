"""Admin views over the pipeline's review queues.

Plain JSON/text, admin-key gated — per CLAUDE.md the admin surface stays
minimal. /admin/deadletters arrives with the extraction pipeline.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..database import get_db
from ..extraction.prompts import PROMPT_VERSION
from ..models import DeadLetter, ListingComponent, LlmUsage, RawListing, UnmappedSkill
from ..rate_limit import limiter

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class UnmappedSkillOut(BaseModel):
    skill: str
    occurrences: int
    first_seen: str
    last_seen: str
    status: str


class UnmappedSkillsResponse(BaseModel):
    total: int
    skills: list[UnmappedSkillOut]


@router.get("/unmapped-skills", response_model=UnmappedSkillsResponse)
@limiter.limit("30/minute")
async def list_unmapped_skills(
    request: Request,
    status: str = Query("pending", description="pending | mapped | rejected"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> UnmappedSkillsResponse:
    """Skills the extractor produced that the taxonomy doesn't cover.

    Ordered by occurrences so the weekly review starts with the entries that
    would buy the most coverage.
    """
    rows = (
        (
            await db.execute(
                select(UnmappedSkill)
                .where(UnmappedSkill.status == status)
                .order_by(UnmappedSkill.occurrences.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return UnmappedSkillsResponse(
        total=len(rows),
        skills=[
            UnmappedSkillOut(
                skill=r.skill,
                occurrences=r.occurrences,
                first_seen=r.first_seen.isoformat(),
                last_seen=r.last_seen.isoformat(),
                status=r.status,
            )
            for r in rows
        ],
    )


class DeadLetterOut(BaseModel):
    id: int
    kind: str
    raw_listing_id: int | None
    error: str
    attempts: int
    created_at: str
    last_attempt_at: str | None
    payload: dict[str, Any]


class DeadLettersResponse(BaseModel):
    total_unresolved: int
    dead_letters: list[DeadLetterOut]


@router.get("/deadletters", response_model=DeadLettersResponse)
@limiter.limit("30/minute")
async def list_dead_letters(
    request: Request,
    kind: str | None = Query(None, description="e.g. extraction, ingestion"),
    include_resolved: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> DeadLettersResponse:
    """Failed pipeline items, newest first; unresolved only unless asked."""
    stmt = select(DeadLetter).order_by(DeadLetter.created_at.desc()).limit(limit)
    count_stmt = select(func.count()).select_from(DeadLetter).where(DeadLetter.resolved_at.is_(None))
    if kind:
        stmt = stmt.where(DeadLetter.kind == kind)
        count_stmt = count_stmt.where(DeadLetter.kind == kind)
    if not include_resolved:
        stmt = stmt.where(DeadLetter.resolved_at.is_(None))

    rows = (await db.execute(stmt)).scalars().all()
    return DeadLettersResponse(
        total_unresolved=await db.scalar(count_stmt) or 0,
        dead_letters=[
            DeadLetterOut(
                id=r.id,
                kind=r.kind,
                raw_listing_id=r.raw_listing_id,
                error=r.error,
                attempts=r.attempts,
                created_at=r.created_at.isoformat(),
                last_attempt_at=r.last_attempt_at.isoformat() if r.last_attempt_at else None,
                payload=r.payload,
            )
            for r in rows
        ],
    )


class RequeueResponse(BaseModel):
    requeued: int
    detail: str


@router.post("/deadletters/{dead_letter_id}/requeue", response_model=RequeueResponse)
@limiter.limit("10/minute")
async def requeue_dead_letter(
    request: Request, dead_letter_id: int, db: AsyncSession = Depends(get_db)
) -> RequeueResponse:
    """Mark a dead letter resolved so its listing is eligible again.

    Requeue is deliberately only "clear the marker": the extraction query picks
    up any listing lacking a row at the current prompt version, so resolving is
    all the next run needs. Nothing here calls the model, so a requeue cannot
    spend money by itself.
    """
    dead = await db.get(DeadLetter, dead_letter_id)
    if not dead:
        raise HTTPException(status_code=404, detail="Dead letter not found")
    if dead.resolved_at is not None:
        return RequeueResponse(requeued=0, detail="Already resolved — nothing to do.")
    dead.resolved_at = datetime.now(UTC)
    await db.commit()
    return RequeueResponse(
        requeued=1,
        detail="Resolved. Eligible again on the next extraction run (POST /extract).",
    )


class ExtractionStatusResponse(BaseModel):
    prompt_version: str
    raw_listings: int
    extracted: int
    pending: int
    coverage_pct: float
    with_visa_signals: int
    unresolved_dead_letters: int
    spend_usd_total: float
    spend_usd_last_run: float
    last_run_id: str | None


@router.get("/extraction-status", response_model=ExtractionStatusResponse)
@limiter.limit("30/minute")
async def extraction_status(
    request: Request, db: AsyncSession = Depends(get_db)
) -> ExtractionStatusResponse:
    """Coverage, visa-signal yield and spend at the current prompt version.

    coverage_pct is the P1 DoD number (>=90% of ingested listings extracted).
    """
    raw_total = await db.scalar(select(func.count()).select_from(RawListing)) or 0
    at_version = ListingComponent.prompt_version == PROMPT_VERSION
    extracted = (
        await db.scalar(select(func.count()).select_from(ListingComponent).where(at_version)) or 0
    )
    with_visa = (
        await db.scalar(
            select(func.count())
            .select_from(ListingComponent)
            .where(at_version)
            .where(
                ListingComponent.visa_sponsorship_available.isnot(None)
                | ListingComponent.visa_requires_existing_authorization.isnot(None)
                | ListingComponent.visa_citizenship_or_pr_required.isnot(None)
            )
        )
        or 0
    )
    dead = (
        await db.scalar(
            select(func.count())
            .select_from(DeadLetter)
            .where(DeadLetter.kind == "extraction")
            .where(DeadLetter.resolved_at.is_(None))
        )
        or 0
    )
    total_spend = await db.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.purpose == "extraction"
        )
    )
    last_run = await db.scalar(
        select(LlmUsage.run_id)
        .where(LlmUsage.purpose == "extraction")
        .order_by(LlmUsage.created_at.desc())
        .limit(1)
    )
    last_spend = (
        await db.scalar(
            select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
                LlmUsage.run_id == last_run
            )
        )
        if last_run
        else 0
    )
    return ExtractionStatusResponse(
        prompt_version=PROMPT_VERSION,
        raw_listings=raw_total,
        extracted=extracted,
        pending=max(raw_total - extracted, 0),
        coverage_pct=round(100 * extracted / raw_total, 1) if raw_total else 0.0,
        with_visa_signals=with_visa,
        unresolved_dead_letters=dead,
        spend_usd_total=float(total_spend or 0),
        spend_usd_last_run=float(last_spend or 0),
        last_run_id=last_run,
    )
