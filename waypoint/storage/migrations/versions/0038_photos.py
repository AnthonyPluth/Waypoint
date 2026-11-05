import sqlalchemy as sa
from alembic import op

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('photo_sources',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('immich_user_id', sa.Text(), nullable=False),
    sa.Column('api_key', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('last_sync', sa.Float(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_photo_sources_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('person_id', 'url', name='uq_photo_sources_person_url'),
    )
    op.create_table('photos',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Text(), nullable=False),
    sa.Column('asset_updated', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('taken_utc', sa.Text(), nullable=False),
    sa.Column('taken_local', sa.Text(), nullable=False),
    sa.Column('taken_offset', sa.Integer(), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('location_source', sa.Text(), nullable=True),
    sa.Column('state', sa.Text(), nullable=True),
    sa.Column('country', sa.Text(), nullable=True),
    sa.Column('trip_id', sa.Integer(), nullable=True),
    sa.Column('segment_id', sa.Integer(), nullable=True),
    sa.Column('match', sa.Text(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=True),
    sa.Column('decided_by', sa.Text(), nullable=True),
    sa.Column('hidden', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('seen', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_photos_segment_id', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['source_id'], ['photo_sources.id'], name='fk_photos_source_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_photos_trip_id', ondelete='SET NULL', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'asset_id', name='uq_photos_source_asset'),
    )
    op.create_index('ix_photos_trip_id', 'photos', ['trip_id'], unique=False)
    op.create_index('ix_photos_segment_id', 'photos', ['segment_id'], unique=False)
    op.create_index('ix_photos_source_id_taken_utc', 'photos', ['source_id', 'taken_utc'], unique=False)
    op.create_table('photo_trip_syncs',
    sa.Column('source_id', sa.Integer(), nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('window_start', sa.Text(), nullable=False),
    sa.Column('window_end', sa.Text(), nullable=False),
    sa.Column('cursor', sa.Text(), nullable=True),
    sa.Column('resume_page', sa.Integer(), nullable=True),
    sa.Column('fetch_started', sa.Text(), nullable=True),
    sa.Column('synced', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['photo_sources.id'], name='fk_photo_trip_syncs_source_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_photo_trip_syncs_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('source_id', 'trip_id'),
    )


def downgrade() -> None:
    op.drop_table('photo_trip_syncs')
    op.drop_index('ix_photos_source_id_taken_utc', table_name='photos')
    op.drop_index('ix_photos_segment_id', table_name='photos')
    op.drop_index('ix_photos_trip_id', table_name='photos')
    op.drop_table('photos')
    op.drop_table('photo_sources')
