from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import JobPosting
from ..schemas import (
    SkillTrendsResponse, SkillTrend,
    RoleTrendsResponse, RoleTrend,
    StatsResponse,
    SkillHistoryResponse, SkillHistorySeries, SkillWeekPoint,
)

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


@router.get("/skills/history", response_model=SkillHistoryResponse)
async def trends_skill_history(
    skills: list[str] = Query(default=[], alias="skills"),
    weeks: int = Query(8, ge=1, le=52),
    db: AsyncSession = Depends(get_db),
):
    """
    Weekly posting counts for a set of skills over the last N weeks.
    If no skills are specified, defaults to the top 5 by overall frequency.
    """
    if not skills:
        top = await db.execute(
            select(
                func.unnest(JobPosting.skills).label("skill"),
                func.count().label("count"),
            )
            .group_by(text("skill"))
            .order_by(text("count DESC"))
            .limit(5)
        )
        skills = [row.skill for row in top.all()]

    if not skills:
        return SkillHistoryResponse(series=[])

    stmt = text("""
        SELECT
            date_trunc('week', date_scraped)::date AS week,
            skill,
            count(*) AS count
        FROM job_postings, unnest(skills) AS skill
        WHERE date_scraped >= now() - make_interval(weeks => :weeks)
          AND skill = ANY(:skills)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """)
    rows = (await db.execute(stmt, {"weeks": weeks, "skills": list(skills)})).all()

    by_skill: dict[str, list[SkillWeekPoint]] = defaultdict(list)
    for row in rows:
        by_skill[row.skill].append(SkillWeekPoint(week=row.week, count=row.count))

    series = [
        SkillHistorySeries(skill=skill, data=by_skill.get(skill, []))
        for skill in skills
    ]
    return SkillHistoryResponse(series=series)
