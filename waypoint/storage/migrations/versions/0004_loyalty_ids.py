import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'loyalty_ids',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('person_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('program', sa.Text(), nullable=False),
        sa.Column('number', sa.Text(), nullable=False),
        sa.Column('tier', sa.Text()),
        sa.Column('expiry', sa.Text()),
        sa.Column('notes', sa.Text()),
        sa.ForeignKeyConstraint(['person_id'], ['people.id'], name='fk_loyalty_ids_person_id', ondelete='CASCADE',
                                deferrable=True, initially='IMMEDIATE'),
    )
    op.create_index('ix_loyalty_ids_person_id', 'loyalty_ids', ['person_id'])


def downgrade() -> None:
    op.drop_index('ix_loyalty_ids_person_id', table_name='loyalty_ids')
    op.drop_table('loyalty_ids')
