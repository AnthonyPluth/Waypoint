import sqlalchemy as sa
from alembic import op

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('review_items') as batch:
        batch.add_column(sa.Column('matches', sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table('review_items') as batch:
        batch.drop_column('matches')
