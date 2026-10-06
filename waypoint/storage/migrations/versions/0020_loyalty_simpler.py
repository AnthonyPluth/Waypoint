import sqlalchemy as sa
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    loyalty_ids = sa.table('loyalty_ids', sa.column('kind', sa.Text()), sa.column('expiry', sa.Text()))
    op.execute(loyalty_ids.update().where(loyalty_ids.c.kind.in_(['airline', 'hotel', 'car'])).values(expiry=None))
    op.drop_column('loyalty_ids', 'tier')


def downgrade() -> None:
    op.add_column('loyalty_ids', sa.Column('tier', sa.Text()))
