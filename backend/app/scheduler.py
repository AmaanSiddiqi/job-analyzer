import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .database import AsyncSessionLocal
from .services.scraper import run_scrape

log = logging.getLogger(__name__)

# Keywords scraped on every scheduled run
KEYWORDS = [
    "software engineer",
    "data engineer",
    "frontend developer",
    "backend developer",
    "devops engineer",
    "data scientist",
    "machine learning engineer",
    "full stack developer",
]

_scheduler = AsyncIOScheduler(timezone="America/Vancouver")


async def _scrape_all() -> None:
    log.info("Scheduled scrape starting — %d keywords", len(KEYWORDS))
    for keyword in KEYWORDS:
        try:
            async with AsyncSessionLocal() as db:
                result = await run_scrape(keyword, max_pages=2, db=db)
            log.info("  '%s' → inserted=%d skipped=%d", keyword, result["inserted"], result["skipped"])
        except Exception:
            log.exception("  '%s' failed", keyword)
        await asyncio.sleep(2)  # brief pause between keywords
    log.info("Scheduled scrape complete")


def start(interval_hours: int = 6) -> None:
    _scheduler.add_job(
        _scrape_all,
        trigger=IntervalTrigger(hours=interval_hours),
        id="scrape_all",
        replace_existing=True,
        misfire_grace_time=300,
    )
    _scheduler.start()
    log.info("Scheduler started — every %d hours", interval_hours)


def stop() -> None:
    _scheduler.shutdown(wait=False)
