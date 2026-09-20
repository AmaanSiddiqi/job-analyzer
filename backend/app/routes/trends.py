from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..extraction.prompts import PROMPT_VERSION
from ..models import JobPosting, ListingComponent
from ..schemas import (
    CompanyTrend,
    CompanyTrendsResponse,
    RoleTrend,
    RoleTrendsResponse,
    SkillHistoryResponse,
    SkillHistorySeries,
    SkillTrend,
    SkillTrendsResponse,
    SkillWeekPoint,
    SourceCount,
    SourceTrendsResponse,
    StatsResponse,
)
from ..settings import get_settings

router = APIRouter(prefix="/trends", tags=["trends"])


async def _total_jobs(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(JobPosting))
    return result.scalar_one()


@router.get("/skills", response_model=SkillTrendsResponse)
async def trends_skills(
    top_n: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Top skills by frequency.

    Two sources, switched by `TRENDS_USE_EXTRACTED_SKILLS` (see settings):

      * **extracted** — canonical taxonomy ids from the LLM extractor. Context
        decides membership, so "we go to market" is not the Go language, while
        the baseline's PhraseMatcher counts it (and "on-the-go", "go-getter").
        Covers eligible board postings only — fewer rows, but the ones a user
        can still apply to.
      * **baseline** — the frozen spaCy vocabulary over every indexed posting,
        including archived LinkedIn rows. The fallback, so the live site never
        depends on a backfill having run.
    """
    if get_settings().trends_use_extracted_skills:
        rows = (
            await db.execute(
                select(
                    func.unnest(ListingComponent.skills).label("skill"),
                    func.count().label("n"),
                )
                .where(ListingComponent.prompt_version == PROMPT_VERSION)
                .group_by(text("skill"))
                .order_by(text("n DESC"))
                .limit(top_n)
            )
        ).all()
        total = await db.scalar(
            select(func.count())
            .select_from(ListingComponent)
            .where(ListingComponent.prompt_version == PROMPT_VERSION)
        )
        return SkillTrendsResponse(
            total_jobs=total or 0,
            top_skills=[SkillTrend(skill=r.skill, count=r.n) for r in rows],
            source="extracted",
        )

    # Label as "n", not "count" — SQLAlchemy's Row is tuple-like, and a
    # column named "count" shadows tuple.count() for attribute access.
    stmt = (
        select(
            func.unnest(JobPosting.skills).label("skill"),
            func.count().label("n"),
        )
        .group_by(text("skill"))
        .order_by(text("n DESC"))
        .limit(top_n)
    )
    result = await db.execute(stmt)
    top_skills = [SkillTrend(skill=row.skill, count=row.n) for row in result.all()]
    return SkillTrendsResponse(
        total_jobs=await _total_jobs(db), top_skills=top_skills, source="baseline"
    )


@router.get("/roles", response_model=RoleTrendsResponse)
async def trends_roles(
    top_n: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Most common job titles across all indexed postings."""
    stmt = (
        select(JobPosting.title, func.count().label("n"))
        .group_by(JobPosting.title)
        .order_by(text("n DESC"))
        .limit(top_n)
    )
    result = await db.execute(stmt)
    top_roles = [RoleTrend(title=row.title, count=row.n) for row in result.all()]
    return RoleTrendsResponse(total_jobs=await _total_jobs(db), top_roles=top_roles)


@router.get("/companies", response_model=CompanyTrendsResponse)
async def trends_companies(
    top_n: int = Query(15, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Most active hiring companies across all indexed postings."""
    stmt = (
        select(JobPosting.company, func.count().label("n"))
        .group_by(JobPosting.company)
        .order_by(text("n DESC"))
        .limit(top_n)
    )
    result = await db.execute(stmt)
    top_companies = [CompanyTrend(company=row.company, count=row.n) for row in result.all()]
    return CompanyTrendsResponse(total_jobs=await _total_jobs(db), top_companies=top_companies)


@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Summary stats for the dashboard header."""
    total_jobs = await db.scalar(select(func.count()).select_from(JobPosting)) or 0
    total_companies = await db.scalar(
        select(func.count(func.distinct(JobPosting.company))).select_from(JobPosting)
    ) or 0
    last_scraped = await db.scalar(select(func.max(JobPosting.date_scraped)).select_from(JobPosting))
    return StatsResponse(total_jobs=total_jobs, total_companies=total_companies, last_scraped=last_scraped)


@router.get("/sources", response_model=SourceTrendsResponse)
async def trends_sources(db: AsyncSession = Depends(get_db)):
    """Posting counts per ingestion source, all-time and last 7 days.

    The recent window is what makes a stalled source obvious — a large
    historical total (e.g. the frozen LinkedIn corpus) otherwise hides the
    fact that nothing new is arriving from it.
    """
    all_time = (
        await db.execute(
            select(JobPosting.source_type, func.count().label("n"))
            .group_by(JobPosting.source_type)
            .order_by(text("n DESC"))
        )
    ).all()
    cutoff = datetime.now(UTC) - timedelta(days=7)
    recent = (
        await db.execute(
            select(JobPosting.source_type, func.count().label("n"))
            .where(JobPosting.date_scraped >= cutoff)
            .group_by(JobPosting.source_type)
            .order_by(text("n DESC"))
        )
    ).all()
    return SourceTrendsResponse(
        total_jobs=await _total_jobs(db),
        sources=[SourceCount(source_type=s, count=n) for s, n in all_time],
        recent_sources=[SourceCount(source_type=s, count=n) for s, n in recent],
    )


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
    use_extracted = get_settings().trends_use_extracted_skills
    source = "extracted" if use_extracted else "baseline"

    if not skills:
        # Default series must come from the same vocabulary the rest of the
        # response uses, or the chart asks for skills this source never emits.
        default_top = (
            select(
                func.unnest(ListingComponent.skills).label("skill"),
                func.count().label("n"),
            ).where(ListingComponent.prompt_version == PROMPT_VERSION)
            if use_extracted
            else select(
                func.unnest(JobPosting.skills).label("skill"),
                func.count().label("n"),
            )
        )
        top = await db.execute(
            default_top.group_by(text("skill")).order_by(text("n DESC")).limit(5)
        )
        skills = [row.skill for row in top.all()]

    if not skills:
        return SkillHistoryResponse(series=[], source=source)

    # Bucket by when the employer *posted* the listing, not when we scraped it.
    # Scrape date made this a history of our own ingestion: the Aug 2026 board
    # backfill loaded 1,331 already-open postings in one run and showed up as a
    # one-week spike. job_postings has no posted_at, so it comes from
    # raw_listings (append-only, hence min() per URL); LinkedIn rows have none
    # and fall back to scrape date, which for a daily scraper is close enough.
    stmt = text("""
        WITH posted AS (
            SELECT source_url, min(posted_at) AS posted_at
            FROM raw_listings
            WHERE posted_at IS NOT NULL
            GROUP BY source_url
        ),
        dated AS (
            SELECT
                jp.skills,
                date_trunc('week', COALESCE(p.posted_at, jp.date_scraped))::date AS week
            FROM job_postings jp
            LEFT JOIN posted p ON p.source_url = jp.source_url
            WHERE COALESCE(p.posted_at, jp.date_scraped)
                  >= now() - make_interval(weeks => :weeks)
        ),
        totals AS (
            SELECT week, count(*) AS total FROM dated GROUP BY week
        )
        SELECT d.week, skill, count(*) AS n, t.total
        FROM dated d
        CROSS JOIN LATERAL unnest(d.skills) AS skill
        JOIN totals t ON t.week = d.week
        WHERE skill = ANY(:skills)
        GROUP BY d.week, skill, t.total
        ORDER BY 1, 2
    """)
    params: dict = {"weeks": weeks, "skills": list(skills)}
    if use_extracted:
        # Same shape — share of each week's postings — over extracted
        # components, dated from raw_listings (job_postings has no posted_at).
        stmt = text("""
            WITH dated AS (
                SELECT lc.skills,
                       date_trunc('week', COALESCE(r.posted_at, r.fetched_at))::date AS week
                FROM listing_components lc
                JOIN raw_listings r ON r.id = lc.raw_listing_id
                WHERE lc.prompt_version = :prompt_version
                  AND COALESCE(r.posted_at, r.fetched_at)
                      >= now() - make_interval(weeks => :weeks)
            ),
            totals AS (SELECT week, count(*) AS total FROM dated GROUP BY week)
            SELECT d.week, skill, count(*) AS n, t.total
            FROM dated d
            CROSS JOIN LATERAL unnest(d.skills) AS skill
            JOIN totals t ON t.week = d.week
            WHERE skill = ANY(:skills)
            GROUP BY d.week, skill, t.total
            ORDER BY 1, 2
        """)
        params["prompt_version"] = PROMPT_VERSION
    rows = (await db.execute(stmt, params)).all()

    by_skill: dict[str, list[SkillWeekPoint]] = defaultdict(list)
    for row in rows:
        by_skill[row.skill].append(
            SkillWeekPoint(
                week=row.week,
                count=row.n,
                total=row.total,
                share=round(row.n / row.total, 4) if row.total else 0.0,
            )
        )

    series = [
        SkillHistorySeries(skill=skill, data=by_skill.get(skill, []))
        for skill in skills
    ]
    return SkillHistoryResponse(series=series, source=source)
