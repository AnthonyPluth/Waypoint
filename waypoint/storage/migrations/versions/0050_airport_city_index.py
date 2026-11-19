import sqlalchemy as sa
from alembic import op

revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_airports_city_lower', 'airports', [sa.text('lower(city)')])


def downgrade() -> None:
    op.drop_index('ix_airports_city_lower', table_name='airports')
