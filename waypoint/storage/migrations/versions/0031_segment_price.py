import sqlalchemy as sa
from alembic import op

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('segments', sa.Column('price_minor', sa.Integer()))
    op.add_column('segments', sa.Column('price_currency', sa.Text()))
    op.add_column('segments', sa.Column('price_source', sa.Text()))


def downgrade() -> None:
    op.drop_column('segments', 'price_source')
    op.drop_column('segments', 'price_currency')
    op.drop_column('segments', 'price_minor')
