import sqlalchemy as sa
from alembic import op

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('photo_trip_syncs') as batch:
        batch.add_column(sa.Column('relist_gen', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('photo_trip_syncs') as batch:
        batch.drop_column('relist_gen')
