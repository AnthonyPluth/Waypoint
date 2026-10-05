"""AI assistants over MCP with OAuth: the apps registered to connect, each approval (grant), and their codes and tokens.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def _fk(table: str, column: str, target: str) -> sa.ForeignKey:
    return sa.ForeignKey(target, name=f'fk_{table}_{column}', ondelete='CASCADE', deferrable=True, initially='IMMEDIATE')


def upgrade() -> None:
    op.create_table('oauth_clients',
                    sa.Column('id', sa.Text(), nullable=False),
                    sa.Column('name', sa.Text()),
                    sa.Column('redirect_uris', sa.Text(), nullable=False),
                    sa.Column('auth_method', sa.Text(), nullable=False),
                    sa.Column('secret_hash', sa.Text()),
                    sa.Column('kind', sa.Text(), nullable=False, server_default=sa.text("'dcr'")),
                    sa.Column('metadata_url', sa.Text()),
                    sa.Column('created', sa.Float(), nullable=False),
                    sa.Column('last_used', sa.Float()),
                    sa.PrimaryKeyConstraint('id'))
    op.create_table('oauth_grants',
                    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
                    sa.Column('client_id', sa.Text(), _fk('oauth_grants', 'client_id', 'oauth_clients.id'), nullable=False),
                    sa.Column('sub', sa.Text()),
                    sa.Column('email', sa.Text()),
                    sa.Column('scope', sa.Text(), nullable=False),
                    sa.Column('resource', sa.Text(), nullable=False),
                    sa.Column('created', sa.Float(), nullable=False),
                    sa.Column('last_used', sa.Float()),
                    sa.Column('revoked', sa.Float()),
                    sa.Column('revoked_reason', sa.Text()),
                    sa.PrimaryKeyConstraint('id'),
                    sqlite_autoincrement=True)
    op.create_index('ix_oauth_grants_client_id', 'oauth_grants', ['client_id'], unique=False)
    op.create_table('oauth_codes',
                    sa.Column('code_hash', sa.Text(), nullable=False),
                    sa.Column('client_id', sa.Text(), _fk('oauth_codes', 'client_id', 'oauth_clients.id'), nullable=False),
                    sa.Column('grant_id', sa.Integer(), _fk('oauth_codes', 'grant_id', 'oauth_grants.id'), nullable=False),
                    sa.Column('redirect_uri', sa.Text(), nullable=False),
                    sa.Column('code_challenge', sa.Text(), nullable=False),
                    sa.Column('resource', sa.Text(), nullable=False),
                    sa.Column('created', sa.Float(), nullable=False),
                    sa.Column('used', sa.Float()),
                    sa.PrimaryKeyConstraint('code_hash'))
    op.create_index('ix_oauth_codes_grant_id', 'oauth_codes', ['grant_id'], unique=False)
    op.create_table('oauth_tokens',
                    sa.Column('token_hash', sa.Text(), nullable=False),
                    sa.Column('kind', sa.Text(), nullable=False),
                    sa.Column('grant_id', sa.Integer(), _fk('oauth_tokens', 'grant_id', 'oauth_grants.id'), nullable=False),
                    sa.Column('created', sa.Float(), nullable=False),
                    sa.Column('expires', sa.Float(), nullable=False),
                    sa.Column('consumed', sa.Float()),
                    sa.Column('replaced_by', sa.Text()),
                    sa.PrimaryKeyConstraint('token_hash'))
    op.create_index('ix_oauth_tokens_grant_id', 'oauth_tokens', ['grant_id'], unique=False)
    op.create_table('oauth_consents',
                    sa.Column('token_hash', sa.Text(), nullable=False),
                    sa.Column('params', sa.Text(), nullable=False),
                    sa.Column('created', sa.Float(), nullable=False),
                    sa.PrimaryKeyConstraint('token_hash'))


def downgrade() -> None:
    op.drop_table('oauth_consents')
    op.drop_index('ix_oauth_tokens_grant_id', table_name='oauth_tokens')
    op.drop_table('oauth_tokens')
    op.drop_index('ix_oauth_codes_grant_id', table_name='oauth_codes')
    op.drop_table('oauth_codes')
    op.drop_index('ix_oauth_grants_client_id', table_name='oauth_grants')
    op.drop_table('oauth_grants')
    op.drop_table('oauth_clients')
