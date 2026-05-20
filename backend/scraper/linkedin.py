"""
Scraper for LinkedIn's public guest job search endpoint.
No authentication required — uses the same API the unlogged homepage calls.

Endpoint:
  GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  ?keywords=<query>&location=Vancouver%2C+BC&start=<offset>

Returns an HTML fragment; each job is an <li> containing a .base-card div.
Pagination: increment `start` by 25 until an empty response is returned.
"""

import asyncio
import httpx
from bs4 import BeautifulSoup, Tag

SEARCH_URL = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    "?keywords={keywords}&location={location}&start={start}"
)

# Mimic a real browser to avoid 429s
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

_PAGE_SIZE = 25
_REQUEST_DELAY = 1.5  # seconds between pages — be a polite scraper


def _parse_cards(html: str) -> list[dict]:
    """Extract job metadata from a single page of results HTML."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []

    for li in soup.find_all("li"):
        if not isinstance(li, Tag):
            continue
        base_card = li.find("div", class_="base-card")
        if not base_card:
            continue

        title_el = li.find("h3", class_="base-search-card__title")
        company_el = li.find("h4", class_="base-search-card__subtitle")
        location_el = li.find("span", class_="job-search-card__location")
        link_el = li.find("a", class_="base-card__full-link")

        if not (title_el and company_el and location_el and link_el):
            continue

        # Strip tracking params from the URL
        url: str = link_el["href"].split("?")[0]  # type: ignore[index]

        jobs.append(
            {
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True),
                "location": location_el.get_text(strip=True),
                "source_url": url,
                # raw_description and skills are populated downstream
                # by the NLP pipeline after fetching the detail page
                "raw_description": "",
                "skills": [],
            }
        )

    return jobs


async def scrape(
    keywords: str,
    max_pages: int = 4,
    location: str = "Canada",
) -> list[dict]:
    """
    Fetch up to `max_pages` pages of job listings for `keywords`.

    Args:
        keywords: Search query, e.g. "software engineer" or "data analyst".
        max_pages: Hard cap on pages fetched (25 results each).
        location: LinkedIn location string, e.g. "Canada" or "Vancouver%2C+BC".

    Returns:
        List of job dicts with keys: title, company, location, source_url,
        raw_description (empty — fill via detail scrape), skills (empty).
    """
    all_jobs: list[dict] = []
    encoded_kw = keywords.replace(" ", "%20")
    encoded_loc = location.replace(" ", "%20").replace(",", "%2C")

    async with httpx.AsyncClient(
        headers=_HEADERS,
        follow_redirects=True,
        timeout=15,
    ) as client:
        for page in range(max_pages):
            start = page * _PAGE_SIZE
            url = SEARCH_URL.format(keywords=encoded_kw, location=encoded_loc, start=start)

            resp = await client.get(url)
            if resp.status_code == 429:
                # Back off and retry once
                await asyncio.sleep(5)
                resp = await client.get(url)
            resp.raise_for_status()

            page_jobs = _parse_cards(resp.text)
            if not page_jobs:
                break  # LinkedIn returned an empty page — we've hit the end

            all_jobs.extend(page_jobs)

            if page < max_pages - 1:
                await asyncio.sleep(_REQUEST_DELAY)

    return all_jobs
