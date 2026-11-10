import sqlalchemy as sa
from alembic import op

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('review_items') as batch:
        batch.add_column(sa.Column('parking', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('review_items') as batch:
        batch.drop_column('parking')
