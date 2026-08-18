"""Add inline to sponsor template tiers

Revision ID: 9c3f5a2b71e4
Revises: 7b2e4c81d05a
Create Date: 2026-08-18 17:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '9c3f5a2b71e4'
down_revision = '7b2e4c81d05a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sponsor_template_tiers',
                  sa.Column('inline', sa.Boolean(), nullable=False, server_default='false'),
                  schema='plugin_eventsponsors')
    op.alter_column('sponsor_template_tiers', 'inline', server_default=None,
                    schema='plugin_eventsponsors')


def downgrade():
    op.drop_column('sponsor_template_tiers', 'inline', schema='plugin_eventsponsors')
