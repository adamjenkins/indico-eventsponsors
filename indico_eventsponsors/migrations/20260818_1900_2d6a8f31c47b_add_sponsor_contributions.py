"""Add sponsor/contribution associations

Revision ID: 2d6a8f31c47b
Revises: 9c3f5a2b71e4
Create Date: 2026-08-18 19:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '2d6a8f31c47b'
down_revision = '9c3f5a2b71e4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'sponsor_contributions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sponsor_id', sa.Integer(), nullable=False, index=True),
        sa.Column('contribution_id', sa.Integer(), nullable=False, index=True),
        # Both sides cascade: a deleted sponsor or a deleted contribution should
        # take the association with it rather than leave a row pointing at
        # nothing.
        sa.ForeignKeyConstraint(['sponsor_id'], ['plugin_eventsponsors.sponsors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contribution_id'], ['events.contributions.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('sponsor_id', 'contribution_id'),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )


def downgrade():
    op.drop_table('sponsor_contributions', schema='plugin_eventsponsors')
