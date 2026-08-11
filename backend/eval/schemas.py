"""
Data model for the eval harness.

Scope note: today's only extractor is `app.services.nlp.extract_skills`
(spaCy PhraseMatcher — CLAUDE.md's frozen `baseline_extractor`). There's no
LLM extraction pipeline yet (that's P1) and no JobComponents schema in
production, so this gold-set format only covers the one field that
actually exists (`skills`). Every record carries `schema_version` so P1's
richer JobComponents fields (title_normalized, seniority, VisaSignals,
etc.) can be added later without invalidating labels already collected.
Dedup (P2) and matching (P5) gold sets should follow the same file-per-task,
`human_verified`-per-record convention rather than inventing a new one.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class PoolListing(BaseModel):
    """One row of eval/gold/listings_pool.jsonl — raw input, no labels yet."""

    listing_id: str  # job_postings.id (as str) if sourced from prod, else a fixture slug
    source: str  # "prod_db" | "fixture"
    title: str
    company: str
    raw_description: str


class DraftExtractionLabel(BaseModel):
    """One row of scripts/draft_label.py's output — before human review."""

    schema_version: int = 1
    listing_id: str
    source: str
    title: str
    company: str
    raw_description: str
    annotator_skills: list[str]  # from the stronger annotator model (draft)
    baseline_skills: list[str]  # from baseline_extractor, computed at draft time
    disagreement: bool  # annotator_skills != baseline_skills, as sets
    annotator_model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoldExtractionLabel(BaseModel):
    """One row of eval/gold/extraction_skills.jsonl — the scored gold set."""

    schema_version: int = 1
    listing_id: str
    source: str
    title: str
    company: str
    raw_description: str
    skills: list[str]  # accepted gold skill set, lowercase
    annotator_model: str | None = None  # None for hand-authored fixtures
    human_verified: bool  # True only if a human explicitly reviewed this row —
    # see review_cli.py's selection policy (all disagreements + 25% random
    # audit of agreements are reviewed; the rest are auto-accepted from the
    # annotator draft with human_verified=False). Published eval numbers
    # should report the human_verified fraction, per CLAUDE.md.
    verification_method: str  # "manual_review" | "auto_accept_agreement" |
    # "auto_accept_unreviewed_disagreement" | "fixture" — the third one means
    # review_cli.py's --sample-size cap excluded this disagreement from manual
    # review; treat it as the least trustworthy category when reading results.
    disagreement_with_baseline: bool = False
    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
