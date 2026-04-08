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
