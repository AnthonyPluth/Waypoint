import time

import sqlalchemy as sa
from alembic import op

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None

ONLY_ME = 'only_me'

photos = sa.table('photos', sa.column('id', sa.Integer()), sa.column('source_id', sa.Integer()), sa.column('asset_id', sa.Text()),
                  sa.column('trip_id', sa.Integer()), sa.column('hidden', sa.Boolean()))
sources = sa.table('photo_sources', sa.column('id', sa.Integer()), sa.column('person_id', sa.Integer()))
syncs = sa.table('photo_trip_syncs', sa.column('source_id', sa.Integer()))
grants = sa.table('photo_grants', sa.column('person_id', sa.Integer()), sa.column('trip_id', sa.Integer()), sa.column('scope', sa.Text()),
                  sa.column('revoked', sa.Float()))
exclusions = sa.table('photo_exclusions', sa.column('person_id', sa.Integer()), sa.column('asset_id', sa.Text()), sa.column('trip_id', sa.Integer()),
                      sa.column('created', sa.Float()))
trip_people = sa.table('trip_people', sa.column('trip_id', sa.Integer()), sa.column('person_id', sa.Integer()))


def upgrade() -> None:
    op.create_table('photo_grants',
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('scope', sa.Text(), server_default=sa.text("'only_me'"), nullable=False),
    sa.Column('revoked', sa.Float(), nullable=True),
    sa.Column('changed', sa.Float(), nullable=False),
    sa.Column('granted_by', sa.Text(), nullable=False),
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
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_photo_exclusions_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_photo_exclusions_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
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
    private = sa.select(photos.c.id).join_from(photos, sources, sources.c.id == photos.c.source_id).where(active.where(grants.c.scope == ONLY_ME).exists())
    op.execute(photos.update().where(photos.c.id.in_(private)).values(hidden=True))
    op.drop_table('photo_sharing_prefs')
    op.drop_index('ix_photo_exclusions_trip_id', table_name='photo_exclusions')
    op.drop_table('photo_exclusions')
    op.drop_index('ix_photo_grants_trip_id', table_name='photo_grants')
    op.drop_table('photo_grants')
