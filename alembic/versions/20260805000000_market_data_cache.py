"""Add market_data_cache table for competitor metric caching.

Revision ID: 20260805000000
Revises: 20260726000000
Create Date: 2026-08-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805000000"
down_revision: Union[str, None] = "20260726000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_data_cache",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("competitor_name", sa.String(), nullable=False),
        sa.Column("metric_type", sa.String(), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_title", sa.String(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "ttl_hours",
            sa.Integer(),
            nullable=False,
            server_default="168",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "competitor_name", "metric_type",
            name="uq_market_data_cache",
        ),
    )
    op.create_index(
        "ix_market_data_cache_workspace_id",
        "market_data_cache",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_data_cache_workspace_id", table_name="market_data_cache")
    op.drop_table("market_data_cache")
