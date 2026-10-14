import sqlalchemy as sa
from alembic import op

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade() -> None:
    settings = sa.table('settings', sa.column('key', sa.Text()))
    op.execute(settings.delete().where(settings.c.key.in_(('logodev_token', 'logodev_secret', 'logodev_last_error'))))


def downgrade() -> None:
    pass
