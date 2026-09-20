"""Skill normalization against the reviewed taxonomy, plus the review queue.

The extraction pipeline (next PR) calls `normalize_and_record` for every
listing: canonical ids go on the row, anything unmatched accumulates in
unmapped_skills with occurrence counts so the weekly review sees what the
taxonomy is missing, ordered by how much it would buy.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from taxonomy.config import get_normalizer

from ..models import UnmappedSkill

log = logging.getLogger(__name__)


async def record_unmapped(db: AsyncSession, skills: list[str]) -> int:
    """Upsert unmapped skill strings, bumping occurrence counts.

    Returns the number of strings new to the queue. Does not commit — the
    caller owns the transaction boundary.
    """
    now = datetime.now(UTC)
    counted: dict[str, int] = {}
    for raw in skills:
        key = raw.strip().lower()
        if key:
            counted[key] = counted.get(key, 0) + 1
    # Checked after filtering, not before: a list of only blanks has nothing to
    # record and must not issue a query with an empty IN clause.
    if not counted:
        return 0

    existing = set(
        (
            await db.execute(
                select(UnmappedSkill.skill).where(UnmappedSkill.skill.in_(list(counted)))
            )
        ).scalars()
    )
    for skill, n in counted.items():
        await db.execute(
            pg_insert(UnmappedSkill)
            .values(skill=skill, occurrences=n, first_seen=now, last_seen=now)
            .on_conflict_do_update(
                index_elements=[UnmappedSkill.skill],
                set_={"occurrences": UnmappedSkill.occurrences + n, "last_seen": now},
            )
        )
    return sum(1 for s in counted if s not in existing)


async def normalize_and_record(
    db: AsyncSession, raw_skills: list[str]
) -> list[str]:
    """Canonical skill ids for a listing; unmatched strings go to the queue."""
    mapped, unmapped = get_normalizer().normalize(raw_skills)
    if unmapped:
        await record_unmapped(db, unmapped)
    return mapped


def extracted_skill_match(skill: str):
    """`job_postings` rows whose *extracted* components carry this skill.

    The two tables are joined on source_url: job_postings is the live feed,
    listing_components hangs off raw_listings. Uses the GIN index on
    listing_components.skills (array containment) and the source_url index
    added in migration 0008.
    """
    from sqlalchemy import exists, select

    from ..extraction.prompts import PROMPT_VERSION
    from ..models import JobPosting, ListingComponent, RawListing

    return exists(
        select(ListingComponent.id)
        .join(RawListing, RawListing.id == ListingComponent.raw_listing_id)
        .where(RawListing.source_url == JobPosting.source_url)
        .where(ListingComponent.prompt_version == PROMPT_VERSION)
        .where(ListingComponent.skills.contains([skill.lower()]))
    )


async def attach_extracted_skills(db: Any, jobs: "Sequence[Any]") -> None:
    """Replace each posting's baseline skills with its extracted ones, in place.

    Every skill chip in the UI is a filter link, and in extracted mode the
    filter matches extracted skills — so a chip from the baseline vocabulary
    would be a dead click ("go" on a posting that only says "go to market").
    One extra query per page, keyed by source_url.

    Postings with no extraction yet (aggregator rows, stale postings, anything
    ingested since the last batch) keep their baseline skills rather than
    rendering empty.
    """
    from sqlalchemy import select

    from ..extraction.prompts import PROMPT_VERSION
    from ..models import ListingComponent, RawListing

    urls = [job.source_url for job in jobs]
    if not urls:
        return
    rows = (
        await db.execute(
            select(RawListing.source_url, ListingComponent.skills)
            .join(ListingComponent, ListingComponent.raw_listing_id == RawListing.id)
            .where(RawListing.source_url.in_(urls))
            .where(ListingComponent.prompt_version == PROMPT_VERSION)
        )
    ).all()
    by_url = {row.source_url: row.skills for row in rows}
    for job in jobs:
        extracted = by_url.get(job.source_url)
        if extracted is not None:
            job.skills = extracted
