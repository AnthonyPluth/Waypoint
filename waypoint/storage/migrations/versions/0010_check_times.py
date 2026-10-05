"""Segments read from an email whose times were marked UTC but may mean the place's own clock, and couldn't be settled from the
message's text, are flagged so their card can ask for a look.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('segments', sa.Column('check_times', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('segments') as batch:
        batch.drop_column('check_times')
