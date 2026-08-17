"""Skill normalization against the reviewed taxonomy, plus the review queue.

The extraction pipeline (next PR) calls `normalize_and_record` for every
listing: canonical ids go on the row, anything unmatched accumulates in
unmapped_skills with occurrence counts so the weekly review sees what the
taxonomy is missing, ordered by how much it would buy.
"""

import logging
from datetime import UTC, datetime

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
