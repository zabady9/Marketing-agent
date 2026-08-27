"""add wizard fields to business_profiles

Revision ID: f420720297bd
Revises: b26fbd327780
Create Date: 2026-08-19 17:50:15.332290

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f420720297bd'
down_revision: Union[str, Sequence[str], None] = 'b26fbd327780'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    All 16 columns are NOT NULL, so every value column needs a server_default
    to backfill existing rows (SQLite populates them at ADD COLUMN time — no
    separate data migration needed). *_source columns backfill to 'estimated'
    (Source.ESTIMATED) rather than 'user_provided': existing rows never had a
    human fill these fields in through the wizard, so "estimated/unknown" is
    the correct provenance, matching how e.g. target_market_description
    defaults to ESTIMATED whenever nothing was explicitly supplied.
    """
    op.add_column('business_profiles', sa.Column('problem_statement', sa.Text(), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('problem_statement_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('unique_value_proposition', sa.Text(), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('unique_value_proposition_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('target_market_type', sa.String(length=16), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('target_market_type_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('funding_source', sa.Text(), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('funding_source_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('founder_risks', sa.Text(), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('founder_risks_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('key_roles_needed', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('business_profiles', sa.Column('key_roles_needed_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('marketing_channels', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('business_profiles', sa.Column('marketing_channels_source', sa.String(length=16), nullable=False, server_default='estimated'))
    op.add_column('business_profiles', sa.Column('study_goal', sa.Text(), nullable=False, server_default=''))
    op.add_column('business_profiles', sa.Column('study_goal_source', sa.String(length=16), nullable=False, server_default='estimated'))


def downgrade() -> None:
    """Downgrade schema.

    Note: native DROP COLUMN requires SQLite >= 3.35 (2021).
    """
    op.drop_column('business_profiles', 'study_goal_source')
    op.drop_column('business_profiles', 'study_goal')
    op.drop_column('business_profiles', 'marketing_channels_source')
    op.drop_column('business_profiles', 'marketing_channels')
    op.drop_column('business_profiles', 'key_roles_needed_source')
    op.drop_column('business_profiles', 'key_roles_needed')
    op.drop_column('business_profiles', 'founder_risks_source')
    op.drop_column('business_profiles', 'founder_risks')
    op.drop_column('business_profiles', 'funding_source_source')
    op.drop_column('business_profiles', 'funding_source')
    op.drop_column('business_profiles', 'target_market_type_source')
    op.drop_column('business_profiles', 'target_market_type')
    op.drop_column('business_profiles', 'unique_value_proposition_source')
    op.drop_column('business_profiles', 'unique_value_proposition')
    op.drop_column('business_profiles', 'problem_statement_source')
    op.drop_column('business_profiles', 'problem_statement')
    # ### end Alembic commands ###
