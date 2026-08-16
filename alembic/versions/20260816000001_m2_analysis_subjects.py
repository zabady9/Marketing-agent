"""M2: create analysis_subjects, drop brand_profiles, add chat_message_id FK, seed visitor workspace

Revision ID: 20260816000001
Revises: 20260816000000
Create Date: 2026-08-16
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260816000001"
down_revision: Union[str, None] = "20260816000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_subjects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("subject_name", sa.String(), nullable=True),
        sa.Column("legal_name", sa.String(), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=True),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("business_lines", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tracked_competitors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("subject_description", sa.Text(), nullable=True),
        sa.Column("areas_of_interest", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "setup_status",
            sa.Enum("in_progress", "pending_review", "active", native_enum=False),
            nullable=False,
            server_default="in_progress",
        ),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_subjects_workspace_id", "analysis_subjects", ["workspace_id"])

    op.execute("DROP TABLE IF EXISTS brand_profiles CASCADE")

    op.add_column(
        "consulting_analyses",
        sa.Column("chat_message_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_consulting_analyses_chat_message_id",
        "consulting_analyses",
        "chat_messages",
        ["chat_message_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        "INSERT INTO workspaces (id, name, autonomy_level, created_at, updated_at) "
        "VALUES ('visitor', 'Visitor', 'supervised', now(), now()) "
        "ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    pass  # Manual recovery required
