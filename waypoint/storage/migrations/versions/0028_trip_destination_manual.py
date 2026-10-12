import sqlalchemy as sa
from alembic import op

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('destination_manual', sa.Boolean(), nullable=False, server_default=sa.false()))
    trips = sa.table('trips', sa.column('id', sa.Integer()), sa.column('destination', sa.Text()),
                     sa.column('destination_manual', sa.Boolean()))
    segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('trip_id', sa.Integer()), sa.column('kind', sa.Text()),
                        sa.column('origin', sa.Text()), sa.column('destination', sa.Text()))
    airports = sa.table('airports', sa.column('code', sa.Text()), sa.column('city', sa.Text()))
    bind = op.get_bind()
    first: dict[int, int] = dict(bind.execute(sa.select(segments.c.trip_id, sa.func.min(segments.c.id)).group_by(segments.c.trip_id)).all())
    cities: dict[str, str] = dict(bind.execute(sa.select(airports.c.code, airports.c.city)).all())
    kept = {row.id: row for row in bind.execute(sa.select(segments).where(segments.c.id.in_(list(first.values())))).all()} if first else {}
    typed = []
    for trip_id, destination in bind.execute(sa.select(trips.c.id, trips.c.destination)).all():
        if not destination or not destination.strip():
            continue
        seg = kept.get(first.get(trip_id))
        if seg is None:
            made = None
        elif seg.kind == 'flight' and seg.destination:
            made = cities.get(seg.destination.strip().upper(), seg.destination)
        else:
            made = seg.destination or seg.origin
        if destination != made:
            typed.append(trip_id)
    for start in range(0, len(typed), 500):
        bind.execute(trips.update().where(trips.c.id.in_(typed[start:start + 500])).values(destination_manual=True))


def downgrade() -> None:
    op.drop_column('trips', 'destination_manual')
