import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'people',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('first_name', sa.Text()),
        sa.Column('legal_name', sa.Text()),
        sa.Column('aliases', sa.Text()),
        sa.Column('user_sub', sa.Text()),
        sa.ForeignKeyConstraint(['user_sub'], ['users.sub'], name='fk_people_user_sub', ondelete='SET NULL',
                                deferrable=True, initially='IMMEDIATE'),
    )
    op.create_index('ux_people_user_sub', 'people', ['user_sub'], unique=True)
    op.execute(
        "INSERT INTO people (display_name, first_name, user_sub) "
        "SELECT COALESCE(NULLIF(TRIM(name), ''), NULLIF(TRIM(email), ''), sub), first_name, sub FROM users ORDER BY sub")


def downgrade() -> None:
    op.drop_index('ux_people_user_sub', table_name='people')
    op.drop_table('people')
