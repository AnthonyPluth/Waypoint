import sqlalchemy as sa
from alembic import op

revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None

syncs = sa.table('photo_trip_syncs', sa.column('fetch_started', sa.Text()))


def upgrade():
    with op.batch_alter_table('photo_trip_syncs') as batch:
        batch.add_column(sa.Column('resume_after', sa.Text(), nullable=True))
        batch.add_column(sa.Column('inputs', sa.Text(), nullable=True))
        batch.drop_column('resume_page')
    op.execute(syncs.update().values(fetch_started=None))


def downgrade():
    with op.batch_alter_table('photo_trip_syncs') as batch:
        batch.add_column(sa.Column('resume_page', sa.Integer(), nullable=True))
        batch.drop_column('inputs')
        batch.drop_column('resume_after')
    op.execute(syncs.update().values(fetch_started=None))
