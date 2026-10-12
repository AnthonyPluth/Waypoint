import json

import sqlalchemy as sa
from alembic import op

from waypoint.storage import geocode

revision = '0029'
down_revision = '0027'
branch_labels = None
depends_on = None

BATCH = 500


def _address(raw):
    try:
        found = json.loads(raw) if raw else {}
    except ValueError:
        return None
    value = found.get('address') if isinstance(found, dict) else None
    return value if isinstance(value, str) else None


def upgrade() -> None:
    op.add_column('segments', sa.Column('latitude', sa.Float()))
    op.add_column('segments', sa.Column('longitude', sa.Float()))
    op.add_column('segments', sa.Column('geo_precision', sa.Text()))
    segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('kind', sa.Text()), sa.column('origin', sa.Text()),
                        sa.column('destination', sa.Text()), sa.column('details', sa.Text()), sa.column('latitude', sa.Float()),
                        sa.column('longitude', sa.Float()), sa.column('geo_precision', sa.Text()))
    conn = op.get_bind()
    rows = conn.execute(sa.select(segments.c.id, segments.c.kind, segments.c.origin, segments.c.destination, segments.c.details)
                        .where(segments.c.kind.in_(geocode.LOCATED_KINDS)).order_by(segments.c.id)).fetchall()
    found = []
    for row_id, kind, origin, destination, details in rows:
        point = geocode.locate(kind, origin, destination, _address(details))
        if point is not None:
            found.append({'b_id': row_id, 'b_lat': point.latitude, 'b_lon': point.longitude, 'b_precision': point.precision})
    update = (sa.update(segments).where(segments.c.id == sa.bindparam('b_id'))
              .values(latitude=sa.bindparam('b_lat'), longitude=sa.bindparam('b_lon'), geo_precision=sa.bindparam('b_precision')))
    for start in range(0, len(found), BATCH):
        conn.execute(update, found[start:start + BATCH])


def downgrade() -> None:
    op.drop_column('segments', 'geo_precision')
    op.drop_column('segments', 'longitude')
    op.drop_column('segments', 'latitude')
