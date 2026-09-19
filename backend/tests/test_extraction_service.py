"""Pipeline behavior: cost-cap abort, dead-lettering, skill normalization,
CAD estimates, and the resumability query."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.extraction.client import ExtractionFailed, ExtractionResult
from app.extraction.prompts import PROMPT_VERSION
from app.extraction.schema import (
    Compensation,
    CompPeriod,
    JobComponents,
    RemotePolicy,
    Seniority,
    Stated,
    VisaSignals,
)
from app.extraction.service import cad_annual_estimate, run_extraction
from app.models import DeadLetter, ListingComponent
from app.settings import Settings


def _components(**over) -> JobComponents:
    base = {
        "title_normalized": "Senior Software Engineer",
        "seniority": Seniority.SENIOR,
        "company_canonical": "Cohere",
        "skills": ["python", "aws"],
        "extraction_confidence": 0.9,
    }
    base.update(over)
    return JobComponents(**base)


def _raw(listing_id=1):
    return SimpleNamespace(
        id=listing_id,
        title="Senior Software Engineer",
        company="Cohere Inc.",
        location="Toronto, ON",
        description="We use Python and AWS.",
        source_url=f"https://example.test/{listing_id}",
        posted_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _db(spent=Decimal(0)):
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=spent)
    result = MagicMock()
    scalars = MagicMock()
    scalars.__iter__ = lambda self: iter(())
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    result.rowcount = 1
    db.execute = AsyncMock(return_value=result)
    return db


def _settings(**over: Any) -> Settings:
    values: dict[str, Any] = {"extraction_cost_cap_usd": 15.0, "extraction_batch_size": 50}
    values.update(over)
    return Settings(**values)


def _result(components=None, attempts=1):
    return ExtractionResult(
        components=components or _components(),
        input_tokens=5000,
        output_tokens=800,
        cache_read_tokens=2299,
        cache_write_tokens=0,
        model="claude-sonnet-5",
        prompt_version=PROMPT_VERSION,
        attempts=attempts,
    )


class TestCadEstimate:
    def test_annual_cad_midpoint(self):
        c = _components(
            compensation=Compensation(
                min_amount=120_000, max_amount=140_000, currency="CAD", period=CompPeriod.YEAR
            )
        )
        assert cad_annual_estimate(c) == Decimal("130000.00")

    def test_hourly_usd_is_annualized_and_converted(self):
        c = _components(
            compensation=Compensation(
                min_amount=50, max_amount=50, currency="USD", period=CompPeriod.HOUR
            )
        )
        # 50 * 2080 * 1.37
        assert cad_annual_estimate(c) == Decimal("142480.00")

    def test_no_compensation_gives_no_estimate(self):
        assert cad_annual_estimate(_components()) is None

    def test_unknown_currency_gives_no_estimate(self):
        """Better no estimate than one from an invented exchange rate."""
        c = _components(
            compensation=Compensation(
                min_amount=1_000_000, currency="JPY", period=CompPeriod.YEAR
            )
        )
        assert cad_annual_estimate(c) is None

    def test_single_bound_still_estimates(self):
        c = _components(
            compensation=Compensation(min_amount=100_000, currency="CAD", period=CompPeriod.YEAR)
        )
        assert cad_annual_estimate(c) == Decimal("100000.00")


class TestRunExtraction:
    async def test_nothing_pending_is_a_noop(self):
        db = _db()
        with patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[])):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.considered == 0 and stats.extracted == 0
        db.add.assert_not_called()

    async def test_extracts_and_writes_a_component_row(self):
        db = _db()
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch("app.extraction.service.extract_one", new=AsyncMock(return_value=_result())),
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.extracted == 1 and stats.dead_lettered == 0
        rows = [c.args[0] for c in db.add.call_args_list]
        component = next(r for r in rows if isinstance(r, ListingComponent))
        assert component.company_canonical == "Cohere"
        assert component.skills == ["aws", "python"]  # normalized + sorted
        assert stats.cost_usd > 0

    async def test_cost_cap_aborts_before_spending_more(self):
        """The cap must stop the run, not merely report the overspend."""
        db = _db(spent=Decimal("15.00"))
        extract = AsyncMock(return_value=_result())
        with (
            patch(
                "app.extraction.service.pending_listings",
                new=AsyncMock(return_value=[_raw(1), _raw(2)]),
            ),
            patch("app.extraction.service.extract_one", new=extract),
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.extracted == 0
        assert stats.aborted_reason is not None and "cap" in stats.aborted_reason
        extract.assert_not_awaited()  # no model call at all

    async def test_failure_dead_letters_and_the_run_continues(self):
        db = _db()
        extract = AsyncMock(
            side_effect=[ExtractionFailed("boom", raw_response="garbage"), _result()]
        )
        with (
            patch(
                "app.extraction.service.pending_listings",
                new=AsyncMock(return_value=[_raw(1), _raw(2)]),
            ),
            patch("app.extraction.service.extract_one", new=extract),
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.dead_lettered == 1 and stats.extracted == 1
        dead = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], DeadLetter)
        )
        assert dead.kind == "extraction"
        assert dead.payload["raw_response"] == "garbage"
        assert dead.attempts == 2

    async def test_unmapped_skills_are_queued(self):
        db = _db()
        components = _components(skills=["python"], skills_unmapped=["COBOL", "Fortran"])
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(components)),
            ),
            patch(
                "app.extraction.service.record_unmapped", new=AsyncMock(return_value=2)
            ) as record,
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.unmapped_skills_new == 2
        assert sorted(record.await_args.args[1]) == ["cobol", "fortran"]

    async def test_model_skill_outside_the_taxonomy_is_not_stored_as_canonical(self):
        """The prompt asks for canonical ids, but a near-miss must not slip into
        the skills column — normalization is the enforcement point."""
        db = _db()
        components = _components(skills=["python", "Rustlang"])
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(components)),
            ),
            patch("app.extraction.service.record_unmapped", new=AsyncMock(return_value=1)),
        ):
            await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        component = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ListingComponent)
        )
        assert component.skills == ["python"]

    async def test_visa_signals_are_counted_and_stored(self):
        db = _db()
        quote = "We sponsor work permits for exceptional candidates."
        components = _components(
            visa=VisaSignals(sponsorship_available=Stated.YES, evidence=[quote]),
            remote_policy=RemotePolicy.HYBRID,
        )
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(components)),
            ),
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.visa_signals_found == 1
        component = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ListingComponent)
        )
        assert component.visa_sponsorship_available is True
        assert component.visa_evidence == [quote]
        assert component.remote_policy == "hybrid"

    async def test_retry_is_counted(self):
        db = _db()
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(attempts=2)),
            ),
        ):
            stats = await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        assert stats.retried == 1


def test_prompt_version_is_recorded_on_rows():
    """Rows must carry the prompt version, or an F1 regression can't be traced
    to a prompt change (CLAUDE.md). Asserted against the constant, not a
    literal, so bumping the prompt doesn't require editing the test — but the
    column must never be empty."""
    from app.extraction.prompts import PROMPT_VERSION
    from app.extraction.service import _to_row

    row = _to_row(_raw(), _components(), "claude-sonnet-5", ["python"])
    assert row.prompt_version == PROMPT_VERSION
    assert PROMPT_VERSION


async def test_stored_unmapped_reflects_normalization_not_the_model_guess():
    """The model often puts a resolvable alias in skills_unmapped ("agentic ai"
    -> "ai agents"). Storing its raw guess would understate coverage."""
    db = _db()
    components = _components(skills=["python"], skills_unmapped=["agentic ai", "Rustlang"])
    with (
        patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
        patch(
            "app.extraction.service.extract_one",
            new=AsyncMock(return_value=_result(components)),
        ),
        patch("app.extraction.service.record_unmapped", new=AsyncMock(return_value=1)),
    ):
        await run_extraction(db, settings=_settings(), client=SimpleNamespace())
    component = next(
        c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ListingComponent)
    )
    assert "ai agents" in component.skills          # alias resolved into skills
    assert component.skills_unmapped == ["rustlang"]  # only the true miss remains


def _compiled(stmt) -> str:
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect())).lower()


async def _pending_sql(**settings_over) -> str:
    """The SQL pending_listings actually executes, captured from the session.

    These used to grep the function's *source text* — which broke on a pure
    refactor, and would have kept passing if the behaviour broke as long as
    the words survived. Compiling the real statement tests the query itself.
    """
    from app.extraction.service import pending_listings

    db = _db()
    await pending_listings(db, 50, _settings(**settings_over))
    return _compiled(db.execute.call_args.args[0])


class TestPendingListings:
    """What gets extracted is decided entirely by this query — and every row it
    returns is money spent, so each rule is asserted on the compiled SQL."""

    async def test_one_row_per_posting_the_newest_version(self):
        """raw_listings is append-only; without DISTINCT ON the first backfill
        would have extracted 2,521 rows for 1,782 postings (29% waste)."""
        sql = await _pending_sql()
        assert "distinct on (raw_listings.source_url)" in sql
        assert "raw_listings.fetched_at desc" in sql

    async def test_skips_aggregators(self):
        sql = await _pending_sql()
        assert "raw_listings.source_type not in" in sql

    async def test_aggregators_included_when_rule_disabled(self):
        sql = await _pending_sql(extraction_skip_aggregators=False)
        assert "not in" not in sql

    async def test_skips_stale_postings_but_keeps_undated_ones(self):
        """A source that returns no date must not have its whole feed dropped."""
        sql = await _pending_sql()
        assert "raw_listings.posted_at is null or raw_listings.posted_at >=" in sql

    async def test_skips_postings_already_extracted_at_this_prompt_version(self):
        sql = await _pending_sql()
        assert "listing_components.prompt_version" in sql

    async def test_skips_dead_lettered_postings(self):
        """Otherwise a posting that always fails is retried — and billed — on
        every run forever, and the requeue endpoint does nothing."""
        sql = await _pending_sql()
        assert "dead_letters.resolved_at is null" in sql
        assert "dead_letters.kind" in sql

    async def test_skips_postings_in_an_uncollected_batch(self):
        """Or the next submission pays for them a second time."""
        sql = await _pending_sql()
        assert "extraction_batches.status" in sql
        assert "any (extraction_batches.raw_listing_ids)" in sql

    async def test_ordered_newest_first(self):
        """When a run is capped, the budget went to listings users would see."""
        sql = await _pending_sql()
        assert "order by raw_listings.posted_at desc nulls last" in sql


class TestEligibilityPersistence:
    async def test_eligibility_fields_are_written(self):
        db = _db()
        from app.extraction.schema import EligibilitySignals

        components = _components(
            eligibility=EligibilitySignals(
                min_years_experience=5,
                degree_required=Stated.YES,
                french_required=Stated.NO,
                is_new_grad_friendly=Stated.NOT_STATED,
                evidence=["5+ years of professional software experience required"],
            )
        )
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(components)),
            ),
        ):
            await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        row = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ListingComponent)
        )
        assert row.min_years_experience == 5
        assert row.degree_required is True
        assert row.french_required is False
        # NOT_STATED must reach the column as a real NULL, not False.
        assert row.is_new_grad_friendly is None
        assert row.eligibility_evidence == [
            "5+ years of professional software experience required"
        ]

    async def test_zero_years_persists_as_zero_not_null(self):
        """"No experience required" is a real signal; a falsy check would lose it."""
        db = _db()
        from app.extraction.schema import EligibilitySignals

        components = _components(
            eligibility=EligibilitySignals(
                min_years_experience=0, evidence=["No prior experience required"]
            )
        )
        with (
            patch("app.extraction.service.pending_listings", new=AsyncMock(return_value=[_raw()])),
            patch(
                "app.extraction.service.extract_one",
                new=AsyncMock(return_value=_result(components)),
            ),
        ):
            await run_extraction(db, settings=_settings(), client=SimpleNamespace())
        row = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ListingComponent)
        )
        assert row.min_years_experience == 0
