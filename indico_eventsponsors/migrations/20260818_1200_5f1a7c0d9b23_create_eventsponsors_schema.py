"""Create eventsponsors schema

Revision ID: 5f1a7c0d9b23
Revises:
Create Date: 2026-08-18 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.ddl import CreateSchema, DropSchema


# revision identifiers, used by Alembic.
revision = '5f1a7c0d9b23'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(CreateSchema('plugin_eventsponsors'))
    op.create_table(
        'sponsor_tiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False, index=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.CheckConstraint('size > 0', name='positive_size'),
        sa.ForeignKeyConstraint(['event_id'], ['events.events.id']),
        sa.UniqueConstraint('event_id', 'name'),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )
    op.create_table(
        'sponsor_logos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False, index=True),
        sa.Column('storage_backend', sa.String(), nullable=False),
        sa.Column('storage_file_id', sa.String(), nullable=False),
        sa.Column('content_type', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('md5', sa.String(), nullable=False),
        sa.Column('created_dt', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.events.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )
    op.create_table(
        'sponsors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False, index=True),
        sa.Column('tier_id', sa.Integer(), nullable=True, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('tagline', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('homepage_url', sa.String(), nullable=False),
        sa.Column('campaign_url', sa.String(), nullable=False),
        sa.Column('use_campaign_url', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('logo_id', sa.Integer(), nullable=True),
        sa.Column('square_logo_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['event_id'], ['events.events.id']),
        sa.ForeignKeyConstraint(['tier_id'], ['plugin_eventsponsors.sponsor_tiers.id']),
        sa.ForeignKeyConstraint(['logo_id'], ['plugin_eventsponsors.sponsor_logos.id']),
        sa.ForeignKeyConstraint(['square_logo_id'], ['plugin_eventsponsors.sponsor_logos.id']),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )
    op.create_table(
        'sponsor_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False, index=True),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('layout', sa.String(), nullable=False),
        sa.Column('max_logo_pct', sa.Integer(), nullable=False),
        sa.Column('for_app', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.events.id']),
        sa.UniqueConstraint('event_id', 'slug'),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )
    op.create_table(
        'sponsor_template_tiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False, index=True),
        sa.Column('tier_id', sa.Integer(), nullable=False, index=True),
        sa.Column('show_logo', sa.Boolean(), nullable=False),
        sa.Column('show_square_logo', sa.Boolean(), nullable=False),
        sa.Column('show_name', sa.Boolean(), nullable=False),
        sa.Column('show_tagline', sa.Boolean(), nullable=False),
        sa.Column('show_description', sa.Boolean(), nullable=False),
        sa.Column('linked', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['plugin_eventsponsors.sponsor_templates.id']),
        sa.ForeignKeyConstraint(['tier_id'], ['plugin_eventsponsors.sponsor_tiers.id']),
        sa.UniqueConstraint('template_id', 'tier_id'),
        sa.PrimaryKeyConstraint('id'),
        schema='plugin_eventsponsors',
    )


def downgrade():
    op.drop_table('sponsor_template_tiers', schema='plugin_eventsponsors')
    op.drop_table('sponsor_templates', schema='plugin_eventsponsors')
    op.drop_table('sponsors', schema='plugin_eventsponsors')
    op.drop_table('sponsor_logos', schema='plugin_eventsponsors')
    op.drop_table('sponsor_tiers', schema='plugin_eventsponsors')
    op.execute(DropSchema('plugin_eventsponsors'))
