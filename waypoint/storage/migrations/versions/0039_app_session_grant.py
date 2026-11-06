import sqlalchemy as sa
from alembic import op

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch:
        batch.add_column(sa.Column('grant_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_auth_sessions_grant_id', 'oauth_grants', ['grant_id'], ['id'], ondelete='CASCADE', initially='IMMEDIATE', deferrable=True)


def downgrade() -> None:
    with op.batch_alter_table('auth_sessions') as batch:
        batch.drop_constraint('fk_auth_sessions_grant_id', type_='foreignkey')
        batch.drop_column('grant_id')
