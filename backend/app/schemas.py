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

    model_config = {"from_attributes": True}


class SkillTrend(BaseModel):
    skill: str
    count: int


class RoleTrend(BaseModel):
    title: str
    count: int


class SkillTrendsResponse(BaseModel):
    total_jobs: int
    top_skills: list[SkillTrend]


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


class SkillHistorySeries(BaseModel):
    skill: str
    data: list[SkillWeekPoint]


class SkillHistoryResponse(BaseModel):
    series: list[SkillHistorySeries]
