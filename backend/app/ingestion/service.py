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
    "st. john's", "quebec city", "pointe claire", "pointe-claire", "laval",
    "markham", "brampton", "richmond hill", "mississauga", "vaughan",
    "gatineau", "sherbrooke", "kelowna", "windsor, on", "kanata", "longueuil",
)
# ", ON" / "(BC)" style province codes — word-bounded so "London" ≠ "LON".
_PROVINCE_CODE = re.compile(
    r"(?:^|[\s,(])(on|qc|bc|ab|mb|sk|ns|nb|nl|pe|yt|nt|nu)(?:$|[\s,).|])", re.IGNORECASE
)
# Foreign countries/regions/cities observed on the configured boards. Bounded
# by what those companies actually post — grow it as leaks are noticed.
_FOREIGN = (
    "united states", "usa", "remote us", "remote - us", "remote (us", "us remote",
    "emea", "europe", "united kingdom", "england", "scotland", "ireland",
    "latam", "apac", "germany", "france", "spain", "italy", "portugal",
    "netherlands", "belgium", "poland", "romania", "bulgaria", "hungary",
    "serbia", "sweden", "switzerland", "luxembourg", "india", "australia",
    "new zealand", "mexico", "brazil", "argentina", "colombia", "chile",
    "japan", "korea", "singapore", "china", "israel", "uae", "dubai", "qatar",
    "taiwan", "taipei", "saudi", "ksa", "nairobi", "kenya", "nigeria", "egypt",
    "philippines", "manila", "vietnam", "thailand", "indonesia", "malaysia",
    "pittsburgh", "cyprus", "hamburg", "lyon", "auckland", "glasgow",
    "new york", "san francisco", "boston", "austin", "seattle", "chicago",
    "denver", "los angeles", "washington", "phoenix", "dallas", "atlanta",
    "miami", "nashville", "portland", "salt lake", "san diego", "houston",
    "london", "paris", "berlin", "munich", "cologne", "frankfurt", "amsterdam",
    "barcelona", "madrid", "malaga", "milan", "dublin", "belfast", "ghent",
    "zurich", "stockholm", "gothenburg", "bucharest", "athens", "melbourne",
    "sydney", "tokyo", "seoul", "delhi", "mumbai", "bangalore", "mexico city",
    "latin america", "santiago", "massachusetts", "california", "texas",
    "virginia", "florida", "colorado", "illinois", "michigan", "pennsylvania",
    "new jersey", "minnesota", "tennessee", "utah", "oregon", "arizona",
    "nevada", "missouri", "indiana", "wisconsin", "kentucky", "oklahoma",
)
# "US"/"USA"/"U.S." need word bounds — a substring match would hit "AUStralia".
_US_RE = re.compile(r"\bu\.?s\.?a?\.?\b", re.IGNORECASE)
# "Pittsburgh, PA" / "Lenexa, KS" — US state codes, none of which collide with
# a Canadian province code (and the province check runs first regardless).
_US_STATE_CODE = re.compile(
    r"(?:^|[\s,(])(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo"
    r"|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|dc)"
    r"(?:$|[\s,).|])",
    re.IGNORECASE,
)


# Regions that include Canada — a remote role scoped to these is in scope.
_CA_INCLUSIVE = ("north america", "americas", "worldwide", "global", "anywhere")
# Tokens that only describe work arrangement, never a place.
_ARRANGEMENT = ("remote", "hybrid", "on-site", "onsite", "in-office", "flexible")


def _segment_kind(segment: str) -> str:
    """Classify one location segment.

    Returns 'ca' (Canadian or Canada-inclusive), 'foreign' (a recognized
    non-Canadian place, or remote *scoped* to an unrecognized place),
    'arrangement' (only says how you work — "Remote", "Hybrid"), or 'unknown'
    (an unrecognized place name with no remote qualifier).

    Strong Canadian signals (the word Canada, full province names, word-bounded
    province codes) are checked before the foreign list so "London, ON" wins
    over "london"; the bare-city list is checked after it so "Melbourne,
    Victoria" reads as foreign, not as Victoria BC.
    """
    seg = segment.lower()
    if "canada" in seg or "(can)" in seg or any(p in seg for p in _PROVINCES):
        return "ca"
    if _PROVINCE_CODE.search(segment):
        return "ca"
    if any(r in seg for r in _CA_INCLUSIVE):
        return "ca"
    if any(f in seg for f in _FOREIGN) or _US_RE.search(seg) or _US_STATE_CODE.search(segment):
        return "foreign"
    if any(c in seg for c in _CITIES):
        return "ca"

    residue = seg
    for word in _ARRANGEMENT:
        residue = residue.replace(word, " ")
    has_place = bool(re.sub(r"[^a-z]", "", residue))
    if has_place:
        # "Remote Saudi Arabia" / "Remote, KSA": naming a place next to "remote"
        # scopes the role there, so it's foreign even if the country isn't
        # listed. Without a remote qualifier it's just a place we don't
        # recognize (a small Canadian town, "TBD") — lean keep.
        return "foreign" if seg != residue else "unknown"
    return "arrangement"


