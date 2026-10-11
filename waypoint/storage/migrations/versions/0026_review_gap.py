import sqlalchemy as sa
from alembic import op

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('review_items', sa.Column('gap', sa.Text()))


def downgrade() -> None:
    op.drop_column('review_items', 'gap')
