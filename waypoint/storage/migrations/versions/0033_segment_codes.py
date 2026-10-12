import sqlalchemy as sa
from alembic import op

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'segment_codes',
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('segments.id', name='fk_segment_codes_segment_id', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE'), primary_key=True),
        sa.Column('mailbox_id', sa.Integer(), sa.ForeignKey('mailboxes.id', name='fk_segment_codes_mailbox_id', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.Column('content', sa.Text()),
        sa.Column('day', sa.Text()),
        sa.Column('created', sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('segment_codes')
