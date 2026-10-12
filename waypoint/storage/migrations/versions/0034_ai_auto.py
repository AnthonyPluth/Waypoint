import sqlalchemy as sa
from alembic import op

revision = '0034'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('review_items', sa.Column('auto_state', sa.Text()))
    op.add_column('review_items', sa.Column('auto_tries', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('review_items', 'auto_tries')
    op.drop_column('review_items', 'auto_state')
