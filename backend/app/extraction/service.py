"""Extraction pipeline: raw_listings → listing_components.

Idempotent and resumable — it only selects listings with no row at the current
prompt version, so an aborted run (cost cap, crash, deploy) resumes where it
stopped with no bookkeeping. Failures dead-letter with the raw response and
never stop the batch; the cost cap is the only thing that halts a run.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anthropic
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DeadLetter, ListingComponent, RawListing
from ..services.skills import record_unmapped
from ..settings import Settings, get_settings
from .client import ExtractionFailed, extract_one
from .cost import CostCapExceeded, check_cap, record_usage
from .prompts import PROMPT_VERSION
from .schema import CompPeriod, JobComponents

log = logging.getLogger(__name__)

# Aggregator sources deliver truncated snippets — see pending_listings().
AGGREGATOR_SOURCES = ("adzuna", "jooble")

# Hardcoded FX for comp_cad_annual_est (CLAUDE.md: hardcoded rates table).
# Rough and deliberately so — the estimate exists for cross-currency sorting,
# never to be shown as an authoritative salary. Original figures are preserved.
_TO_CAD: dict[str, Decimal] = {
    "CAD": Decimal("1.00"),
    "USD": Decimal("1.37"),
    "EUR": Decimal("1.48"),
    "GBP": Decimal("1.73"),
}
# Annualization multipliers by pay period.
_ANNUALIZE: dict[CompPeriod, Decimal] = {
    CompPeriod.YEAR: Decimal(1),
    CompPeriod.MONTH: Decimal(12),
    CompPeriod.HOUR: Decimal(2080),  # 40h × 52w
}


def cad_annual_estimate(components: JobComponents) -> Decimal | None:
    """Midpoint of the stated range, annualized and converted to CAD."""
    comp = components.compensation
    amounts = [a for a in (comp.min_amount, comp.max_amount) if a is not None]
    if not amounts or not comp.currency or comp.period is None:
        return None
    rate = _TO_CAD.get(comp.currency.upper())
    if rate is None:
        return None
    midpoint = Decimal(str(sum(amounts))) / Decimal(len(amounts))
    return (midpoint * _ANNUALIZE[comp.period] * rate).quantize(Decimal("0.01"))


@dataclass
class ExtractionRunStats:
    run_id: str
    considered: int = 0
    extracted: int = 0
    dead_lettered: int = 0
    retried: int = 0
    cost_usd: Decimal = Decimal(0)
    aborted_reason: str | None = None
    unmapped_skills_new: int = 0
    visa_signals_found: int = 0
    errors: list[str] = field(default_factory=list)


def _resolve_posted_at(components: JobComponents, raw: RawListing) -> datetime | None:
    """Prefer a date stated in the posting text over the source's metadata.

    The model returns a `date`; raw_listings stores a `datetime` from the board
    API. Where the text states a date, it's the more authoritative of the two
    (an API's timestamp can reflect a re-publish), so it wins.
    """
    if components.posted_at is not None:
        return datetime.combine(components.posted_at, datetime.min.time(), tzinfo=UTC)
    return raw.posted_at


def _to_row(
    raw: RawListing,
    components: JobComponents,
    model: str,
    mapped_skills: list[str],
    unmapped_skills: list[str] | None = None,
) -> ListingComponent:
    comp = components.compensation
    visa = components.visa
    elig = components.eligibility
    return ListingComponent(
        raw_listing_id=raw.id,
        prompt_version=PROMPT_VERSION,
        model=model,
        title_raw=components.title_raw,
        title_normalized=components.title_normalized,
        seniority=components.seniority.value,
        company_raw=components.company_raw,
        company_canonical=components.company_canonical,
        skills=mapped_skills,
        # What is *still* unmapped after normalization, not the model's raw
        # guess: it often puts a resolvable alias here (e.g. "agentic ai" ->
        # "ai agents"), and storing that would misreport taxonomy coverage.
        skills_unmapped=(
            unmapped_skills if unmapped_skills is not None else components.skills_unmapped
        ),
        required_quals=components.required_quals,
        preferred_quals=components.preferred_quals,
        comp_min=comp.min_amount,
        comp_max=comp.max_amount,
        comp_currency=comp.currency.upper() if comp.currency else None,
        comp_period=comp.period.value if comp.period else None,
        comp_is_estimated=comp.is_estimated,
        comp_cad_annual_est=cad_annual_estimate(components),
        location_raw=components.location_raw or raw.location,
        city=components.city,
        region=components.region,
        country=components.country.upper() if components.country else None,
        remote_policy=components.remote_policy.value,
        visa_sponsorship_available=visa.sponsorship_available,
        visa_requires_existing_authorization=visa.requires_existing_authorization,
        visa_citizenship_or_pr_required=visa.citizenship_or_pr_required,
        min_years_experience=elig.min_years_experience,
        degree_required=elig.degree_required,
        french_required=elig.french_required,
        is_new_grad_friendly=elig.is_new_grad_friendly,
        is_internship_or_coop=elig.is_internship_or_coop,
        eligibility_evidence=[e for e in elig.evidence if e.strip()],
        visa_evidence=[e for e in visa.evidence if e.strip()],
        posted_at=_resolve_posted_at(components, raw),
        language=components.language,
        extraction_confidence=components.extraction_confidence,
    )


async def pending_listings(
    db: AsyncSession, limit: int, settings: Settings | None = None
) -> list[RawListing]:
    """Listings worth extracting, freshest first.

    This query *is* the resumability mechanism — nothing tracks progress
    separately, so a run that dies mid-way simply has fewer pending rows next
    time. It also carries the two standing cost rules from CLAUDE.md, because
    the cheapest token is the one never sent:

      * skip postings older than the staleness window — 26% of the corpus is
        >90 days old and mostly filled, frozen or evergreen, so extracting it
        is money spent on listings nobody should apply to;
      * skip aggregator rows — Adzuna/Jooble give truncated snippets, which
        make poor extraction input; they earn their keep on breadth and company
        discovery instead.

    Ordered newest-first (not oldest) so that when a run is capped, the budget
    went to the listings users would actually see.
    """
    settings = settings or get_settings()
    already_done = (
        select(ListingComponent.id)
        .where(ListingComponent.raw_listing_id == RawListing.id)
        .where(ListingComponent.prompt_version == PROMPT_VERSION)
    )
    stmt = select(RawListing).where(~exists(already_done))

    if settings.extraction_skip_aggregators:
        stmt = stmt.where(RawListing.source_type.notin_(AGGREGATOR_SOURCES))
    if settings.extraction_max_posting_age_days:
        cutoff = datetime.now(UTC) - timedelta(days=settings.extraction_max_posting_age_days)
        # posted_at NULL means the source gave no date — keep those rather than
        # silently dropping a whole source's listings.
        stmt = stmt.where(
            (RawListing.posted_at.is_(None)) | (RawListing.posted_at >= cutoff)
        )

    stmt = stmt.order_by(RawListing.posted_at.desc().nullslast()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def run_extraction(
    db: AsyncSession,
    *,
    limit: int | None = None,
    settings: Settings | None = None,
    client: anthropic.AsyncAnthropic | None = None,
) -> ExtractionRunStats:
    """Extract pending listings until the limit or the cost cap is reached."""
    settings = settings or get_settings()
    stats = ExtractionRunStats(run_id=f"extract-{uuid.uuid4().hex[:12]}")
    batch_limit = limit or settings.extraction_batch_size

    listings = await pending_listings(db, batch_limit, settings)
    stats.considered = len(listings)
    if not listings:
        log.info("extraction: nothing pending at prompt %s", PROMPT_VERSION)
        return stats

    owns_client = client is None
    client = client or anthropic.AsyncAnthropic()
    try:
        for raw in listings:
            try:
                await check_cap(db, stats.run_id, settings.extraction_cost_cap_usd)
            except CostCapExceeded as e:
                stats.aborted_reason = str(e)
                log.warning("extraction aborted: %s", e)
                break

            try:
                result = await extract_one(
                    client,
                    settings,
                    title=raw.title,
                    company=raw.company,
                    location=raw.location,
                    description=raw.description,
                )
            except ExtractionFailed as e:
                db.add(
                    DeadLetter(
                        kind="extraction",
                        raw_listing_id=raw.id,
                        payload={
                            "prompt_version": PROMPT_VERSION,
                            "model": settings.extraction_model,
                            "source_url": raw.source_url,
                            "raw_response": e.raw_response,
                        },
                        error=str(e)[:4000],
                        attempts=2,
                        last_attempt_at=datetime.now(UTC),
                    )
                )
                stats.dead_lettered += 1
                stats.errors.append(f"{raw.source_url}: {e}")
                continue

            stats.cost_usd += await record_usage(
                db,
                run_id=stats.run_id,
                purpose="extraction",
                model=result.model,
                prompt_version=result.prompt_version,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            if result.attempts > 1:
                stats.retried += 1

            # The model is told to use canonical ids, but it can still emit a
            # near-miss — normalizing here is what guarantees the invariant,
            # and it routes both its unmapped list and any near-miss into the
            # same review queue.
            mapped, unmapped = _normalize(result.components)
            if unmapped:
                stats.unmapped_skills_new += await record_unmapped(db, unmapped)
            if result.components.visa.any_flag_set:
                stats.visa_signals_found += 1

            db.add(_to_row(raw, result.components, result.model, mapped, unmapped))
            stats.extracted += 1
            # Commit per listing: a run that dies has kept everything it paid
            # for, which matters most during a long backfill.
            await db.commit()
    finally:
        if owns_client:
            await client.close()

    await db.commit()
    log.info(
        "extraction run %s: considered=%d extracted=%d dead=%d retried=%d cost=$%.4f%s",
        stats.run_id, stats.considered, stats.extracted, stats.dead_lettered,
        stats.retried, stats.cost_usd, f" ABORTED: {stats.aborted_reason}" if stats.aborted_reason else "",
    )
    return stats


def _normalize(components: JobComponents) -> tuple[list[str], list[str]]:
    """Canonical ids for the model's skills, plus everything unmatched."""
    from taxonomy.config import get_normalizer

    mapped, unmapped = get_normalizer().normalize(
        [*components.skills, *components.skills_unmapped]
    )
    return mapped, unmapped
