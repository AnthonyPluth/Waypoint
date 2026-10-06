import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_pending',
        sa.Column('state', sa.Text(), primary_key=True),
        sa.Column('nonce', sa.Text()),
        sa.Column('verifier', sa.Text()),
        sa.Column('next', sa.Text()),
        sa.Column('created', sa.Float()),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('token_hash', sa.Text(), primary_key=True),
        sa.Column('sub', sa.Text()),
        sa.Column('email', sa.Text()),
        sa.Column('name', sa.Text()),
        sa.Column('created', sa.Float()),
        sa.Column('expires', sa.Float()),
        sa.Column('id_token', sa.Text()),
    )
    op.create_table(
        'users',
        sa.Column('sub', sa.Text(), primary_key=True),
        sa.Column('email', sa.Text()),
        sa.Column('name', sa.Text()),
        sa.Column('first_name', sa.Text()),
        sa.Column('last_seen', sa.Float()),
    )
    op.create_table(
        'settings',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('value', sa.Text()),
    )


def downgrade() -> None:
    op.drop_table('settings')
    op.drop_table('users')
    op.drop_table('auth_sessions')
    op.drop_table('auth_pending')
