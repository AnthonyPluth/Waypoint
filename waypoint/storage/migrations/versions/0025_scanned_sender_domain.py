import sqlalchemy as sa
from alembic import op

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scanned_messages', sa.Column('sender_domain', sa.Text()))


def downgrade() -> None:
    op.drop_column('scanned_messages', 'sender_domain')
