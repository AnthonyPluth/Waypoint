"""Brand logos (`brand_logos`): the logos of the airlines, hotels, rental companies and cruise lines in bookings, fetched from
Logo.dev once a key is saved in Settings and kept here so the app never asks anyone else for an image. A cache: not part of
a backup, and nothing else changes.

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brand_logos',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('logo', sa.LargeBinary()),
        sa.Column('logo_type', sa.Text()),
        sa.Column('checked', sa.Text()),
    )


def downgrade() -> None:
    op.drop_table('brand_logos')
