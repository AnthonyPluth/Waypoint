"""A mailbox's owner can share its "Couldn't read" items with the household (`mailboxes.share_review`): off for every mailbox
there already is, so nothing is shown to anyone who couldn't see it before.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('share_review', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('mailboxes', 'share_review')   # (not a batch: rebuilding mailboxes would take its review items with it, by their cascade)
