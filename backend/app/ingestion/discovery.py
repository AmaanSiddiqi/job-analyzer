"""Company discovery: grow companies.yaml from aggregator data.

Aggregator listings mention employers far beyond the curated board list.
This module (1) accumulates unseen company names into suggested_companies,
(2) probes whether pending ones expose a public Greenhouse/Lever/Ashby
board under slug guesses derived from their name, and (3) renders verified
hits as ready-to-paste YAML for Amaan's review. Nothing is ever auto-added
to companies.yaml — the probe finds candidates, a human promotes them.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sources.config import load_companies

from ..models import SuggestedCompany
from .boards import FETCHERS, USER_AGENT, BoardFetchError, FetchedListing
from .service import looks_canadian

log = logging.getLogger(__name__)

_PROBE_CONCURRENCY = 4
# Aggregator company fields are messy — skip obvious non-employers/agencies.
_NAME_BLOCKLIST = ("recruit", "staffing", "talent", "agency", "consulting group")


def _slug_guesses(name: str) -> list[str]:
    """Candidate board tokens from a company display name."""
    base = re.sub(r"\b(inc|ltd|llc|corp|co|inc\.|ltd\.)\.?$", "", name.strip().lower()).strip()
    base = re.sub(r"[^a-z0-9 ]", "", base)
    words = base.split()
    if not words:
        return []
    guesses = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(g for g in guesses if g))


async def record_suggestions(db: AsyncSession, listings: list[FetchedListing]) -> int:
    """Upsert unseen aggregator companies into the suggestion queue.

    Returns how many company names are new to the queue this run.
    """
    known = {c.name.lower() for c in load_companies().companies}
    now = datetime.now(UTC)
    counted: dict[str, int] = {}
    for listing in listings:
        name = listing.company.strip()
        if not name or name.lower() in known:
            continue
        if any(b in name.lower() for b in _NAME_BLOCKLIST):
            continue
        counted[name] = counted.get(name, 0) + 1
    if not counted:
        return 0

    lowered = [n.lower() for n in counted]
    existing = set(
        (
            await db.execute(
                select(func.lower(SuggestedCompany.company_name)).where(
                    func.lower(SuggestedCompany.company_name).in_(lowered)
                )
            )
        ).scalars()
    )
    new_names = sum(1 for n in counted if n.lower() not in existing)

    for name, n in counted.items():
        # Uniqueness is the lower(company_name) expression index — the
        # conflict target must name that expression, not a constraint.
        stmt = (
            pg_insert(SuggestedCompany)
            .values(company_name=name, occurrences=n, first_seen=now, last_seen=now)
            .on_conflict_do_update(
                index_elements=[text("lower(company_name)")],
                set_={
                    "occurrences": SuggestedCompany.occurrences + n,
                    "last_seen": now,
                },
            )
        )
        await db.execute(stmt)
    return new_names


async def probe_pending(db: AsyncSession, limit: int = 100) -> dict[str, int]:
    """Probe pending suggestions for public boards; record what we find.

    Reuses the board fetchers, so a hit comes with real listings — both the
    total and the Canadian-role count are recorded (the latter is the review
    queue's sort key), and the payload is thrown away. A board with zero
    Canadian roles is auto-rejected as 'no_ca_roles' and never reaches review.
    """
    rows = (
        (
            await db.execute(
                select(SuggestedCompany)
                .where(SuggestedCompany.status == "pending")
                .order_by(SuggestedCompany.occurrences.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    sem = asyncio.Semaphore(_PROBE_CONCURRENCY)
    found = no_board = no_ca_roles = 0

    async def probe(row: SuggestedCompany) -> None:
        nonlocal found, no_board, no_ca_roles
        async with sem, httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=15
        ) as client:
            for token in _slug_guesses(row.company_name):
                for board, fetcher in FETCHERS.items():
                    try:
                        listings = await fetcher(client, token, row.company_name)
                    except BoardFetchError:
                        continue
                    ca_jobs = sum(1 for listing in listings if looks_canadian(listing.location))
                    row.board = board
                    row.board_token = token
                    row.board_jobs = len(listings)
                    row.ca_jobs = ca_jobs
                    row.probed_at = datetime.now(UTC)
                    if ca_jobs:
                        row.status = "board_found"
                        found += 1
                    else:
                        # Board exists but hires nowhere we care about — or the
                        # slug matched a different company entirely. Either way
                        # it isn't worth review time.
                        row.status = "no_ca_roles"
                        no_ca_roles += 1
                    return
        row.status = "no_board"
        row.probed_at = datetime.now(UTC)
        no_board += 1

    await asyncio.gather(*[probe(r) for r in rows])
    await db.commit()
    log.info(
        "discovery probe: %d with CA roles, %d board-but-no-CA, %d no board (of %d pending)",
        found, no_ca_roles, no_board, len(rows),
    )
    return {
        "probed": len(rows),
        "board_found": found,
        "no_ca_roles": no_ca_roles,
        "no_board": no_board,
    }


async def render_yaml_suggestions(db: AsyncSession) -> str:
    """Ready-to-paste companies.yaml entries, most Canada-relevant first.

    Sorted by Canadian-role count, not raw occurrences: the latter ranks by how
    aggressively a company advertises, which favours large US employers.
    """
    rows = (
        (
            await db.execute(
                select(SuggestedCompany)
                .where(SuggestedCompany.status == "board_found")
                .order_by(
                    SuggestedCompany.ca_jobs.desc().nullslast(),
                    SuggestedCompany.occurrences.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    blocks = []
    for r in rows:
        ca_share = (
            f"{r.ca_jobs}/{r.board_jobs} Canadian"
            if r.board_jobs
            else f"{r.ca_jobs} Canadian"
        )
        blocks.append(
            f'  - name: "{r.company_name}"\n'
            f'    hq: "TODO — verify"\n'
            f"    board: {r.board}\n"
            f"    token: {r.board_token}\n"
            f"    # discovered via aggregators: seen {r.occurrences}x; board has "
            f"{ca_share} roles at probe time — VERIFY this is the right company\n"
        )
    return "".join(blocks)
