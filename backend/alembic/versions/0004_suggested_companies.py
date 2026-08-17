"""suggested_companies: aggregator-driven board discovery queue

Companies appearing in Adzuna/Jooble data that aren't in companies.yaml
accumulate here; a probe job checks for public Greenhouse/Lever/Ashby
boards and Amaan promotes verified hits to the YAML (never auto-added).
Additive only.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'suggested_companies',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_name', sa.Text(), nullable=False),
        sa.Column('occurrences', sa.Integer(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column('probed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('board', sa.Text(), nullable=True),
        sa.Column('board_token', sa.Text(), nullable=True),
        sa.Column('board_jobs', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_suggested_companies_name_lower', 'suggested_companies',
        [sa.literal_column('lower(company_name)')], unique=True,
    )
    op.create_index(
        'ix_suggested_companies_status', 'suggested_companies', ['status'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_suggested_companies_status', table_name='suggested_companies')
    op.drop_index('uq_suggested_companies_name_lower', table_name='suggested_companies')
    op.drop_table('suggested_companies')
