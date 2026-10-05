"""The airlines (by IATA code, with their names), which the stats name a flight's airline from.

Revision ID: 0010
Revises: 0009
"""
import gzip
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

AIRLINES = Path(__file__).resolve().parent.parent.parent / "airlines.tsv.gz"


def upgrade() -> None:
    airlines = op.create_table(
        'airlines',
        sa.Column('code', sa.Text(), primary_key=True),
        sa.Column('icao', sa.Text()),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('country', sa.Text()),
    )
    with gzip.open(AIRLINES, 'rt', encoding='utf-8') as f:
        found = [line.rstrip('\n').split('\t') for line in f if line.strip()]
    op.bulk_insert(airlines, [{'code': code, 'icao': icao or None, 'name': name, 'country': country or None}
                              for code, icao, name, country in found])


def downgrade() -> None:
    op.drop_table('airlines')
