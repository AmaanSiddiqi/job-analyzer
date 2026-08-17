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

    # Whether aggregator listings also upsert into job_postings (the live
    # dashboard table). Off by default: the same real job often appears on
    # both a company board and an aggregator with different URLs, which
    # double-counts trends until P2's canonical dedup lands. Aggregator data
    # still lands in raw_listings (extraction input + company discovery).
    aggregators_to_postings: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
