import sqlalchemy as sa
from alembic import op

revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('trip_exclusions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_trip_exclusions_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_trip_exclusions_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('trip_id', 'person_id', name='uq_trip_exclusions_trip_person'),
    )
    op.create_index('ix_trip_exclusions_person_id', 'trip_exclusions', ['person_id'], unique=False)
    op.create_table('segment_exclusions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_segment_exclusions_person_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], name='fk_segment_exclusions_segment_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('segment_id', 'person_id', name='uq_segment_exclusions_segment_person'),
    )
    op.create_index('ix_segment_exclusions_person_id', 'segment_exclusions', ['person_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_segment_exclusions_person_id', table_name='segment_exclusions')
    op.drop_table('segment_exclusions')
    op.drop_index('ix_trip_exclusions_person_id', table_name='trip_exclusions')
    op.drop_table('trip_exclusions')
