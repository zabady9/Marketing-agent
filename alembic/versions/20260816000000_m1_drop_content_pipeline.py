"""M1: Drop content pipeline tables (posts, content_plans) and LangGraph checkpointer tables.

Revision ID: 20260816000000
Revises: 20260805000000
Create Date: 2026-08-16

DESTRUCTIVE — no rollback possible after this migration runs.
Safe because: (a) no production data exists, (b) all code that referenced these
tables has been removed in Increment 1 before this migration runs.

Downgrade is a no-op: tables cannot be recreated without a schema snapshot.
"""
from typing import Union

from alembic import op

revision: str = "20260816000000"
down_revision: Union[str, None] = "20260805000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS posts CASCADE")
    op.execute("DROP TABLE IF EXISTS content_plans CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations CASCADE")


def downgrade() -> None:
    # Cannot recreate dropped tables without a data snapshot.
    # Manual recovery required if rollback is needed.
    pass
