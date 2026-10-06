"""Where each brand logo came from (`brand_logos.source`): Logo.dev, or Wikidata and Commons for a hotel's own brand. A logo from
before is Logo.dev's, and every brand is asked about again (`checked` cleared) so a hotel brand that got its parent's logo from
Logo.dev gets one of its own, or none. A cache, so nothing else changes.

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('brand_logos', sa.Column('source', sa.Text()))
    brand_logos = sa.table('brand_logos', sa.column('logo', sa.LargeBinary()), sa.column('source', sa.Text()), sa.column('checked', sa.Text()))
    op.execute(brand_logos.update().where(brand_logos.c.logo.is_not(None)).values(source='logodev'))
    op.execute(brand_logos.update().values(checked=None))


def downgrade() -> None:
    op.drop_column('brand_logos', 'source')
