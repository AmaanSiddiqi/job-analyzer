"""Adzuna and Jooble API clients — the breadth channel.

Both are free-tier keyword-search APIs covering employers far beyond the
curated board list. Descriptions are often truncated and URLs are redirects,
so this data is thinner than board JSON — it feeds raw_listings (extraction
input) and company discovery; whether it also reaches job_postings is the
AGGREGATORS_TO_POSTINGS setting (see settings.py for the dedup rationale).

Response shapes were written against the public API docs; the first run with
real credentials validates them (normalizers are deliberately defensive).
"""

import logging
from datetime import datetime
from typing import Any

import httpx

from ..settings import Settings
from .boards import BoardFetchError, FetchedListing, html_to_text

log = logging.getLogger(__name__)

# Same role coverage as the legacy scheduler's keyword list.
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

_ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/ca/search/{page}"
_JOOBLE_URL = "https://jooble.org/api/{key}"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch_adzuna(
    client: httpx.AsyncClient, settings: Settings, keyword: str
) -> list[FetchedListing]:
    """Fetch up to adzuna_pages_per_keyword pages for one keyword (Canada)."""
    listings: list[FetchedListing] = []
    for page in range(1, settings.adzuna_pages_per_keyword + 1):
        try:
            resp = await client.get(
                _ADZUNA_URL.format(page=page),
                params={
                    "app_id": settings.adzuna_app_id,
                    "app_key": settings.adzuna_app_key,
                    "what": keyword,
                    "results_per_page": 50,
                    "max_days_old": settings.aggregator_max_days_old,
                    "content-type": "application/json",
                },
            )
        except httpx.HTTPError as e:
            raise BoardFetchError(f"adzuna '{keyword}' p{page}: {e}") from e
        if resp.status_code != 200:
            raise BoardFetchError(f"adzuna '{keyword}' p{page}: HTTP {resp.status_code}")
        results = resp.json().get("results") or []
        for job in results:
            listing = _normalize_adzuna(job)
            if listing:
                listings.append(listing)
        if len(results) < 50:
            break  # last page
    return listings


def _normalize_adzuna(job: dict[str, Any]) -> FetchedListing | None:
    company = (job.get("company") or {}).get("display_name")
    url = job.get("redirect_url")
    title = job.get("title")
    if not (company and url and title and job.get("id")):
        return None
    return FetchedListing(
        source_type="adzuna",
        source_name="adzuna-ca",
        external_id=str(job["id"]),
        source_url=url,
        title=html_to_text(title, inline=True),  # Adzuna wraps matches in <strong>
        company=company,
        location=(job.get("location") or {}).get("display_name"),
        description=html_to_text(job.get("description") or ""),
        posted_at=_parse_iso(job.get("created")),
        payload=job,
    )


async def fetch_jooble(
    client: httpx.AsyncClient, settings: Settings, keyword: str
) -> list[FetchedListing]:
    """POST search for one keyword (Canada), paging up to the configured max."""
    listings: list[FetchedListing] = []
    for page in range(1, settings.jooble_pages_per_keyword + 1):
        try:
            resp = await client.post(
                _JOOBLE_URL.format(key=settings.jooble_api_key),
                json={"keywords": keyword, "location": "Canada", "page": page},
            )
        except httpx.HTTPError as e:
            raise BoardFetchError(f"jooble '{keyword}' p{page}: {e}") from e
        if resp.status_code != 200:
            raise BoardFetchError(f"jooble '{keyword}' p{page}: HTTP {resp.status_code}")
        jobs = resp.json().get("jobs") or []
        for job in jobs:
            listing = _normalize_jooble(job)
            if listing:
                listings.append(listing)
        if not jobs:
            break
    return listings


def _normalize_jooble(job: dict[str, Any]) -> FetchedListing | None:
    company = job.get("company")
    url = job.get("link")
    title = job.get("title")
    if not (company and url and title and job.get("id") is not None):
        return None
    return FetchedListing(
        source_type="jooble",
        source_name="jooble-ca",
        external_id=str(job["id"]),
        source_url=url,
        title=html_to_text(title, inline=True),
        company=company,
        location=job.get("location"),
        description=html_to_text(job.get("snippet") or ""),
        posted_at=_parse_iso(job.get("updated")),
        payload=job,
    )
