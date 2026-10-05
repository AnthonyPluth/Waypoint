"""A member who claims a guest ("This is me"): the guests they were linked from, and whether they turned the suggestion down.

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('people', sa.Column('links', sa.Text()))
    op.add_column('people', sa.Column('claim_dismissed', sa.Boolean()))


def downgrade() -> None:
    with op.batch_alter_table('people') as batch:
        batch.drop_column('claim_dismissed')
        batch.drop_column('links')
