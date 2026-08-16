"""Re-verify every board token in companies.yaml against the live public APIs.

Manual maintenance tool (network access — never run from unit tests or CI):

    cd backend && uv run python -m sources.verify

Reports per-company job counts and flags dead boards so stale tokens get
caught before ingestion silently drops a company.
"""

import asyncio
import sys

import httpx

from sources.config import Company, load_companies

_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "lever": "https://api.lever.co/v0/postings/{}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
}
_UA = "job-analyzer-source-verifier/0.1 (+https://jobs.amaansiddiqi.me)"
_sem = asyncio.Semaphore(8)


async def _job_count(client: httpx.AsyncClient, company: Company) -> int | None:
    """Job count if the board responds with a valid payload, else None (dead)."""
    url = _ENDPOINTS[company.board].format(company.token)
    async with _sem:
        try:
            r = await client.get(url, timeout=15)
        except httpx.HTTPError:
            return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if company.board == "lever":
        return len(data) if isinstance(data, list) else None
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return len(jobs) if isinstance(jobs, list) else None


async def main() -> int:
    config = load_companies()
    async with httpx.AsyncClient(headers={"User-Agent": _UA}) as client:
        counts = await asyncio.gather(*[_job_count(client, c) for c in config.companies])

    dead: list[Company] = []
    total_jobs = 0
    for company, count in zip(config.companies, counts, strict=True):
        if count is None:
            dead.append(company)
            print(f"DEAD  {company.name:24} {company.board}/{company.token}")
        else:
            total_jobs += count
            print(f"ok    {company.name:24} {company.board}/{company.token}  jobs={count}")

    print(
        f"\n{len(config.companies) - len(dead)}/{len(config.companies)} boards alive, "
        f"{total_jobs} open jobs total"
    )
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
