import sqlalchemy as sa
from alembic import op

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('photos') as batch:
        batch.add_column(sa.Column('decided_at', sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('photos') as batch:
        batch.drop_column('decided_at')
