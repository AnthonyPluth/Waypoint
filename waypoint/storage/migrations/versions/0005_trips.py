"""Trips and segments, with who is on them, and the airports (by IATA code, with their time zone) that fill in a flight's
zones.

Revision ID: 0005
Revises: 0004
"""
import gzip
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

AIRPORTS = Path(__file__).resolve().parent.parent.parent / "airports.tsv.gz"


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=f'fk_{table}_{column}', ondelete=ondelete,
                                   deferrable=True, initially='IMMEDIATE')


def upgrade() -> None:
    airports = op.create_table(
        'airports',
        sa.Column('code', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('city', sa.Text(), nullable=False),
        sa.Column('country', sa.Text(), nullable=False),
        sa.Column('zone', sa.Text(), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
    )
    op.create_table(
        'trips',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('start_date', sa.Text()),
        sa.Column('end_date', sa.Text()),
        sa.Column('destination', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.Column('auto', sa.Boolean(), nullable=False),
        sa.Column('booked_by', sa.Integer()),
        _fk('trips', 'booked_by', 'people.id', 'SET NULL'),
    )
    op.create_index('ix_trips_booked_by', 'trips', ['booked_by'])
    op.create_table(
        'segments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('confirmation', sa.Text()),
        sa.Column('provider', sa.Text()),
        sa.Column('start_local', sa.Text(), nullable=False),
        sa.Column('start_zone', sa.Text(), nullable=False),
        sa.Column('end_local', sa.Text(), nullable=False),
        sa.Column('end_zone', sa.Text(), nullable=False),
        sa.Column('origin', sa.Text()),
        sa.Column('destination', sa.Text()),
        sa.Column('details', sa.Text()),
        sa.Column('manage_url', sa.Text()),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('booked_by', sa.Integer()),
        sa.Column('locked_fields', sa.Text()),
        _fk('segments', 'trip_id', 'trips.id', 'CASCADE'),
        _fk('segments', 'booked_by', 'people.id', 'SET NULL'),
    )
    op.create_index('ix_segments_trip_id', 'segments', ['trip_id'])
    op.create_index('ix_segments_booked_by', 'segments', ['booked_by'])
    op.create_table(
        'segment_travelers',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment_id', sa.Integer(), nullable=False),
        sa.Column('person_id', sa.Integer()),
        sa.Column('name', sa.Text()),
        _fk('segment_travelers', 'segment_id', 'segments.id', 'CASCADE'),
        _fk('segment_travelers', 'person_id', 'people.id', 'CASCADE'),
    )
    op.create_index('ix_segment_travelers_segment_id', 'segment_travelers', ['segment_id'])
    op.create_index('ix_segment_travelers_person_id', 'segment_travelers', ['person_id'])
    with gzip.open(AIRPORTS, 'rt', encoding='utf-8') as f:
        found = [line.rstrip('\n').split('\t') for line in f if line.strip()]
    op.bulk_insert(airports, [{'code': c, 'name': n, 'city': city, 'country': country, 'zone': z,
                               'latitude': float(lat), 'longitude': float(lon)}
                              for c, n, city, country, z, lat, lon in found])


def downgrade() -> None:
    op.drop_index('ix_segment_travelers_person_id', table_name='segment_travelers')
    op.drop_index('ix_segment_travelers_segment_id', table_name='segment_travelers')
    op.drop_table('segment_travelers')
    op.drop_index('ix_segments_booked_by', table_name='segments')
    op.drop_index('ix_segments_trip_id', table_name='segments')
    op.drop_table('segments')
    op.drop_index('ix_trips_booked_by', table_name='trips')
    op.drop_table('trips')
    op.drop_table('airports')
