import time

import sqlalchemy as sa
from alembic import op

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


photos = sa.table('photos', sa.column('id', sa.Integer()), sa.column('source_id', sa.Integer()), sa.column('asset_id', sa.Text()),
                  sa.column('trip_id', sa.Integer()), sa.column('hidden', sa.Boolean()))
sources = sa.table('photo_sources', sa.column('id', sa.Integer()), sa.column('person_id', sa.Integer()), sa.column('url', sa.Text()))
syncs = sa.table('photo_trip_syncs', sa.column('source_id', sa.Integer()))
exclusions = sa.table('photo_exclusions', sa.column('person_id', sa.Integer()), sa.column('asset_id', sa.Text()), sa.column('trip_id', sa.Integer()),
                      sa.column('created', sa.Float()))
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
    hidden = sa.select(sources.c.person_id, photos.c.asset_id, photos.c.trip_id, sa.cast(sa.literal(time.time()), sa.Float())).distinct() \
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
    op.execute(photos.delete())
    op.execute(syncs.delete())
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
