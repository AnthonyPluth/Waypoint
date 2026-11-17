import sqlalchemy as sa
from alembic import op

revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None

settings = sa.table('settings', sa.column('key', sa.String()), sa.column('value', sa.Text()))
LEGACY = ('ai_mode', 'ai_openrouter_model', 'ai_openrouter_key', 'ai_auto')


def upgrade() -> None:
    conn = op.get_bind()
    mode = conn.execute(sa.select(settings.c.value).where(settings.c.key == 'ai_mode')).scalar()
    if mode != 'local':
        conn.execute(sa.delete(settings).where(settings.c.key.in_(('ai_ollama_url', 'ai_ollama_model'))))
    conn.execute(sa.delete(settings).where(settings.c.key.in_(LEGACY)))


def downgrade() -> None:
    pass
