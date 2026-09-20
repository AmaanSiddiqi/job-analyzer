"""raw_listings.source_url index — joins job_postings to extracted components

The dashboard's extracted-skills mode matches a job_posting to its
listing_components through source_url. The existing unique constraint leads
with source_type, so it cannot serve a lookup by source_url alone.

Additive; no existing table is touched.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_raw_listings_source_url', 'raw_listings', ['source_url'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_raw_listings_source_url', table_name='raw_listings')