def looks_canadian(location: str | None) -> bool:
    """Keep listings with any Canadian location segment; drop ones whose only
    named places are foreign. Wrong-keeps are cheap (staleness ages them out);
    wrong-drops silently lose relevant jobs — so unknowns lean keep."""
    if not location:
        return True
    kinds = {_segment_kind(seg) for seg in re.split(r"[|;]", location) if seg.strip()}
    if "ca" in kinds:
        return True
    if "foreign" in kinds:
        return False
    # "Hamburg | Remote": an unrecognized place beside a remote tag is a role
    # scoped to that place, same as the single-segment case above.
    return not ("arrangement" in kinds and "unknown" in kinds)


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
    # Same source_url seen twice in one run (aggregator keywords overlap) —
    # skipped before the location filter, so fetched != kept + filtered without it.
    duplicate_in_run: int = 0
    new_raw: int = 0
    new_postings: int = 0
    failed_boards: list[str] = field(default_factory=list)


async def store_listing(db: AsyncSession, listing: FetchedListing, counts: SourceCounts) -> None:
    """Dual-write one listing (raw_listings + job_postings), idempotently.

    Shared by board and aggregator ingestion — the writes are identical, only
    the fetch side differs.
    """
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
            await store_listing(db, listing, per_source)

    await db.commit()
    for board, c in counts.items():
        log.info(
            "ingestion %s: fetched=%d kept=%d filtered=%d new_raw=%d new_postings=%d failed=%s",
            board, c.fetched, c.kept, c.filtered_location, c.new_raw, c.new_postings,
            c.failed_boards or "none",
        )
    return counts


async def _store_raw_only(db: AsyncSession, listing: FetchedListing, counts: SourceCounts) -> None:
    """raw_listings write only — aggregator default until P2 canonical dedup
    (see Settings.aggregators_to_postings for why job_postings is skipped)."""
    digest = content_hash(listing.title, listing.company, listing.location, listing.description)
    stmt = (
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
    result = await db.execute(stmt)
    if result.rowcount:  # type: ignore[attr-defined]
        counts.new_raw += 1


async def run_aggregator_ingestion(db: AsyncSession) -> dict[str, SourceCounts | int]:
    """Fetch Adzuna + Jooble for every keyword, store, and mine company
    suggestions. Returns per-source counts plus discovery stats."""
    from .aggregators import KEYWORDS, fetch_adzuna, fetch_jooble
    from .discovery import record_suggestions

    settings = get_settings()
    counts = {"adzuna": SourceCounts(), "jooble": SourceCounts()}
    all_listings: list[FetchedListing] = []

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for keyword in KEYWORDS:
            for source, fetcher, configured in (
                ("adzuna", fetch_adzuna, bool(settings.adzuna_app_id and settings.adzuna_app_key)),
                ("jooble", fetch_jooble, bool(settings.jooble_api_key)),
            ):
                if not configured:
                    continue
                try:
                    listings = await fetcher(client, settings, keyword)
                except BoardFetchError as e:
                    log.warning("aggregator fetch failed: %s", e)
                    counts[source].failed_boards.append(keyword)
                    continue
                counts[source].fetched += len(listings)
                all_listings.extend(listings)

    seen_urls: set[str] = set()
    for listing in all_listings:
        per_source = counts[listing.source_type]
        # Same URL appears under multiple keywords — first hit wins this run;
        # cross-run idempotency is the DB constraint's job.
        if listing.source_url in seen_urls:
            per_source.duplicate_in_run += 1
            continue
        seen_urls.add(listing.source_url)
        if settings.board_canada_only and not looks_canadian(listing.location):
            per_source.filtered_location += 1
            continue
        per_source.kept += 1
        if settings.aggregators_to_postings:
            await store_listing(db, listing, per_source)
        else:
            await _store_raw_only(db, listing, per_source)

    new_suggestions = await record_suggestions(
        db, [listing for listing in all_listings if listing.source_url in seen_urls]
    )
    await db.commit()
    for source, c in counts.items():
        log.info(
            "aggregator %s: fetched=%d kept=%d filtered=%d dup_in_run=%d new_raw=%d failed_keywords=%s",
            source, c.fetched, c.kept, c.filtered_location, c.duplicate_in_run, c.new_raw,
            c.failed_boards or "none",
        )
    log.info("company discovery: %d new suggestions", new_suggestions)
    return {**counts, "new_company_suggestions": new_suggestions}
