import sqlalchemy as sa
from alembic import op

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('done_at', sa.Float()))


def downgrade() -> None:
    op.drop_column('trips', 'done_at')
