import sqlalchemy as sa
from alembic import op

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('segments') as batch:
        batch.add_column(sa.Column('email_updated', sa.Float(), nullable=True))
        batch.add_column(sa.Column('email_update', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('segments', recreate='never') as batch:
        batch.drop_column('email_update')
        batch.drop_column('email_updated')
