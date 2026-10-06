"""A seat for each traveller on a segment (`segment_travelers.seat`), where a booking had one `seat` in its details for all of them.
Nothing is moved: what was entered before stays in the booking's details, which the stats and the cards still fall back to.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('segment_travelers', sa.Column('seat', sa.Text()))


def downgrade() -> None:
    op.drop_column('segment_travelers', 'seat')   # (not a batch: rebuilding the table would take its rows with the segment's cascade)
