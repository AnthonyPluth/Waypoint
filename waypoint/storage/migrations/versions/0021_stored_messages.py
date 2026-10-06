import sqlalchemy as sa
from alembic import op

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stored_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mailbox_id', sa.Integer(), sa.ForeignKey('mailboxes.id', name='fk_stored_messages_mailbox_id', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.Column('message_id', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('subject', sa.Text()),
        sa.Column('created', sa.Float(), nullable=False),
        sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_stored_messages_mailbox_message'),
    )
    op.create_table(
        'segment_messages',
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('segments.id', name='fk_segment_messages_segment_id', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE'), primary_key=True),
        sa.Column('stored_message_id', sa.Integer(), sa.ForeignKey('stored_messages.id', name='fk_segment_messages_stored_message_id', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE'), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('segment_messages')
    op.drop_table('stored_messages')
