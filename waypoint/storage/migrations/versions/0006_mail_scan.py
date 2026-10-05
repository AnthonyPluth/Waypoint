"""Scanning mail: what each scan has looked at (ids only), the "Couldn't read" review queue, the senders a person stopped
reviewing, and what a mailbox's last scan couldn't do.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=f'fk_{table}_{column}', ondelete=ondelete,
                                   deferrable=True, initially='IMMEDIATE')


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('scan_error', sa.Text()))
    op.create_table(
        'scanned_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mailbox_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Text(), nullable=False),
        sa.Column('outcome', sa.Text(), nullable=False),
        sa.Column('scanned', sa.Float(), nullable=False),
        sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_scanned_messages_mailbox_message'),
        _fk('scanned_messages', 'mailbox_id', 'mailboxes.id', 'CASCADE'),
    )
    op.create_table(
        'review_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mailbox_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.Text(), nullable=False),
        sa.Column('sender_domain', sa.Text(), nullable=False),
        sa.Column('received', sa.Text()),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.UniqueConstraint('mailbox_id', 'message_id', name='uq_review_items_mailbox_message'),
        _fk('review_items', 'mailbox_id', 'mailboxes.id', 'CASCADE'),
    )
    op.create_table(
        'ignored_senders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mailbox_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.Text(), nullable=False),
        sa.UniqueConstraint('mailbox_id', 'domain', name='uq_ignored_senders_mailbox_domain'),
        _fk('ignored_senders', 'mailbox_id', 'mailboxes.id', 'CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('ignored_senders')
    op.drop_table('review_items')
    op.drop_table('scanned_messages')
    with op.batch_alter_table('mailboxes') as batch:
        batch.drop_column('scan_error')
