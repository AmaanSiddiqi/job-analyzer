from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import JobPosting
from ..schemas import JobPostingCreate, JobPostingOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobPostingOut])
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    location: str | None = Query(None),
    company: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(JobPosting).order_by(JobPosting.date_scraped.desc())
    if location:
        stmt = stmt.where(func.lower(JobPosting.location).contains(location.lower()))
    if company:
        stmt = stmt.where(func.lower(JobPosting.company) == company.lower())
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobPostingOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobPosting, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", response_model=JobPostingOut, status_code=201)
async def create_job(payload: JobPostingCreate, db: AsyncSession = Depends(get_db)):
    job = JobPosting(**payload.model_dump())
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job
