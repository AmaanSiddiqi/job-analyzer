"""normalize_and_record splits skills correctly and queues the misses.

DB is mocked — these assert on behavior (what gets returned, what gets
queued), not on SQL.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.skills import normalize_and_record, record_unmapped


def _db(existing: tuple[str, ...] = ()):
    session = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.__iter__ = lambda self: iter(existing)
    result.scalars.return_value = scalars
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    return session


async def test_returns_canonical_ids_only():
    db = _db()
    mapped = await normalize_and_record(db, ["Python", "golang", "Postgres"])
    assert mapped == ["go", "postgresql", "python"]


async def test_unmapped_skills_are_queued_not_returned():
    db = _db()
    with patch("app.services.skills.record_unmapped", new=AsyncMock(return_value=1)) as rec:
        mapped = await normalize_and_record(db, ["Python", "Fortran"])
    assert mapped == ["python"]
    rec.assert_awaited_once()
    assert rec.await_args.args[1] == ["fortran"]


async def test_no_queue_write_when_everything_maps():
    db = _db()
    with patch("app.services.skills.record_unmapped", new=AsyncMock()) as rec:
        await normalize_and_record(db, ["Python", "AWS"])
    rec.assert_not_awaited()


async def test_record_unmapped_counts_new_names():
    db = _db(existing=("fortran",))
    # fortran already queued, cobol is new → 1 new name, both upserted
    new = await record_unmapped(db, ["Fortran", "COBOL", "cobol"])
    assert new == 1
    # one SELECT for existing names + one upsert per distinct skill
    assert db.execute.await_count == 3


async def test_record_unmapped_ignores_blanks():
    db = _db()
    assert await record_unmapped(db, ["", "   "]) == 0
    db.execute.assert_not_awaited()


async def test_record_unmapped_empty_list_is_noop():
    db = _db()
    assert await record_unmapped(db, []) == 0
    db.execute.assert_not_awaited()
