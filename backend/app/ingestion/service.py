"""Board ingestion run: fetch all configured boards → raw_listings + job_postings.

Dual-write design (P1 plan): every kept listing is (a) appended to
raw_listings — the append-only input the LLM extraction pipeline consumes —
and (b) upserted into job_postings with baseline spaCy skills so the live
dashboards get fresh data without waiting on the extraction pipeline.
Both writes are idempotent: raw_listings via its (source_type, source_url,
content_hash) constraint, job_postings via the source_url conflict target.
"""

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sources.config import Company, load_companies

from ..models import JobPosting, RawListing
from ..services import nlp
from ..settings import get_settings
from .boards import FETCHERS, USER_AGENT, BoardFetchError, FetchedListing

log = logging.getLogger(__name__)

_PROVINCES = (
    "ontario", "quebec", "québec", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "yukon", "northwest territories", "nunavut",
)
_CITIES = (
    "toronto", "montreal", "montréal", "vancouver", "ottawa", "calgary",
    "edmonton", "waterloo", "kitchener", "mississauga", "victoria", "winnipeg",
    "saskatoon", "halifax", "hamilton", "burnaby", "oakville", "fredericton",
    "moncton", "regina", "london, on", "guelph", "burlington, on",
    "st. john's", "quebec city",
)
# ", ON" / "(BC)" style province codes — word-bounded so "London" ≠ "LON".
_PROVINCE_CODE = re.compile(
    r"(?:^|[\s,(])(on|qc|bc|ab|mb|sk|ns|nb|nl|pe|yt|nt|nu)(?:$|[\s,).|])", re.IGNORECASE
)
_FOREIGN_REMOTE = (
    "remote us", "remote - us", "remote (us", "remote, us", "us remote",
    "remote usa", "remote - usa", "united states", "emea", "europe", "uk",
    "united kingdom", "latam", "apac", "germany", "france", "spain", "india",
    "australia", "mexico", "brazil",
)


def looks_canadian(location: str | None) -> bool:
    """Conservative filter: keep Canadian locations, unknowns, and remote
    listings that don't name a foreign scope. Wrong-keeps are cheap (staleness
    ages them out); wrong-drops silently lose relevant jobs — so lean keep."""
    if not location:
        return True
    loc = location.lower()
    if "canada" in loc or "(can)" in loc:
        return True
    if any(p in loc for p in _PROVINCES) or any(c in loc for c in _CITIES):
        return True
    if _PROVINCE_CODE.search(location):
        return True
    return "remote" in loc and not any(f in loc for f in _FOREIGN_REMOTE)


def content_hash(title: str, company: str, location: str | None, description: str) -> str:
    """Stable hash of the fields that constitute 'the same content'."""
    normalized = "\x1f".join(
        " ".join(part.split()).lower() for part in (title, company, location or "", description)
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass
class SourceCounts:
    fetched: int = 0
    kept: int = 0
    filtered_location: int = 0
    new_raw: int = 0
    new_postings: int = 0
    failed_boards: list[str] = field(default_factory=list)


async def _store(db: AsyncSession, listing: FetchedListing, counts: SourceCounts) -> None:
    digest = content_hash(listing.title, listing.company, listing.location, listing.description)

    raw_stmt = (
        pg_insert(RawListing)
        .values(
            source_type=listing.source_type,
            source_name=listing.source_name,
            external_id=listing.external_id,
            source_url=listing.source_url,
            content_hash=digest,
            title=listing.title,
            company=listing.company,
            location=listing.location,
            description=listing.description,
            posted_at=listing.posted_at,
            payload=listing.payload,
        )
        .on_conflict_do_nothing(constraint="uq_raw_listings_source_content")
    )
    result = await db.execute(raw_stmt)
    if result.rowcount:  # type: ignore[attr-defined]  # same Core-DML narrowing issue as services/scraper.py
        counts.new_raw += 1

    posting_stmt = (
        pg_insert(JobPosting)
        .values(
            title=listing.title,
            company=listing.company,
            location=listing.location or "Unknown",
            skills=nlp.extract_skills(listing.description),
            source_url=listing.source_url,
            raw_description=listing.description,
            source_type=listing.source_type,
        )
        .on_conflict_do_nothing(index_elements=["source_url"])
    )
    result = await db.execute(posting_stmt)
    if result.rowcount:  # type: ignore[attr-defined]
        counts.new_postings += 1


async def run_board_ingestion(
    db: AsyncSession, companies: tuple[Company, ...] | None = None
) -> dict[str, SourceCounts]:
    """Fetch every configured board and store listings. Returns per-source counts.

    One failed board never aborts the run — it's recorded in failed_boards
    for the per-source health view and the run continues.
    """
    settings = get_settings()
    if companies is None:
        companies = load_companies().companies

    sem = asyncio.Semaphore(settings.board_fetch_concurrency)
    counts: dict[str, SourceCounts] = {
        board: SourceCounts() for board in sorted({c.board for c in companies})
    }

    async def fetch_one(company: Company) -> list[FetchedListing]:
        async with sem:
            return await FETCHERS[company.board](client, company.token, company.name)

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        results = await asyncio.gather(
            *[fetch_one(c) for c in companies], return_exceptions=True
        )

    for company, result in zip(companies, results, strict=True):
        per_source = counts[company.board]
        if isinstance(result, BaseException):
            if not isinstance(result, BoardFetchError):
                raise result
            log.warning("board fetch failed: %s/%s: %s", company.board, company.token, result)
            per_source.failed_boards.append(company.token)
            continue
        per_source.fetched += len(result)
        for listing in result:
            if settings.board_canada_only and not looks_canadian(listing.location):
                per_source.filtered_location += 1
                continue
            per_source.kept += 1
            await _store(db, listing, per_source)

    await db.commit()
    for board, c in counts.items():
        log.info(
            "ingestion %s: fetched=%d kept=%d filtered=%d new_raw=%d new_postings=%d failed=%s",
            board, c.fetched, c.kept, c.filtered_location, c.new_raw, c.new_postings,
            c.failed_boards or "none",
        )
    return counts
