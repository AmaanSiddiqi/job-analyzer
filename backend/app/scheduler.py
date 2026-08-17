import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .database import AsyncSessionLocal
from .services.scraper import linkedin_scraper_enabled, run_scrape
from .settings import get_settings

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


_LOCATION = "Canada"


async def _scrape_all() -> None:
    log.info("Scheduled scrape starting — %d keywords @ %s", len(KEYWORDS), _LOCATION)
    for keyword in KEYWORDS:
        try:
            async with AsyncSessionLocal() as db:
                result = await run_scrape(keyword, max_pages=4, db=db, location=_LOCATION)
            log.info("  '%s' → inserted=%d skipped=%d", keyword, result["inserted"], result["skipped"])
        except Exception:
            log.exception("  '%s' failed", keyword)
        await asyncio.sleep(3)
    log.info("Scheduled scrape complete")


async def _ingest_boards() -> None:
    # Local import so the scheduler module doesn't pull ingestion (and spaCy
    # via its nlp import) at startup unless a job actually runs.
    from .ingestion.service import run_board_ingestion

    log.info("Scheduled board ingestion starting")
    try:
        async with AsyncSessionLocal() as db:
            await run_board_ingestion(db)
    except Exception:
        log.exception("Scheduled board ingestion failed")
    log.info("Scheduled board ingestion complete")


async def _ingest_aggregators() -> None:
    from .ingestion.service import run_aggregator_ingestion

    log.info("Scheduled aggregator ingestion starting")
    try:
        async with AsyncSessionLocal() as db:
            await run_aggregator_ingestion(db)
    except Exception:
        log.exception("Scheduled aggregator ingestion failed")
    log.info("Scheduled aggregator ingestion complete")


def start(interval_hours: int = 6) -> None:
    settings = get_settings()
    jobs = 0

    if linkedin_scraper_enabled():
        _scheduler.add_job(
            _scrape_all,
            trigger=IntervalTrigger(hours=interval_hours),
            id="scrape_all",
            replace_existing=True,
            misfire_grace_time=300,
        )
        jobs += 1
    else:
        log.info(
            "LinkedIn scraper is disabled (ENABLE_LINKEDIN_SCRAPER unset) — "
            "deprecated per CLAUDE.md; board-JSON/Adzuna/Jooble sources replace it."
        )

    if settings.enable_board_ingestion:
        _scheduler.add_job(
            _ingest_boards,
            trigger=IntervalTrigger(hours=settings.board_ingest_interval_hours),
            id="ingest_boards",
            replace_existing=True,
            misfire_grace_time=300,
        )
        jobs += 1
    else:
        log.info("Board ingestion is disabled (ENABLE_BOARD_INGESTION unset) — not scheduled.")

    if settings.enable_aggregator_ingestion:
        _scheduler.add_job(
            _ingest_aggregators,
            trigger=IntervalTrigger(hours=settings.board_ingest_interval_hours * 2),
            id="ingest_aggregators",
            replace_existing=True,
            misfire_grace_time=300,
        )
        jobs += 1
    else:
        log.info(
            "Aggregator ingestion is disabled (ENABLE_AGGREGATOR_INGESTION unset) — not scheduled."
        )

    if not jobs:
        log.info("No ingestion sources enabled — scheduler not started.")
        return

    _scheduler.start()
    log.info("Scheduler started — %d job(s)", jobs)


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
