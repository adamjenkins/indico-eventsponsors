"""Add app_above_schedule to sponsor templates

Revision ID: 7b2e4c81d05a
Revises: 5f1a7c0d9b23
Create Date: 2026-08-18 15:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '7b2e4c81d05a'
down_revision = '5f1a7c0d9b23'
branch_labels = None
depends_on = None


def upgrade():
    # server_default so existing rows get a value, then dropped: the column is
    # only ever written by the application, and leaving a default in the schema
    # would hide a future bug where it forgets to.
    op.add_column('sponsor_templates',
                  sa.Column('app_above_schedule', sa.Boolean(), nullable=False, server_default='false'),
                  schema='plugin_eventsponsors')
    op.alter_column('sponsor_templates', 'app_above_schedule', server_default=None,
                    schema='plugin_eventsponsors')


def downgrade():
    op.drop_column('sponsor_templates', 'app_above_schedule', schema='plugin_eventsponsors')
