import sqlalchemy as sa
from alembic import op

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('review_items', sa.Column('reference', sa.Text()))
    with op.batch_alter_table('scanned_messages') as batch:
        batch.add_column(sa.Column('segment_id', sa.Integer()))
        batch.create_foreign_key('fk_scanned_messages_segment_id', 'segments', ['segment_id'], ['id'], ondelete='SET NULL',
                                 deferrable=True, initially='IMMEDIATE')


def downgrade() -> None:
    with op.batch_alter_table('scanned_messages') as batch:
        batch.drop_constraint('fk_scanned_messages_segment_id', type_='foreignkey')
        batch.drop_column('segment_id')
    with op.batch_alter_table('review_items') as batch:
        batch.drop_column('reference')
