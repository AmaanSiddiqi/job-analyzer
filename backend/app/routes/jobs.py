from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..database import get_db
from ..models import JobPosting
from ..rate_limit import limiter
from ..schemas import JobPostingCreate, JobPostingOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _filtered_jobs_query(
    location: str | None,
    company: str | None,
    source_type: str | None,
    skill: str | None,
    q: str | None,
    since_days: int | None,
) -> Select[tuple[JobPosting]]:
    """Shared WHERE clauses so /jobs and /jobs/count can't drift apart."""
    stmt = select(JobPosting)
    if location:
        stmt = stmt.where(func.lower(JobPosting.location).contains(location.lower()))
    if company:
        stmt = stmt.where(func.lower(JobPosting.company) == company.lower())
    if source_type:
        stmt = stmt.where(JobPosting.source_type == source_type.lower())
    if skill:
        # Array containment (@>) — this is what the GIN index on skills serves.
        stmt = stmt.where(JobPosting.skills.contains([skill.lower()]))
    if q:
        stmt = stmt.where(func.lower(JobPosting.title).contains(q.lower()))
    if since_days:
        stmt = stmt.where(
            JobPosting.date_scraped >= datetime.now(UTC) - timedelta(days=since_days)
        )
    return stmt


@router.get("", response_model=list[JobPostingOut])
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    location: str | None = Query(None),
    company: str | None = Query(None),
    source_type: str | None = Query(None, description="greenhouse|lever|ashby|adzuna|jooble|linkedin"),
    skill: str | None = Query(None, description="exact taxonomy skill, e.g. 'python'"),
    q: str | None = Query(None, description="substring match on title"),
    since_days: int | None = Query(None, ge=1, le=365, description="posted within N days"),
    db: AsyncSession = Depends(get_db),
):
    """List postings, newest first. All filters are optional and AND together.

    Response stays a bare list (existing clients depend on it) — facet counts
    live on GET /trends/sources instead of an envelope here.
    """
    stmt = _filtered_jobs_query(location, company, source_type, skill, q, since_days)
    stmt = stmt.order_by(JobPosting.date_scraped.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/count")
async def count_jobs(
    location: str | None = Query(None),
    company: str | None = Query(None),
    source_type: str | None = Query(None),
    skill: str | None = Query(None),
    q: str | None = Query(None),
    since_days: int | None = Query(None, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Total matching the same filters as GET /jobs — lets the UI paginate and
    show "N results" without fetching every row."""
    inner = _filtered_jobs_query(location, company, source_type, skill, q, since_days)
    total = await db.scalar(select(func.count()).select_from(inner.subquery()))
    return {"total": total or 0}


@router.get("/{job_id}", response_model=JobPostingOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobPostingOut, status_code=201, dependencies=[Depends(require_admin_key)])
@limiter.limit("10/minute")
async def create_job(request: Request, payload: JobPostingCreate, db: AsyncSession = Depends(get_db)):
    job = JobPosting(**payload.model_dump())
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job
