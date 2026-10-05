"""The flight status cache: the last live answer for a flight number on a local departure date.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'flight_status',
        sa.Column('flight_number', sa.Text(), primary_key=True),
        sa.Column('date', sa.Text(), primary_key=True),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('origin', sa.Text()),
        sa.Column('destination', sa.Text()),
        sa.Column('dep_scheduled', sa.Text()),
        sa.Column('dep_estimated', sa.Text()),
        sa.Column('dep_actual', sa.Text()),
        sa.Column('dep_zone', sa.Text()),
        sa.Column('dep_terminal', sa.Text()),
        sa.Column('dep_gate', sa.Text()),
        sa.Column('arr_scheduled', sa.Text()),
        sa.Column('arr_estimated', sa.Text()),
        sa.Column('arr_actual', sa.Text()),
        sa.Column('arr_zone', sa.Text()),
        sa.Column('arr_terminal', sa.Text()),
        sa.Column('arr_gate', sa.Text()),
        sa.Column('fetched_at', sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('flight_status')
