import sqlalchemy as sa
from alembic import op

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None

OVER = ('landed', 'cancelled', 'diverted')


def upgrade() -> None:
    op.create_table('flight_checks',
    sa.Column('flight_number', sa.Text(), nullable=False),
    sa.Column('date', sa.Text(), nullable=False),
    sa.Column('checked_at', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('flight_number', 'date'),
    )
    status = sa.table('flight_status', sa.column('flight_number'), sa.column('date'), sa.column('state'),
                      sa.column('fetched_at', sa.Float()), sa.column('attempted_at', sa.Float()))
    checks = sa.table('flight_checks', sa.column('flight_number'), sa.column('date'), sa.column('checked_at', sa.Float()))
    last = sa.case((sa.func.coalesce(status.c.attempted_at, 0) > status.c.fetched_at, status.c.attempted_at), else_=status.c.fetched_at)
    op.execute(checks.insert().from_select(
        ['flight_number', 'date', 'checked_at'],
        sa.select(status.c.flight_number, status.c.date, last).where(
            status.c.state.not_in(OVER), sa.or_(status.c.fetched_at > 0, sa.func.coalesce(status.c.attempted_at, 0) > 0))))
    op.execute(status.delete().where(status.c.state.not_in(OVER)))
    with op.batch_alter_table('flight_status') as batch:
        batch.drop_column('attempted_at')


def downgrade() -> None:
    with op.batch_alter_table('flight_status') as batch:
        batch.add_column(sa.Column('attempted_at', sa.Float(), nullable=True))
    op.drop_table('flight_checks')
