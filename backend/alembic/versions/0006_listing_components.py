"""listing_components: LLM extraction output

One row per (raw_listing, prompt_version) — the unique constraint is what
makes a prompt change additive rather than destructive, so an F1 regression
stays attributable to a version and the previous extraction is still there.

Visa flags are nullable BOOLEAN on purpose: NULL means the posting doesn't
address work authorization, which is different from FALSE (it says no). A
partial index covers only the non-NULL rows, since most postings say nothing.

Additive; no existing table is touched.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('listing_components',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('raw_listing_id', sa.BigInteger(), nullable=False),
    sa.Column('prompt_version', sa.Text(), nullable=False),
    sa.Column('model', sa.Text(), nullable=False),
    sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('title_raw', sa.Text(), nullable=False),
    sa.Column('title_normalized', sa.Text(), nullable=False),
    sa.Column('seniority', sa.Text(), nullable=False),
    sa.Column('company_raw', sa.Text(), nullable=False),
    sa.Column('company_canonical', sa.Text(), nullable=False),
    sa.Column('skills', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('skills_unmapped', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('required_quals', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('preferred_quals', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('comp_min', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('comp_max', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('comp_currency', sa.String(length=3), nullable=True),
    sa.Column('comp_period', sa.Text(), nullable=True),
    sa.Column('comp_is_estimated', sa.Boolean(), nullable=False),
    sa.Column('comp_cad_annual_est', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('location_raw', sa.Text(), nullable=True),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('region', sa.Text(), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('remote_policy', sa.Text(), nullable=False),
    sa.Column('visa_sponsorship_available', sa.Boolean(), nullable=True),
    sa.Column('visa_requires_existing_authorization', sa.Boolean(), nullable=True),
    sa.Column('visa_citizenship_or_pr_required', sa.Boolean(), nullable=True),
    sa.Column('visa_evidence', postgresql.ARRAY(sa.String()), nullable=False),
    sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('language', sa.String(length=8), nullable=False),
    sa.Column('extraction_confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.ForeignKeyConstraint(['raw_listing_id'], ['raw_listings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('raw_listing_id', 'prompt_version', name='uq_listing_components_listing_prompt')
    )
    op.create_index('ix_listing_components_prompt_version', 'listing_components', ['prompt_version'], unique=False)
    op.create_index('ix_listing_components_raw_listing_id', 'listing_components', ['raw_listing_id'], unique=False)
    op.create_index('ix_listing_components_skills_gin', 'listing_components', ['skills'], unique=False, postgresql_using='gin')
    op.create_index('ix_listing_components_sponsorship', 'listing_components', ['visa_sponsorship_available'], unique=False, postgresql_where=sa.text('visa_sponsorship_available IS NOT NULL'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_listing_components_sponsorship', table_name='listing_components', postgresql_where=sa.text('visa_sponsorship_available IS NOT NULL'))
    op.drop_index('ix_listing_components_skills_gin', table_name='listing_components', postgresql_using='gin')
    op.drop_index('ix_listing_components_raw_listing_id', table_name='listing_components')
    op.drop_index('ix_listing_components_prompt_version', table_name='listing_components')
    op.drop_table('listing_components')
