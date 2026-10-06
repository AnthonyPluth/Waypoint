import sqlalchemy as sa
from alembic import op

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'brand_logos',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('logo', sa.LargeBinary()),
        sa.Column('logo_type', sa.Text()),
        sa.Column('checked', sa.Text()),
    )


def downgrade() -> None:
    op.drop_table('brand_logos')
