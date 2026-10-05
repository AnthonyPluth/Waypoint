"""Gmail connections: a member's mailbox (its refresh token encrypted) and the connections in progress at Google.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mailboxes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_sub', sa.Text(), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('token', sa.Text(), nullable=False),
        sa.Column('history_id', sa.Text()),
        sa.Column('last_scan', sa.Float()),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('last_error', sa.Text()),
        sa.Column('created', sa.Float()),
        sa.UniqueConstraint('owner_sub', 'address', name='uq_mailboxes_owner_address'),
    )
    op.create_table(
        'mailbox_pending',
        sa.Column('state', sa.Text(), primary_key=True),
        sa.Column('owner_sub', sa.Text(), nullable=False),
        sa.Column('verifier', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('mailbox_pending')
    op.drop_table('mailboxes')
