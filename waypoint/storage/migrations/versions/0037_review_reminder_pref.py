import sqlalchemy as sa
from alembic import op

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reminder_prefs') as batch:
        batch.add_column(sa.Column('review', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table('reminder_prefs') as batch:
        batch.drop_column('review')
