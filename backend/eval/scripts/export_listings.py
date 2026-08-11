"""
Pull a random sample of real listings from the DB into eval/gold/listings_pool.jsonl
— the raw corpus that draft_label.py annotates and review_cli.py reviews.

Usage:
    uv run python -m eval.scripts.export_listings --limit 150 --out eval/gold/listings_pool.jsonl

Requires DATABASE_URL (same env var the app uses — point it at prod, a prod
copy, or local dev data). Read-only: SELECT only, no writes.
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import JobPosting
from eval.jsonl import write_jsonl
from eval.schemas import PoolListing


async def export_listings(limit: int, out_path: Path) -> int:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(JobPosting)
            .where(func.length(JobPosting.raw_description) > 200)  # skip empty/failed scrapes
            .order_by(func.random())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    listings = [
        PoolListing(
            listing_id=str(row.id),
            source="prod_db",
            title=row.title,
            company=row.company,
            raw_description=row.raw_description,
        )
        for row in rows
    ]
    write_jsonl(out_path, listings)
    return len(listings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--out", type=Path, default=Path("eval/gold/listings_pool.jsonl"))
    args = parser.parse_args()

    n = asyncio.run(export_listings(args.limit, args.out))
    print(f"Wrote {n} listings to {args.out}")


if __name__ == "__main__":
    main()
