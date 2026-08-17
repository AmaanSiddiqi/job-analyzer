"""suggested_companies.ca_jobs: Canadian-role count as the review sort key

The first discovery batch surfaced mostly large US employers (ranked by raw
occurrence count) including one wrong-company slug match. Recording how many
Canadian roles a probed board actually has lets the review queue sort by
Canada relevance and auto-reject zero-CA boards before they reach review.
Additive, nullable.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('suggested_companies', sa.Column('ca_jobs', sa.Integer(), nullable=True))
    # Existing board_found rows were ranked by occurrences and never had their
    # Canadian-role counts measured — send them back through the probe.
    op.execute(
        "UPDATE suggested_companies SET status = 'pending', probed_at = NULL "
        "WHERE status = 'board_found'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('suggested_companies', 'ca_jobs')
