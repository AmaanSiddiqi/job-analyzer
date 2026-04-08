from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import JobPosting
from ..schemas import SkillTrendsResponse, SkillTrend, RoleTrendsResponse, RoleTrend, StatsResponse

router = APIRouter(prefix="/trends", tags=["trends"])


async def _total_jobs(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(JobPosting))
    return result.scalar_one()


@router.get("/skills", response_model=SkillTrendsResponse)
async def trends_skills(
    top_n: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Top skills by frequency across all indexed postings."""
    stmt = (
        select(
            func.unnest(JobPosting.skills).label("skill"),
            func.count().label("count"),
        )
        .group_by(text("skill"))
        .order_by(text("count DESC"))
        .limit(top_n)
    )
    result = await db.execute(stmt)
    top_skills = [SkillTrend(skill=row.skill, count=row.count) for row in result.all()]
    return SkillTrendsResponse(total_jobs=await _total_jobs(db), top_skills=top_skills)


@router.get("/roles", response_model=RoleTrendsResponse)
async def trends_roles(
    top_n: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Most common job titles across all indexed postings."""
    stmt = (
        select(JobPosting.title, func.count().label("count"))
        .group_by(JobPosting.title)
        .order_by(text("count DESC"))
        .limit(top_n)
    )
    result = await db.execute(stmt)
    top_roles = [RoleTrend(title=row.title, count=row.count) for row in result.all()]
    return RoleTrendsResponse(total_jobs=await _total_jobs(db), top_roles=top_roles)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Summary stats for the dashboard header."""
    total_jobs = await db.scalar(select(func.count()).select_from(JobPosting)) or 0
    total_companies = await db.scalar(
        select(func.count(func.distinct(JobPosting.company))).select_from(JobPosting)
    ) or 0
    last_scraped = await db.scalar(select(func.max(JobPosting.date_scraped)).select_from(JobPosting))
    return StatsResponse(total_jobs=total_jobs, total_companies=total_companies, last_scraped=last_scraped)
