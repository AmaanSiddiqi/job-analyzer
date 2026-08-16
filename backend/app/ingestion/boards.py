"""Async clients for the three public job-board APIs.

Each fetcher makes ONE request per company (all three APIs return full
descriptions in the list call — Greenhouse via ?content=true) and returns
normalized FetchedListing objects. HTTP failures raise BoardFetchError so
the service layer can count per-source health without one dead board
aborting the whole run.
"""

import asyncio
import html
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

USER_AGENT = "job-analyzer-ingest/0.1 (+https://jobs.amaansiddiqi.me)"

_GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
_LEVER_URL = "https://api.lever.co/v0/postings/{token}?mode=json"
_ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

_MAX_429_RETRIES = 2


class BoardFetchError(RuntimeError):
    """A board request failed after retries (network, non-200, bad payload)."""


class FetchedListing(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: str  # 'greenhouse' | 'lever' | 'ashby'
    source_name: str  # board token from companies.yaml
    external_id: str
    source_url: str
    title: str
    company: str  # curated display name from companies.yaml
    location: str | None
    description: str
    posted_at: datetime | None
    payload: dict[str, Any]


def html_to_text(markup: str) -> str:
    """Strip HTML to newline-separated text (mirrors the scraper's approach)."""
    if not markup:
        return ""
    return BeautifulSoup(markup, "lxml").get_text(separator="\n", strip=True)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    """GET with 429 backoff; raises BoardFetchError on anything unrecoverable."""
    for attempt in range(_MAX_429_RETRIES + 1):
        try:
            resp = await client.get(url)
        except httpx.HTTPError as e:
            raise BoardFetchError(f"request failed: {url}: {e}") from e
        if resp.status_code == 429 and attempt < _MAX_429_RETRIES:
            wait = 5 * (2**attempt)
            log.warning("429 from %s — backing off %ds", url, wait)
            await asyncio.sleep(wait)
            continue
        if resp.status_code != 200:
            raise BoardFetchError(f"HTTP {resp.status_code}: {url}")
        try:
            return resp.json()
        except ValueError as e:
            raise BoardFetchError(f"non-JSON response: {url}") from e
    raise BoardFetchError(f"rate-limited after {_MAX_429_RETRIES} retries: {url}")


async def fetch_greenhouse(
    client: httpx.AsyncClient, token: str, company: str
) -> list[FetchedListing]:
    data = await _get_json(client, _GREENHOUSE_URL.format(token=token))
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise BoardFetchError(f"greenhouse/{token}: payload has no jobs list")
    listings = []
    for job in jobs:
        # `content` is entity-escaped HTML (&lt;p&gt;...) — unescape, then strip.
        description = html_to_text(html.unescape(job.get("content") or ""))
        listings.append(
            FetchedListing(
                source_type="greenhouse",
                source_name=token,
                external_id=str(job["id"]),
                source_url=job["absolute_url"],
                title=job["title"],
                company=company,
                location=(job.get("location") or {}).get("name"),
                description=description,
                posted_at=_parse_iso(job.get("first_published")),
                payload=job,
            )
        )
    return listings


def _lever_description(job: dict[str, Any]) -> str:
    parts = [
        job.get("openingPlain") or "",
        job.get("descriptionPlain") or "",
    ]
    for lst in job.get("lists") or []:
        parts.append(lst.get("text") or "")
        parts.append(html_to_text(lst.get("content") or ""))
    parts.append(job.get("additionalPlain") or "")
    # Comp language is visa/salary evidence for extraction — keep it.
    parts.append(job.get("salaryDescriptionPlain") or "")
    return "\n".join(p for p in parts if p.strip())


async def fetch_lever(client: httpx.AsyncClient, token: str, company: str) -> list[FetchedListing]:
    data = await _get_json(client, _LEVER_URL.format(token=token))
    if not isinstance(data, list):
        raise BoardFetchError(f"lever/{token}: payload is not a postings list")
    listings = []
    for job in data:
        categories = job.get("categories") or {}
        all_locations = categories.get("allLocations") or []
        location = " | ".join(all_locations) or categories.get("location")
        created = job.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created / 1000, tz=UTC) if isinstance(created, int | float) else None
        )
        listings.append(
            FetchedListing(
                source_type="lever",
                source_name=token,
                external_id=str(job["id"]),
                source_url=job["hostedUrl"],
                title=job["text"],
                company=company,
                location=location,
                description=_lever_description(job),
                posted_at=posted_at,
                payload=job,
            )
        )
    return listings


async def fetch_ashby(client: httpx.AsyncClient, token: str, company: str) -> list[FetchedListing]:
    data = await _get_json(client, _ASHBY_URL.format(token=token))
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise BoardFetchError(f"ashby/{token}: payload has no jobs list")
    listings = []
    for job in jobs:
        if not job.get("isListed", True):
            continue
        secondary = [s.get("location") for s in job.get("secondaryLocations") or []]
        locations = [job.get("location"), *secondary]
        if job.get("isRemote"):
            locations.append("Remote")
        location = " | ".join(dict.fromkeys(loc for loc in locations if loc)) or None
        description = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
        listings.append(
            FetchedListing(
                source_type="ashby",
                source_name=token,
                external_id=str(job["id"]),
                source_url=job["jobUrl"],
                title=job["title"],
                company=company,
                location=location,
                description=description,
                posted_at=_parse_iso(job.get("publishedAt")),
                payload=job,
            )
        )
    return listings


FETCHERS: dict[str, Callable[[httpx.AsyncClient, str, str], Awaitable[list[FetchedListing]]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}
