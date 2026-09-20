from datetime import datetime

from pydantic import BaseModel


class JobPostingBase(BaseModel):
    title: str
    company: str
    location: str
    skills: list[str]
    source_url: str
    raw_description: str


class JobPostingCreate(JobPostingBase):
    pass


class JobPostingOut(JobPostingBase):
    id: int
    date_scraped: datetime
    # Which pipeline produced the row: greenhouse | lever | ashby | adzuna |
    # jooble | linkedin (legacy). Additive — existing clients ignore it.
    source_type: str = "linkedin"

    model_config = {"from_attributes": True}


class SourceCount(BaseModel):
    source_type: str
    count: int


class SourceTrendsResponse(BaseModel):
    """Per-source posting counts — the P1 DoD's 'per-source counts visible'."""

    total_jobs: int
    sources: list[SourceCount]
    # Same breakdown restricted to the last 7 days, so a stalled source is
    # visible even when its historical total is large.
    recent_sources: list[SourceCount]


class SkillTrend(BaseModel):
    skill: str
    count: int


class RoleTrend(BaseModel):
    title: str
    count: int


class SkillTrendsResponse(BaseModel):
    total_jobs: int
    top_skills: list[SkillTrend]
    # "extracted" = LLM canonical taxonomy ids over eligible board postings;
    # "baseline" = the frozen spaCy vocabulary over every indexed posting.
    # The two count different populations, so the UI states which it is showing.
    source: str = "baseline"


class RoleTrendsResponse(BaseModel):
    total_jobs: int
    top_roles: list[RoleTrend]


class StatsResponse(BaseModel):
    total_jobs: int
    total_companies: int
    last_scraped: datetime | None


class CompanyTrend(BaseModel):
    company: str
    count: int


class CompanyTrendsResponse(BaseModel):
    total_jobs: int
    top_companies: list[CompanyTrend]


class SkillWeekPoint(BaseModel):
    week: datetime
    count: int
    # Postings dated to this week across all skills, and this skill's share of
    # them. Share is what the chart plots: raw counts are not comparable across
    # the LinkedIn -> board-JSON source change, a percentage is.
    total: int = 0
    share: float = 0.0


class SkillHistorySeries(BaseModel):
    skill: str
    data: list[SkillWeekPoint]


class SkillHistoryResponse(BaseModel):
    source: str = "baseline"
    series: list[SkillHistorySeries]
