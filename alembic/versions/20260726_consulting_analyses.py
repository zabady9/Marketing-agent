"""consulting analyses table

Revision ID: 20260726000000
Revises: 20260704000000
Create Date: 2026-07-26

Adds:
- consulting_analyses table for SWOT/PESTEL/feasibility reports with citations
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726000000"
down_revision: Union[str, None] = "20260704000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "consulting_analyses",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("analysis_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="generating"),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consulting_analyses_workspace_id", "consulting_analyses", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_consulting_analyses_workspace_id", table_name="consulting_analyses")
    op.drop_table("consulting_analyses")
