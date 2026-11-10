import sqlalchemy as sa
from alembic import op

revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('segment_codes') as batch:
        batch.add_column(sa.Column('opened_by', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_segment_codes_opened_by', 'stored_messages', ['opened_by'], ['id'], ondelete='SET NULL', initially='IMMEDIATE', deferrable=True)


def downgrade() -> None:
    with op.batch_alter_table('segment_codes') as batch:
        batch.drop_constraint('fk_segment_codes_opened_by', type_='foreignkey')
        batch.drop_column('opened_by')
