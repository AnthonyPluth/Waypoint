import sqlalchemy as sa
from alembic import op


revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_devices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('owner_sub', sa.Text(), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('environment', sa.Text(), nullable=False),
    sa.Column('created', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token', name='uq_app_devices_token'),
    info={'doc': "iPhones a member turned notifications on for in the app; each ends when its owner can no longer sign in, and doesn't travel in a backup"}
    )
    with op.batch_alter_table('app_devices', schema=None) as batch_op:
        batch_op.create_index('ix_app_devices_owner', ['owner_sub'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('app_devices', schema=None) as batch_op:
        batch_op.drop_index('ix_app_devices_owner')

    op.drop_table('app_devices')
