import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('review_items', sa.Column('suggestion', sa.Text()))
    op.add_column('review_items', sa.Column('suggestion_error', sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table('review_items') as batch:
        batch.drop_column('suggestion_error')
        batch.drop_column('suggestion')
