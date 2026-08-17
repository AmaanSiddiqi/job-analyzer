from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    date_scraped: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    # Which pipeline produced this row: 'linkedin' (legacy scraper), or one of
    # the P1 sources ('greenhouse' | 'lever' | 'ashby' | 'adzuna' | 'jooble').
    # Server default keeps the pre-P1 rows honest without a backfill step.
    source_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'linkedin'")
    )

    __table_args__ = (
        # GET /jobs's default listing orders by this with no filter — a full
        # table scan + sort on every unfiltered page load without it (AUDIT.md §4)
        Index("ix_job_postings_date_scraped", text("date_scraped DESC")),
        # trends.py GROUP BY company / ORDER BY count
        Index("ix_job_postings_company", "company"),
        # jobs.py filters func.lower(company) == ... exactly — a plain index on
        # `company` doesn't serve a lower() comparison, this is the matching
        # expression index
        Index("ix_job_postings_company_lower", text("lower(company)")),
        # trends.py GROUP BY title
        Index("ix_job_postings_title", "title"),
        # unnest(skills) queries across /trends/skills, /trends/skills/history
        Index("ix_job_postings_skills_gin", "skills", postgresql_using="gin"),
        # P1 per-source counts (source health, ingestion dashboards)
        Index("ix_job_postings_source_type", "source_type"),
    )


class RawListing(Base):
    """Append-only record of every listing as fetched from a source.

    This is the input to the LLM extraction pipeline. Rows are never updated:
    if a source returns changed content for the same job, that's a new row
    (same external_id, different content_hash). Idempotency at ingest is the
    (source_type, source_url, content_hash) unique constraint — re-fetching
    unchanged content is a no-op.
    """

    __tablename__ = "raw_listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Company slug / board token for board sources, API name for aggregators.
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    # The source's own job identifier, when it has one (board JSON ids).
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 over normalized (title, company, location, description).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Full source API response for this listing — lets extraction be re-run
    # with more fields later without re-fetching.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_url", "content_hash", name="uq_raw_listings_source_content"
        ),
        Index("ix_raw_listings_fetched_at", text("fetched_at DESC")),
        Index("ix_raw_listings_source_type", "source_type"),
        Index("ix_raw_listings_content_hash", "content_hash"),
    )


class DeadLetter(Base):
    """Failed pipeline items (3 attempts exhausted) held for inspect/requeue."""

    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # What kind of work failed: 'ingestion' | 'extraction' (more kinds later).
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    raw_listing_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Enough context to retry the work item without this conversation's state —
    # for extraction failures this includes the raw LLM response per CLAUDE.md.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_dead_letters_kind", "kind"),
        Index("ix_dead_letters_created_at", text("created_at DESC")),
    )


class LlmUsage(Base):
    """Per-call LLM spend ledger backing the hard cost cap (default $15/run)."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Groups calls belonging to one logical run so the cap is per-run.
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)  # 'extraction' | 'eval' | ...
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_llm_usage_run_id", "run_id"),
        Index("ix_llm_usage_created_at", text("created_at DESC")),
    )


class SuggestedCompany(Base):
    """Companies seen in aggregator (Adzuna/Jooble) data that aren't in
    sources/companies.yaml — the discovery queue that grows the board list.

    A probe job checks whether each has a public Greenhouse/Lever/Ashby board
    (identity-verified); Amaan reviews verified hits and promotes them to
    companies.yaml. Never auto-added: wrong-company slug collisions are the
    failure mode the human review exists to catch.
    """

    __tablename__ = "suggested_companies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Display name as seen in aggregator data; unique case-insensitively via
    # the expression index below.
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # 'pending' → probe → 'board_found' (with board/token/board_jobs filled)
    # or 'no_board'; Amaan's review moves board_found → 'added' | 'rejected'.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    probed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    board: Mapped[str | None] = mapped_column(Text, nullable=True)
    board_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    board_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("uq_suggested_companies_name_lower", text("lower(company_name)"), unique=True),
        Index("ix_suggested_companies_status", "status"),
    )


class UnmappedSkill(Base):
    """Extracted skills with no taxonomy match, accumulated for weekly review."""

    __tablename__ = "unmapped_skills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    skill: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # lowercase
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # 'pending' until reviewed, then 'mapped' (added to taxonomy) or 'rejected'.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))

    __table_args__ = (Index("ix_unmapped_skills_status", "status"),)
