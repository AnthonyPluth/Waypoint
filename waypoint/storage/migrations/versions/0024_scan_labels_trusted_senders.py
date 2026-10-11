import sqlalchemy as sa
from alembic import op

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [target], name=f'fk_{table}_{column}', ondelete=ondelete,
                                   deferrable=True, initially='IMMEDIATE')


def upgrade() -> None:
    op.add_column('mailboxes', sa.Column('scan_labels', sa.Text()))
    op.create_table(
        'trusted_senders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mailbox_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.Text(), nullable=False),
        sa.UniqueConstraint('mailbox_id', 'domain', name='uq_trusted_senders_mailbox_domain'),
        _fk('trusted_senders', 'mailbox_id', 'mailboxes.id', 'CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('trusted_senders')
    op.drop_column('mailboxes', 'scan_labels')
