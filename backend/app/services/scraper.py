"""
Core scrape pipeline: listings → descriptions → NLP → DB upsert.
Called by both the HTTP endpoint and the scheduler.
"""

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import JobPosting
from ..services import nlp
from scraper import linkedin

log = logging.getLogger(__name__)

_DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
_HEADERS = linkedin._HEADERS
_CONCURRENCY = 3
_DESC_DELAY = 0.8


def _extract_job_id(url: str) -> str | None:
    match = re.search(r"[-/](\d{7,})(?:\?|$)", url)
    return match.group(1) if match else None


def _parse_description(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    candidates = [
        soup.find("div", {"class": "show-more-less-html__markup"}),
        soup.find("div", {"class": lambda c: c and "description__text" in c}),
        soup.find("section", {"class": lambda c: c and "description" in c}),
        soup.find("div", {"class": "description"}),
        soup.find("div", {"class": "job-description"}),
    ]
    for el in candidates:
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 50:
                return text
    body = soup.find("body") or soup
    text = body.get_text(separator="\n", strip=True)
    return text if len(text) > 50 else ""


async def _fetch_description(source_url: str, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> str:
    job_id = _extract_job_id(source_url)
    if not job_id:
        log.warning("could not extract job_id from %s", source_url)
        return ""
    async with sem:
        try:
            resp = await client.get(_DETAIL_URL.format(job_id=job_id))
            await asyncio.sleep(_DESC_DELAY)
            log.info("description fetch %s → %s (%d chars)", job_id, resp.status_code, len(resp.text))
            if resp.status_code == 200:
                return _parse_description(resp.text)
            log.warning("non-200 for job %s: %s", job_id, resp.status_code)
        except httpx.HTTPError as e:
            log.warning("HTTP error fetching description for %s: %s", job_id, e)
    return ""


async def run_scrape(keywords: str, max_pages: int, db: AsyncSession) -> dict:
    """Scrape `keywords`, enrich descriptions, extract skills, upsert to DB."""
    listings = await linkedin.scrape(keywords, max_pages)

    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=20) as client:
        descriptions = await asyncio.gather(
            *[_fetch_description(j["source_url"], client, sem) for j in listings]
        )

    inserted = skipped = 0
    for listing, raw_desc in zip(listings, descriptions):
        skills = nlp.extract_skills(raw_desc)
        stmt = (
            pg_insert(JobPosting)
            .values(**listing, raw_description=raw_desc, skills=skills)
            .on_conflict_do_nothing(index_elements=["source_url"])
        )
        result = await db.execute(stmt)
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1

    await db.commit()
    return {"fetched": len(listings), "inserted": inserted, "skipped": skipped}
