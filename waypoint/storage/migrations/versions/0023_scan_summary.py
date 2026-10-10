import sqlalchemy as sa
from alembic import op

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('mailboxes') as batch:
        batch.add_column(sa.Column('scan_summary', sa.Text()))


def downgrade() -> None:
    with op.batch_alter_table('mailboxes') as batch:
        batch.drop_column('scan_summary')
