import time

import sqlalchemy as sa
from alembic import op

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None

ONLY_ME = 'only_me'
TRIP = 'trip'

photos = sa.table('photos', sa.column('id', sa.Integer()), sa.column('source_id', sa.Integer()), sa.column('asset_id', sa.Text()),
                  sa.column('trip_id', sa.Integer()), sa.column('hidden', sa.Boolean()))
sources = sa.table('photo_sources', sa.column('id', sa.Integer()), sa.column('person_id', sa.Integer()), sa.column('url', sa.Text()))
syncs = sa.table('photo_trip_syncs', sa.column('source_id', sa.Integer()))
grants = sa.table('photo_grants', sa.column('person_id', sa.Integer()), sa.column('trip_id', sa.Integer()), sa.column('scope', sa.Text()),
                  sa.column('revoked', sa.Float()))
exclusions = sa.table('photo_exclusions', sa.column('person_id', sa.Integer()), sa.column('asset_id', sa.Text()), sa.column('trip_id', sa.Integer()),
                      sa.column('created', sa.Float()))
trip_people = sa.table('trip_people', sa.column('trip_id', sa.Integer()), sa.column('person_id', sa.Integer()))
trips = sa.table('trips', sa.column('id', sa.Integer()), sa.column('booked_by', sa.Integer()))
segments = sa.table('segments', sa.column('id', sa.Integer()), sa.column('trip_id', sa.Integer()), sa.column('booked_by', sa.Integer()))
recipients = sa.table('segment_recipients', sa.column('segment_id', sa.Integer()), sa.column('person_id', sa.Integer()))
travelers = sa.table('segment_travelers', sa.column('segment_id', sa.Integer()), sa.column('person_id', sa.Integer()))


def _outsiders():
    def member(trip_col, person_col):
        return sa.select(trip_people.c.person_id).where(trip_people.c.trip_id == trip_col, trip_people.c.person_id == person_col).exists()
    by_trip = sa.select(trips.c.id.label('trip_id')).where(trips.c.booked_by.is_not(None), ~member(trips.c.id, trips.c.booked_by))
    by_segment = sa.select(segments.c.trip_id.label('trip_id')).where(segments.c.booked_by.is_not(None), ~member(segments.c.trip_id, segments.c.booked_by))
    received = sa.select(segments.c.trip_id.label('trip_id')).join_from(recipients, segments, segments.c.id == recipients.c.segment_id) \
        .where(~member(segments.c.trip_id, recipients.c.person_id))
    aboard = sa.select(segments.c.trip_id.label('trip_id')).join_from(travelers, segments, segments.c.id == travelers.c.segment_id) \
        .where(travelers.c.person_id.is_not(None), ~member(segments.c.trip_id, travelers.c.person_id))
    return sa.union(by_trip, by_segment, received, aboard).subquery()


def upgrade() -> None:
    op.create_table('photo_grants',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.Text(), server_default=sa.text("'only_me'"), nullable=False),
    sa.Column('revoked', sa.Float(), nullable=True),
    sa.Column('changed', sa.Float(), nullable=False),
    sa.Column('granted_by', sa.Text(), nullable=False),
    sa.Column('ask_again', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.CheckConstraint("scope IN ('only_me', 'trip')", name='ck_photo_grants_scope'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_photo_grants_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_photo_grants_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('person_id', 'trip_id'),
    )
    op.create_index('ix_photo_grants_trip_id', 'photo_grants', ['trip_id'], unique=False)
    op.create_table('photo_exclusions',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Text(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.Column('was_trip_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_photo_exclusions_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_photo_exclusions_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['was_trip_id'], ['trips.id'], name='fk_photo_exclusions_was_trip_id', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('person_id', 'asset_id', 'trip_id'),
    )
    op.create_index('ix_photo_exclusions_trip_id', 'photo_exclusions', ['trip_id'], unique=False)
    op.create_table('photo_sharing_prefs',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('default_scope', sa.Text(), server_default=sa.text("'only_me'"), nullable=False),
    sa.Column('share_all', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('set_by', sa.Text(), nullable=True),
    sa.Column('share_all_since', sa.Float(), nullable=True),
    sa.Column('steward_sub', sa.Text(), nullable=True),
    sa.CheckConstraint("default_scope IN ('only_me', 'trip')", name='ck_photo_sharing_prefs_default_scope'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_photo_sharing_prefs_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('person_id'),
    )
    hidden = sa.select(sources.c.person_id, photos.c.asset_id, photos.c.trip_id, sa.literal(time.time(), sa.Float())).distinct() \
        .join_from(photos, sources, sources.c.id == photos.c.source_id) \
        .where(photos.c.hidden.is_(sa.true()), photos.c.trip_id.is_not(None))
    op.execute(exclusions.insert().from_select(['person_id', 'asset_id', 'trip_id', 'created'], hidden))
    op.execute(photos.delete())
    op.execute(syncs.delete())
    op.drop_column('photos', 'hidden')
    with op.batch_alter_table('photo_sources') as batch:
        batch.drop_constraint('uq_photo_sources_person_url', type_='unique')
        batch.create_unique_constraint('uq_photo_sources_person_url_user', ['person_id', 'url', 'immich_user_id'])


def downgrade() -> None:
    op.add_column('photos', sa.Column('hidden', sa.Boolean(), server_default=sa.false(), nullable=False))
    active = sa.select(grants.c.person_id).where(grants.c.person_id == sources.c.person_id, grants.c.trip_id == photos.c.trip_id,
                                                 grants.c.revoked.is_(None))
    aboard = sa.select(trip_people.c.person_id).where(trip_people.c.person_id == sources.c.person_id, trip_people.c.trip_id == photos.c.trip_id)
    removed = sa.select(exclusions.c.asset_id).where(exclusions.c.person_id == sources.c.person_id, exclusions.c.asset_id == photos.c.asset_id,
                                                     exclusions.c.trip_id == photos.c.trip_id)
    unseen = sa.select(photos.c.id).join_from(photos, sources, sources.c.id == photos.c.source_id) \
        .where(sa.or_(photos.c.trip_id.is_(None), ~active.exists(), ~aboard.exists(), removed.exists()))
    op.execute(photos.delete().where(photos.c.id.in_(unseen)))
    outsiders = _outsiders()
    seen_by_an_outsider = photos.c.trip_id.in_(sa.select(outsiders.c.trip_id))
    private = sa.select(photos.c.id).join_from(photos, sources, sources.c.id == photos.c.source_id) \
        .where(sa.or_(active.where(grants.c.scope == ONLY_ME).exists(), sa.and_(active.where(grants.c.scope == TRIP).exists(), seen_by_an_outsider)))
    op.execute(photos.update().where(photos.c.id.in_(private)).values(hidden=True))
    first = sa.select(sa.func.min(sources.c.id)).group_by(sources.c.person_id, sources.c.url)
    op.execute(sources.delete().where(sources.c.id.not_in(first)))
    with op.batch_alter_table('photo_sources') as batch:
        batch.drop_constraint('uq_photo_sources_person_url_user', type_='unique')
        batch.create_unique_constraint('uq_photo_sources_person_url', ['person_id', 'url'])
    op.drop_table('photo_sharing_prefs')
    op.drop_index('ix_photo_exclusions_trip_id', table_name='photo_exclusions')
    op.drop_table('photo_exclusions')
    op.drop_index('ix_photo_grants_trip_id', table_name='photo_grants')
    op.drop_table('photo_grants')
