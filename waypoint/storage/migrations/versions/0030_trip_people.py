import sqlalchemy as sa
from alembic import op

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'trip_people',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('trip_id', sa.Integer(), sa.ForeignKey('trips.id', name='fk_trip_people_trip_id', ondelete='CASCADE',
                                                         deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.Column('person_id', sa.Integer(), sa.ForeignKey('people.id', name='fk_trip_people_person_id', ondelete='CASCADE',
                                                            deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.UniqueConstraint('trip_id', 'person_id', name='uq_trip_people_trip_person'),
    )
    op.create_index('ix_trip_people_person_id', 'trip_people', ['person_id'])
    op.add_column('segments', sa.Column('travelers_from_trip', sa.Boolean(), nullable=False, server_default=sa.false()))
    trip_people = sa.table('trip_people', sa.column('trip_id', sa.Integer()), sa.column('person_id', sa.Integer()))
    segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('trip_id', sa.Integer()))
    travelers = sa.table('segment_travelers', sa.column('segment_id', sa.Integer()), sa.column('person_id', sa.Integer()))
    named = (sa.select(segments.c.trip_id, travelers.c.person_id).distinct()
             .select_from(travelers.join(segments, segments.c.id == travelers.c.segment_id))
             .where(travelers.c.person_id.is_not(None)).order_by(segments.c.trip_id, travelers.c.person_id))
    op.get_bind().execute(sa.insert(trip_people).from_select(['trip_id', 'person_id'], named))


def downgrade() -> None:
    trip_people = sa.table('trip_people', sa.column('id', sa.Integer()), sa.column('trip_id', sa.Integer()),
                           sa.column('person_id', sa.Integer()))
    segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('trip_id', sa.Integer()),
                        sa.column('travelers_from_trip', sa.Boolean()))
    travelers = sa.table('segment_travelers', sa.column('segment_id', sa.Integer()), sa.column('person_id', sa.Integer()),
                         sa.column('name', sa.Text()), sa.column('seat', sa.Text()))
    bind = op.get_bind()
    flagged = bind.execute(sa.select(segments.c.id, segments.c.trip_id).where(segments.c.travelers_from_trip.is_(True))
                           .order_by(segments.c.id)).all()
    everyone: dict[int, list[int]] = {}
    for trip_id, person_id in bind.execute(sa.select(trip_people.c.trip_id, trip_people.c.person_id).order_by(trip_people.c.id)).all():
        everyone.setdefault(trip_id, []).append(person_id)
    rows = [{'segment_id': segment_id, 'person_id': person_id, 'name': None, 'seat': None}
            for segment_id, trip_id in flagged for person_id in everyone.get(trip_id, [])]
    if rows:
        bind.execute(sa.insert(travelers), rows)
    op.drop_column('segments', 'travelers_from_trip')
    op.drop_index('ix_trip_people_person_id', table_name='trip_people')
    op.drop_table('trip_people')
