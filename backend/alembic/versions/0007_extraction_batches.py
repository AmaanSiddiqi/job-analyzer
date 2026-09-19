"""extraction_batches: DB-tracked Message Batches API submissions

A batch runs for minutes to hours, so its id has to survive the process that
submitted it — otherwise a deploy mid-batch orphans results we already paid for.
raw_listing_ids keeps in-flight listings out of the next submission.

Additive; no existing table is touched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'extraction_batches',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('anthropic_batch_id', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('prompt_version', sa.Text(), nullable=False),
        sa.Column('raw_listing_ids', postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column('request_count', sa.Integer(), nullable=False),
        sa.Column('estimated_cost_usd', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('succeeded', sa.Integer(), nullable=False),
        sa.Column('fell_back_to_live', sa.Integer(), nullable=False),
        sa.Column('dead_lettered', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('anthropic_batch_id'),
    )
    op.create_index(
        'ix_extraction_batches_open',
        'extraction_batches',
        ['status'],
        unique=False,
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_extraction_batches_open',
        table_name='extraction_batches',
        postgresql_where=sa.text("status = 'submitted'"),
    )
    op.drop_table('extraction_batches')
