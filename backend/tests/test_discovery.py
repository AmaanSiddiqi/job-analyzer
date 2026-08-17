"""Company discovery: slug guessing, suggestion recording, board probing."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import respx

from app.ingestion.boards import FetchedListing
from app.ingestion.discovery import _slug_guesses, probe_pending, record_suggestions
from app.models import SuggestedCompany

BOARD_FIXTURES = Path(__file__).parent / "fixtures" / "boards"


class TestSlugGuesses:
    def test_multi_word(self):
        assert _slug_guesses("Maple Analytics Inc.") == ["mapleanalytics", "maple-analytics"]

    def test_single_word(self):
        assert _slug_guesses("Shopify") == ["shopify"]

    def test_punctuation_stripped(self):
        assert "supercom" in _slug_guesses("Super.com")


def _listing(company: str) -> FetchedListing:
    return FetchedListing(
        source_type="adzuna",
        source_name="adzuna-ca",
        external_id="1",
        source_url=f"https://x.test/{company}",
        title="Engineer",
        company=company,
        location="Toronto, ON",
        description="desc",
        posted_at=None,
        payload={},
    )


def _db(rows=None, scalars=()):
    """AsyncSession stand-in: .scalars().all() serves ORM selects (probe),
    iter(.scalars()) serves the existing-names select, rowcount serves upserts."""
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = rows or []
    scalars_mock.__iter__ = lambda self: iter(scalars)
    result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=result)
    return session


async def test_record_suggestions_skips_known_and_blocklisted():
    db = _db(scalars=())
    listings = [
        _listing("Cohere"),  # already in companies.yaml → skipped
        _listing("Maple Analytics"),
        _listing("Maple Analytics"),  # counted once as a name
        _listing("TopTier Staffing"),  # blocklist → skipped
    ]
    new = await record_suggestions(db, listings)
    assert new == 1
    # one SELECT (existing names) + one upsert for the single new company
    assert db.execute.await_count == 2


async def test_record_suggestions_existing_name_not_counted_new():
    db = _db(scalars=("maple analytics",))
    new = await record_suggestions(db, [_listing("Maple Analytics")])
    assert new == 0  # still upserted (occurrence bump), but not new
    assert db.execute.await_count == 2


@respx.mock
async def test_probe_pending_finds_greenhouse_board():
    row = SuggestedCompany(
        company_name="Knak",
        occurrences=5,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        status="pending",
    )
    db = _db(rows=[row])

    # slug guess "knak" hits greenhouse; every other probe URL 404s
    respx.get("https://boards-api.greenhouse.io/v1/boards/knak/jobs?content=true").respond(
        json=json.loads((BOARD_FIXTURES / "greenhouse.json").read_text())
    )
    respx.route().respond(404)

    stats = await probe_pending(db)

    assert stats == {"probed": 1, "board_found": 1, "no_board": 0}
    assert row.status == "board_found"
    assert row.board == "greenhouse"
    assert row.board_token == "knak"
    assert row.board_jobs == 2
    db.commit.assert_awaited_once()


@respx.mock
async def test_probe_pending_no_board():
    row = SuggestedCompany(
        company_name="Totally Unfindable Co",
        occurrences=2,
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        status="pending",
    )
    db = _db(rows=[row])
    respx.route().respond(404)

    stats = await probe_pending(db)

    assert stats == {"probed": 1, "board_found": 0, "no_board": 1}
    assert row.status == "no_board"
    assert row.probed_at is not None
