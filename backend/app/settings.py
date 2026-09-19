"""Typed settings for P1 ingestion config (pydantic-settings).

New P1 configuration goes here instead of scattered os.getenv calls.
Pre-P1 modules (auth, database, scraper flag) keep their existing env
reads — migrating them is churn without benefit; new code uses Settings.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Feature flag for Greenhouse/Lever/Ashby board ingestion. Default off:
    # flipping it in Railway is the supervised go-live step.
    enable_board_ingestion: bool = False

    # Max concurrent board fetches. One HTTP request per company per run,
    # spread across three vendors — modest concurrency is deliberate.
    board_fetch_concurrency: int = 4

    # Keep only listings whose location looks Canadian (or remote without an
    # explicit foreign scope). The product is Canada-focused; several listed
    # companies post globally (e.g. Geotab's German roles).
    board_canada_only: bool = True

    # Scheduler cadence for board ingestion runs.
    board_ingest_interval_hours: int = 6

    # --- Aggregator ingestion (Adzuna + Jooble) ---

    # Feature flag; also requires the API credentials below to be set.
    enable_aggregator_ingestion: bool = False

    # Free-tier credentials — register at developer.adzuna.com / jooble.org/api.
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jooble_api_key: str = ""

    # Adzuna pages fetched per keyword (50 results/page).
    adzuna_pages_per_keyword: int = 2
    # Only listings posted within this window (Adzuna max_days_old param);
    # scheduled runs re-see recent posts, idempotency makes that a no-op.
    aggregator_max_days_old: int = 7
    # Jooble pages fetched per keyword.
    jooble_pages_per_keyword: int = 2

    # --- LLM extraction (P1 flagship) ---

    # Feature flag; also requires ANTHROPIC_API_KEY. Default off so a deploy
    # never starts spending on its own.
    enable_llm_extraction: bool = False

    # Sonnet 5 keeps Opus 5 free to be the *stronger, different* eval annotator
    # CLAUDE.md requires — same-model labeling would make the eval circular.
    extraction_model: str = "claude-sonnet-5"
    # Hard abort once a run's ledgered spend reaches this (CLAUDE.md default).
    extraction_cost_cap_usd: float = 15.0
    # Listings per run when no explicit limit is passed.
    extraction_batch_size: int = 50
    extraction_max_tokens: int = 4096
    # low is enough for schema-constrained extraction and keeps the backfill
    # affordable; raise it if the eval shows visa-evidence recall suffering.
    extraction_effort: str = "low"
    # Two standing cost rules (CLAUDE.md): the cheapest token is one never sent.
    # 26% of the corpus is >90 days old and mostly filled/evergreen, and
    # aggregator snippets are truncated so they extract poorly.
    # Batch path (CLAUDE.md rule d: batch API for backfills — half price).
    # How often the scheduler collects finished batches and submits new work.
    # 45, not 60: each cycle's batch reads the 1-hour prompt cache, and a read
    # refreshes its TTL — so a cycle shorter than the TTL keeps the cache warm
    # indefinitely, and only a cold start pays the 2x write (see batch.py).
    extraction_interval_minutes: int = 45
    # Most requests in one submission. The cost cap trims this further.
    extraction_batch_max: int = 2000
    # Per-listing cost of a *batched* extraction, used to size a batch against
    # the cost cap before submitting (actual spend is ledgered on collection).
    # This is the measured worst case — no cache hits — and deliberately so:
    # a real 6-request batch on 2026-09-19 got zero cache reads (every request
    # paid a 4,322-token cache write at 1.25x) and cost $0.0149/listing, no
    # cheaper than live. A pre-check that assumed caching works would let a
    # batch run to ~2x the cap before the ledger noticed. A cap that only holds
    # when things go well isn't a cap.
    extraction_est_batch_cost_per_listing_usd: float = 0.015
    # Circuit breaker: above this share of failed requests, a batch is marked
    # failed and nothing falls back to the (2x price) live path — a systematic
    # fault like a rejected schema would otherwise re-run every listing live.
    extraction_batch_max_error_rate: float = 0.2
    extraction_max_posting_age_days: int | None = 90
    extraction_skip_aggregators: bool = True

    # Adaptive thinking is Sonnet 5's default and measurably doubles cost here
    # (~$0.032 vs ~$0.016 per listing on real gold-set token counts), so it
    # starts off: extraction is schema-constrained, which is where thinking
    # buys least. The eval scores both settings — turn it on if visa-evidence
    # recall actually needs it, rather than paying 2x on the assumption.
    extraction_thinking: bool = False

    # Whether aggregator listings also upsert into job_postings (the live
    # dashboard table). Off by default: the same real job often appears on
    # both a company board and an aggregator with different URLs, which
    # double-counts trends until P2's canonical dedup lands. Aggregator data
    # still lands in raw_listings (extraction input + company discovery).
    aggregators_to_postings: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
