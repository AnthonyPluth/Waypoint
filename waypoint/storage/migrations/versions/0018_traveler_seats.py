import sqlalchemy as sa
from alembic import op

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('segment_travelers', sa.Column('seat', sa.Text()))


def downgrade() -> None:
    op.drop_column('segment_travelers', 'seat')
