import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('people', sa.Column('links', sa.Text()))
    op.add_column('people', sa.Column('claim_dismissed', sa.Boolean()))


def downgrade() -> None:
    with op.batch_alter_table('people') as batch:
        batch.drop_column('claim_dismissed')
        batch.drop_column('links')
