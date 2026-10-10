import sqlalchemy as sa
from alembic import op

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('scan_summary', sa.Text()))


def downgrade() -> None:
    op.drop_column('mailboxes', 'scan_summary')
