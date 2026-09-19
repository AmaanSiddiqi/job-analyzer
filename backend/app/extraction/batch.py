"""Batch extraction: the Message Batches API path, at half the live price.

CLAUDE.md rule (d) — batch API for any backfill. The same path also carries
steady-state extraction, because at ~40 new postings a day nobody is waiting on
a listing's structure in real time, and one mechanism is simpler than two.

The lifecycle is submit -> (minutes to hours) -> collect, with every submission
recorded in `extraction_batches` so it survives the process that made it:

  * submit: pending postings are sized against the cost cap *before* anything
    is sent, then submitted as one batch. In-flight postings are excluded from
    the next submission by pending_listings, so nothing is paid for twice.
  * collect: each succeeded result is validated with the same rules as the live
    path. Results that fail (validation, refusal, truncation, expiry) get one
    live retry via extract_one, and dead-letter after that — three attempts,
    as CLAUDE.md specifies.

**Why every submission warms the cache first.** Measured 2026-09-19: a batch's
requests run concurrently, so none finds the prompt cache warm — all 6 requests
of a real batch paid a 4,322-token cache *write* and got zero reads, which made
batch ($0.0149/listing) no cheaper than live ($0.0146). One live request with
the identical prefix and a 1-hour TTL, sent just before submitting, turned that
into 5/5 cache *reads* and ~$0.0069/listing: half price, as batch should be.
The warm-up costs one 2x write when the cache is cold, and only a cheap read
when it's still alive from the previous cycle.

The circuit breaker matters more than it looks. If a *systematic* fault hits a
batch (the schema rejected, as happened in P1), every request fails; falling
back to live for each would re-run the whole backlog at twice the price. Past
`extraction_batch_max_error_rate`, the batch is marked failed, nothing falls
back, and scheduled submission stops until someone submits by hand.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import anthropic
from anthropic.types import TextBlock
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ExtractionBatch, ListingComponent, RawListing
from ..settings import Settings, get_settings
from .client import ExtractionFailed, build_request, extract_one, output_format_param
from .cost import CostCapExceeded, cache_write_split, check_cap, record_usage
from .prompts import PROMPT_VERSION
from .schema import JobComponents
from .service import dead_letter, pending_listings, persist_components

log = logging.getLogger(__name__)

# Arbitrary but fixed: serializes submitters (the scheduled job and the admin
# endpoint) so two of them can't select the same pending postings at once.
_SUBMIT_LOCK_KEY = 7_311_901


def build_batch_params(settings: Settings, raw: RawListing) -> MessageCreateParamsNonStreaming:
    """One batch request: the live request plus the structured-output format.

    Built from build_request so a batch can't drift from what the eval measured;
    only the format is added, because the live path gets it from parse().
    """
    kwargs = build_request(settings, raw.title, raw.company, raw.location, raw.description)
    kwargs["output_config"] = {**kwargs.get("output_config", {}), "format": output_format_param()}
    # 1-hour TTL: a batch can take longer than 5 minutes, and the warm-up
    # written before submission has to still be alive when requests run.
    kwargs["system"] = [{**kwargs["system"][0], "cache_control": _CACHE_1H}]
    return MessageCreateParamsNonStreaming(**kwargs)  # type: ignore[typeddict-item]


_CACHE_1H = {"type": "ephemeral", "ttl": "1h"}


async def _warm_cache(
    db: AsyncSession, client: anthropic.AsyncAnthropic, settings: Settings, sample: RawListing
) -> None:
    """Write the shared prefix to the cache before the batch runs.

    The request is a batch request's params with the posting swapped for a
    one-word message: system prompt, skill list, output schema and model are
    identical, so the cache key is too. Its output is discarded.

    Best-effort by design: if it fails, the batch still runs correctly, just at
    the uncached price the cost cap was already sized for.
    """
    params = build_batch_params(settings, sample)
    try:
        response = await client.messages.create(
            model=params["model"],
            system=params["system"],
            output_config=params["output_config"],
            thinking=params["thinking"],
            messages=[{"role": "user", "content": "warm"}],
            max_tokens=16,
        )
    except Exception:
        log.warning("cache warm-up failed; submitting uncached", exc_info=True)
        return
    usage = response.usage
    write_5m, write_1h = cache_write_split(usage)
    await record_usage(
        db,
        run_id="batch-warmup",
        purpose="extraction",
        model=response.model,
        prompt_version=PROMPT_VERSION,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=write_5m,
        cache_write_1h_tokens=write_1h,
    )
    log.info(
        "cache warm-up: wrote %d, read %d prefix tokens",
        usage.cache_creation_input_tokens or 0, usage.cache_read_input_tokens or 0,
    )


async def _breaker_open(db: AsyncSession) -> bool:
    """True when the most recent batch was failed by the circuit breaker."""
    latest = await db.scalar(
        select(ExtractionBatch.status).order_by(ExtractionBatch.submitted_at.desc()).limit(1)
    )
    return latest == "failed"


async def submit_batch(
    db: AsyncSession,
    client: anthropic.AsyncAnthropic,
    *,
    limit: int | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> ExtractionBatch | None:
    """Submit pending postings as one batch; None when there is nothing to do.

    `force` skips the circuit breaker — for the admin endpoint, where a person
    has looked at why the last batch failed. The scheduler never forces.
    """
    settings = settings or get_settings()

    # Transaction-scoped: released by the commit below, or by rollback on error.
    if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _SUBMIT_LOCK_KEY}):
        log.info("batch submit skipped: another submission is in progress")
        return None
    if not force and await _breaker_open(db):
        log.error(
            "batch submit skipped: the last batch tripped the circuit breaker. "
            "Inspect it (GET /admin/extraction-status), then submit by hand "
            "(POST /extract/batch) to resume."
        )
        return None

    listings = await pending_listings(db, limit or settings.extraction_batch_max, settings)
    if not listings:
        return None

    # Size against the cap before anything is sent. Actual spend is ledgered
    # per result on collection; this is the pre-flight check.
    # Already a batched, worst-case figure — see the setting for why the batch
    # discount is not applied on top.
    per_listing = Decimal(str(settings.extraction_est_batch_cost_per_listing_usd))
    affordable = int(Decimal(str(settings.extraction_cost_cap_usd)) / per_listing)
    if len(listings) > affordable:
        log.warning(
            "batch trimmed from %d to %d postings to stay under the $%.2f cap",
            len(listings), affordable, settings.extraction_cost_cap_usd,
        )
        listings = listings[:affordable]

    await _warm_cache(db, client, settings, listings[0])
    remote = await client.messages.batches.create(
        requests=[
            Request(custom_id=str(raw.id), params=build_batch_params(settings, raw))
            for raw in listings
        ]
    )
    row = ExtractionBatch(
        anthropic_batch_id=remote.id,
        status="submitted",
        model=settings.extraction_model,
        prompt_version=PROMPT_VERSION,
        raw_listing_ids=[raw.id for raw in listings],
        request_count=len(listings),
        estimated_cost_usd=per_listing * len(listings),
    )
    db.add(row)
    try:
        await db.commit()
    except Exception:
        # The batch exists and will bill, but nothing records it — so nothing
        # would ever collect it. Cancel rather than pay for orphaned results.
        log.exception("could not record batch %s; cancelling it", remote.id)
        await client.messages.batches.cancel(remote.id)
        raise
    log.info(
        "submitted batch %s: %d postings, est $%.2f",
        remote.id, len(listings), row.estimated_cost_usd,
    )
    return row


@dataclass
class CollectStats:
    batches_collected: int = 0
    batches_failed: int = 0
    still_processing: int = 0
    extracted: int = 0
    fell_back_to_live: int = 0
    dead_lettered: int = 0
    cost_usd: Decimal = Decimal(0)
    errors: list[str] = field(default_factory=list)


def _parse_succeeded(message: anthropic.types.Message) -> JobComponents:
    """Validate a batch result exactly as the live path would.

    Raises ValueError on anything the live path would retry: a refusal, a
    response cut off by max_tokens, or output failing our validators.
    """
    if message.stop_reason == "refusal":
        raise ValueError(f"model refused ({message.stop_reason})")
    body = next((b.text for b in message.content if isinstance(b, TextBlock)), None)
    if not body:
        raise ValueError(f"no text in response (stop_reason={message.stop_reason})")
    try:
        return JobComponents.model_validate_json(body)
    except ValidationError as e:
        raise ValueError(str(e)) from e


async def _collect_one(
    db: AsyncSession,
    client: anthropic.AsyncAnthropic,
    settings: Settings,
    batch: ExtractionBatch,
    stats: CollectStats,
) -> None:
    results = [r async for r in await client.messages.batches.results(batch.anthropic_batch_id)]
    failed = [r for r in results if r.result.type != "succeeded"]

    if results and len(failed) / len(results) > settings.extraction_batch_max_error_rate:
        first = failed[0].result
        batch.status = "failed"
        batch.error = f"{len(failed)}/{len(results)} requests failed; first: {first!r}"[:4000]
        batch.collected_at = datetime.now(UTC)
        await db.commit()
        stats.batches_failed += 1
        stats.errors.append(f"batch {batch.anthropic_batch_id}: {batch.error}")
        log.error("batch %s tripped the circuit breaker: %s", batch.anthropic_batch_id, batch.error)
        return

    run_id = f"batch-{batch.id}"
    raws = {
        raw.id: raw
        for raw in (
            await db.execute(select(RawListing).where(RawListing.id.in_(batch.raw_listing_ids)))
        ).scalars()
    }
    # Collection is idempotent: a crash mid-collection is re-run from the top,
    # and postings already written are skipped rather than duplicated.
    done = set(
        (
            await db.execute(
                select(ListingComponent.raw_listing_id)
                .where(ListingComponent.raw_listing_id.in_(batch.raw_listing_ids))
                .where(ListingComponent.prompt_version == batch.prompt_version)
            )
        ).scalars()
    )

    for item in results:
        raw = raws.get(int(item.custom_id))
        if raw is None or raw.id in done:
            continue

        reason: str
        if item.result.type == "succeeded":
            message = item.result.message
            usage = message.usage
            # Billed whether or not the output validates, so ledger it first.
            stats.cost_usd += await record_usage(
                db,
                run_id=run_id,
                purpose="extraction",
                model=message.model,
                prompt_version=batch.prompt_version,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_input_tokens or 0,
                cache_write_tokens=cache_write_split(usage)[0],
                cache_write_1h_tokens=cache_write_split(usage)[1],
                batch=True,
            )
            try:
                components = _parse_succeeded(message)
            except ValueError as e:
                reason = str(e)
            else:
                await persist_components(db, raw, components, message.model)
                await db.commit()
                batch.succeeded += 1
                stats.extracted += 1
                continue
        else:
            reason = f"batch result {item.result.type}"

        await _live_retry(db, client, settings, batch, raw, run_id, reason, stats)

    batch.status = "collected"
    batch.collected_at = datetime.now(UTC)
    await db.commit()
    stats.batches_collected += 1
    log.info(
        "collected batch %s: %d extracted, %d via live retry, %d dead-lettered",
        batch.anthropic_batch_id, batch.succeeded, batch.fell_back_to_live, batch.dead_lettered,
    )


async def _live_retry(
    db: AsyncSession,
    client: anthropic.AsyncAnthropic,
    settings: Settings,
    batch: ExtractionBatch,
    raw: RawListing,
    run_id: str,
    reason: str,
    stats: CollectStats,
) -> None:
    """Attempts two and three for a posting whose batch result failed."""
    try:
        await check_cap(db, run_id, settings.extraction_cost_cap_usd)
    except CostCapExceeded as e:
        # Leave it pending rather than dead-lettered: it didn't fail, we just
        # stopped paying. The next run picks it up.
        stats.errors.append(f"{raw.source_url}: live retry skipped, {e}")
        return
    try:
        result = await extract_one(
            client,
            settings,
            title=raw.title,
            company=raw.company,
            location=raw.location,
            description=raw.description,
        )
    except Exception as e:
        # Deliberately broad: anything escaping here would abort collection,
        # leave the batch 'submitted', and hit the same posting on every tick —
        # wedging the whole batch. One posting must never cost the batch.
        raw_response = e.raw_response if isinstance(e, ExtractionFailed) else None
        db.add(
            dead_letter(
                raw,
                settings.extraction_model,
                f"batch: {reason}; live: {type(e).__name__}: {e}",
                raw_response,
                3,
            )
        )
        batch.dead_lettered += 1
        stats.dead_lettered += 1
    else:
        stats.cost_usd += await record_usage(
            db,
            run_id=run_id,
            purpose="extraction",
            model=result.model,
            prompt_version=result.prompt_version,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
        )
        await persist_components(db, raw, result.components, result.model)
        batch.fell_back_to_live += 1
        stats.fell_back_to_live += 1
    await db.commit()


async def collect_batches(
    db: AsyncSession,
    client: anthropic.AsyncAnthropic,
    settings: Settings | None = None,
) -> CollectStats:
    """Collect every submitted batch that has finished processing."""
    settings = settings or get_settings()
    stats = CollectStats()
    open_batches = (
        await db.execute(
            select(ExtractionBatch)
            .where(ExtractionBatch.status == "submitted")
            .order_by(ExtractionBatch.submitted_at)
        )
    ).scalars().all()
    # Each batch is isolated: one that errors must not block the others, nor
    # the submit step that runs after this in the same cycle — otherwise a
    # single bad batch id wedges extraction permanently, retried every hour.
    for batch in open_batches:
        try:
            remote = await client.messages.batches.retrieve(batch.anthropic_batch_id)
        except anthropic.NotFoundError:
            # Gone at Anthropic (results expire after 29 days). Nothing to
            # collect; fail it so its postings become eligible again.
            batch.status = "failed"
            batch.error = "batch not found at Anthropic (expired or deleted)"
            batch.collected_at = datetime.now(UTC)
            await db.commit()
            stats.batches_failed += 1
            stats.errors.append(f"batch {batch.anthropic_batch_id}: {batch.error}")
            log.error("batch %s: %s", batch.anthropic_batch_id, batch.error)
            continue
        except Exception as e:
            # Transient (network, 5xx after SDK retries): try again next tick.
            await db.rollback()
            stats.errors.append(f"batch {batch.anthropic_batch_id}: {type(e).__name__}: {e}")
            log.exception("could not check batch %s", batch.anthropic_batch_id)
            continue
        if remote.processing_status != "ended":
            stats.still_processing += 1
            continue
        try:
            await _collect_one(db, client, settings, batch, stats)
        except Exception as e:
            # Collection is idempotent, so a retry next tick is safe.
            await db.rollback()
            stats.errors.append(f"batch {batch.anthropic_batch_id}: {type(e).__name__}: {e}")
            log.exception("could not collect batch %s", batch.anthropic_batch_id)
    return stats


async def run_batch_cycle(db: AsyncSession, client: anthropic.AsyncAnthropic) -> None:
    """One scheduler tick: collect what finished, then submit what's pending."""
    collected = await collect_batches(db, client)
    submitted = await submit_batch(db, client)
    log.info(
        "extraction cycle: collected=%d failed=%d processing=%d extracted=%d live=%d dead=%d "
        "cost=$%.4f; submitted=%s",
        collected.batches_collected, collected.batches_failed, collected.still_processing,
        collected.extracted, collected.fell_back_to_live, collected.dead_lettered,
        collected.cost_usd, f"{submitted.request_count} postings" if submitted else "nothing",
    )
