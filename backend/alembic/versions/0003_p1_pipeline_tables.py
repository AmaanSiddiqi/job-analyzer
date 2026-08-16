"""P1 groundwork: raw_listings, dead_letters, llm_usage, unmapped_skills, source_type

Schema for the P1 sources-and-extraction pipeline (see CLAUDE.md target
architecture). Purely additive — no existing table is altered except
job_postings gaining a NOT NULL source_type column with server_default
'linkedin', which is correct for every pre-P1 row (LinkedIn was the sole
source). New ingestion code sets the column explicitly.

raw_listings is append-only; idempotency at ingest is the
(source_type, source_url, content_hash) unique constraint. listing_components
(extraction output) arrives with the extraction-pipeline PR, not here.

Non-concurrent CREATE INDEX throughout — all new tables are empty and the
job_postings index is cheap at ~6k rows (same reasoning as 0002's docstring).

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'raw_listings',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('source_name', sa.Text(), nullable=False),
        sa.Column('external_id', sa.Text(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('company', sa.Text(), nullable=False),
        sa.Column('location', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'source_type', 'source_url', 'content_hash',
            name='uq_raw_listings_source_content',
        ),
    )
    op.create_index(
        'ix_raw_listings_fetched_at', 'raw_listings',
        [sa.literal_column('fetched_at DESC')], unique=False,
    )
    op.create_index('ix_raw_listings_source_type', 'raw_listings', ['source_type'], unique=False)
    op.create_index('ix_raw_listings_content_hash', 'raw_listings', ['content_hash'], unique=False)

    op.create_table(
        'dead_letters',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('raw_listing_id', sa.BigInteger(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('error', sa.Text(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dead_letters_kind', 'dead_letters', ['kind'], unique=False)
    op.create_index(
        'ix_dead_letters_created_at', 'dead_letters',
        [sa.literal_column('created_at DESC')], unique=False,
    )

    op.create_table(
        'llm_usage',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.Text(), nullable=False),
        sa.Column('purpose', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('prompt_version', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_usage_run_id', 'llm_usage', ['run_id'], unique=False)
    op.create_index(
        'ix_llm_usage_created_at', 'llm_usage',
        [sa.literal_column('created_at DESC')], unique=False,
    )

    op.create_table(
        'unmapped_skills',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('skill', sa.Text(), nullable=False),
        sa.Column('occurrences', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('skill'),
    )
    op.create_index('ix_unmapped_skills_status', 'unmapped_skills', ['status'], unique=False)

    op.add_column(
        'job_postings',
        sa.Column('source_type', sa.Text(), server_default=sa.text("'linkedin'"), nullable=False),
    )
    op.create_index('ix_job_postings_source_type', 'job_postings', ['source_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_job_postings_source_type', table_name='job_postings')
    op.drop_column('job_postings', 'source_type')
    op.drop_index('ix_unmapped_skills_status', table_name='unmapped_skills')
    op.drop_table('unmapped_skills')
    op.drop_index('ix_llm_usage_created_at', table_name='llm_usage')
    op.drop_index('ix_llm_usage_run_id', table_name='llm_usage')
    op.drop_table('llm_usage')
    op.drop_index('ix_dead_letters_created_at', table_name='dead_letters')
    op.drop_index('ix_dead_letters_kind', table_name='dead_letters')
    op.drop_table('dead_letters')
    op.drop_index('ix_raw_listings_content_hash', table_name='raw_listings')
    op.drop_index('ix_raw_listings_source_type', table_name='raw_listings')
    op.drop_index('ix_raw_listings_fetched_at', table_name='raw_listings')
    op.drop_table('raw_listings')
