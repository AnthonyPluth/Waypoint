import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'push_devices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_sub', sa.Text(), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh', sa.Text(), nullable=False),
        sa.Column('auth', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.UniqueConstraint('endpoint', name='uq_push_devices_endpoint'),
    )
    op.create_index('ix_push_devices_owner', 'push_devices', ['owner_sub'])
    op.create_table(
        'reminder_prefs',
        sa.Column('owner_sub', sa.Text(), primary_key=True),
        sa.Column('check_in', sa.Boolean(), nullable=False),
        sa.Column('day_of', sa.Boolean(), nullable=False),
    )
    op.create_table(
        'reminders_sent',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('owner_sub', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('ref', sa.Text(), nullable=False),
        sa.Column('sent', sa.Float(), nullable=False),
        sa.UniqueConstraint('owner_sub', 'kind', 'ref', name='uq_reminders_sent_owner_kind_ref'),
    )
    op.create_table(
        'calendar_feeds',
        sa.Column('owner_sub', sa.Text(), primary_key=True),
        sa.Column('key_hash', sa.Text(), nullable=False),
        sa.Column('created', sa.Float(), nullable=False),
        sa.UniqueConstraint('key_hash', name='uq_calendar_feeds_key_hash'),
    )


def downgrade() -> None:
    op.drop_table('calendar_feeds')
    op.drop_table('reminders_sent')
    op.drop_table('reminder_prefs')
    op.drop_index('ix_push_devices_owner', table_name='push_devices')
    op.drop_table('push_devices')
