"""Memberships lose their tier (`loyalty_ids.tier`), and only Known Traveler and redress numbers keep an expiry: an airline, hotel or car
program number doesn't expire, so any expiry saved on one is cleared. The downgrade puts back an empty tier column (what was
cleared isn't restored).

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    loyalty_ids = sa.table('loyalty_ids', sa.column('kind', sa.Text()), sa.column('expiry', sa.Text()))
    op.execute(loyalty_ids.update().where(loyalty_ids.c.kind.in_(['airline', 'hotel', 'car'])).values(expiry=None))
    op.drop_column('loyalty_ids', 'tier')   # (not a batch: rebuilding the table would take its rows with a cascade)


def downgrade() -> None:
    op.add_column('loyalty_ids', sa.Column('tier', sa.Text()))
