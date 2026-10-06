import sqlalchemy as sa
from alembic import op

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'segment_ports',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment_id', sa.Integer(), sa.ForeignKey('segments.id', name='fk_segment_ports_segment_id', ondelete='CASCADE',
                                                             deferrable=True, initially='IMMEDIATE'), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('zone', sa.Text(), nullable=False),
        sa.Column('arrive_local', sa.Text()),
        sa.Column('depart_local', sa.Text()),
    )
    op.create_index('ix_segment_ports_segment_id', 'segment_ports', ['segment_id'])


def downgrade() -> None:
    op.drop_index('ix_segment_ports_segment_id', table_name='segment_ports')
    op.drop_table('segment_ports')
