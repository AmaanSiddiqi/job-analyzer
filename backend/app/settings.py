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


@lru_cache
def get_settings() -> Settings:
    return Settings()
