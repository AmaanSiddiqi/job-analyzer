import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, AsyncSessionLocal
from ..services.scraper import LinkedInScrapingDisabled, linkedin_scraper_enabled, run_scrape
from ..scheduler import KEYWORDS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scrape", tags=["scrape"])


class ScrapeRequest(BaseModel):
    keywords: str = "software engineer"
    max_pages: int = Field(2, ge=1, le=40)
    location: str = "Canada"


class ScrapeResponse(BaseModel):
    fetched: int
    inserted: int
    skipped: int


class BulkScrapeRequest(BaseModel):
    max_pages: int = Field(10, ge=1, le=40)
    location: str = "Canada"


class BulkScrapeStarted(BaseModel):
    status: str
    keywords: list[str]
    max_pages: int
    location: str


@router.post("", response_model=ScrapeResponse)
async def scrape_jobs(payload: ScrapeRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await run_scrape(payload.keywords, payload.max_pages, db, location=payload.location)
    except LinkedInScrapingDisabled as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return ScrapeResponse(**result)


async def _run_bulk(max_pages: int, location: str) -> None:
    log.info("Bulk scrape starting — %d keywords × %d pages @ %s", len(KEYWORDS), max_pages, location)
    for keyword in KEYWORDS:
        try:
            async with AsyncSessionLocal() as db:
                result = await run_scrape(keyword, max_pages, db, location=location)
            log.info("  bulk '%s' → inserted=%d skipped=%d", keyword, result["inserted"], result["skipped"])
        except Exception:
            log.exception("  bulk '%s' failed", keyword)
        await asyncio.sleep(3)
    log.info("Bulk scrape complete")


@router.post("/bulk", response_model=BulkScrapeStarted)
async def scrape_bulk(
    background_tasks: BackgroundTasks,
    payload: BulkScrapeRequest = BulkScrapeRequest(),
):
    """Kick off a full scrape of all preset keywords in the background."""
    if not linkedin_scraper_enabled():
        raise HTTPException(
            status_code=503,
            detail=(
                "LinkedIn scraping is disabled (deprecated data source — see CLAUDE.md's "
                "'Data source transition'). Set ENABLE_LINKEDIN_SCRAPER=true to re-enable temporarily."
            ),
        )
    background_tasks.add_task(_run_bulk, payload.max_pages, payload.location)
    return BulkScrapeStarted(
        status="started",
        keywords=KEYWORDS,
        max_pages=payload.max_pages,
        location=payload.location,
    )
