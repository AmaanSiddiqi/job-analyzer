from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services.scraper import run_scrape

router = APIRouter(prefix="/scrape", tags=["scrape"])


class ScrapeRequest(BaseModel):
    keywords: str = "software engineer"
    max_pages: int = Field(2, ge=1, le=8)


class ScrapeResponse(BaseModel):
    fetched: int
    inserted: int
    skipped: int


@router.post("", response_model=ScrapeResponse)
async def scrape_jobs(payload: ScrapeRequest, db: AsyncSession = Depends(get_db)):
    result = await run_scrape(payload.keywords, payload.max_pages, db)
    return ScrapeResponse(**result)
