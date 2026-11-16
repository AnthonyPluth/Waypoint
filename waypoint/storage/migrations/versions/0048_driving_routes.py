import sqlalchemy as sa
from alembic import op

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('driving_routes',
    sa.Column('trip_id', sa.Integer(), nullable=False),
    sa.Column('from_lat', sa.Integer(), nullable=False),
    sa.Column('from_lon', sa.Integer(), nullable=False),
    sa.Column('to_lat', sa.Integer(), nullable=False),
    sa.Column('to_lon', sa.Integer(), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('stored', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name='fk_driving_routes_trip_id', ondelete='CASCADE', initially='IMMEDIATE', deferrable=True),
    sa.PrimaryKeyConstraint('trip_id', 'from_lat', 'from_lon', 'to_lat', 'to_lon'),
    )


def downgrade() -> None:
    op.drop_table('driving_routes')
