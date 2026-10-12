import sqlalchemy as sa
from alembic import op

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('ai_day', sa.Text()))
    op.add_column('mailboxes', sa.Column('ai_day_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('review_items', sa.Column('auto_state', sa.Text()))
    op.add_column('review_items', sa.Column('auto_tries', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('review_items', 'auto_tries')
    op.drop_column('review_items', 'auto_state')
    op.drop_column('mailboxes', 'ai_day_count')
    op.drop_column('mailboxes', 'ai_day')
