"""add artifacts table

Revision ID: 2f64df5ca8d0
Revises: 143bc8909ee1
Create Date: 2026-09-18 15:38:09.318261

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f64df5ca8d0'
down_revision: Union[str, Sequence[str], None] = '143bc8909ee1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'artifacts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('format', sa.String(length=8), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('storage_path', sa.String(length=500), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('spec_json', sa.JSON(), nullable=False),
        sa.Column('parent_artifact_id', sa.String(length=36), nullable=True),
        # func.now() (not text('now()')) — dialect-aware, matching every
        # other table's created_at (see app/models/*.py): compiles to
        # CURRENT_TIMESTAMP on SQLite, now() on Postgres. A raw text('now()')
        # only works on Postgres and breaks every SQLite install (dev
        # default) with "unknown function: now()" the moment a row is
        # actually inserted — DDL alone doesn't surface it.
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_artifact_id'], ['artifacts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    # batch_alter_table: SQLite can't ALTER a constraint onto an existing
    # table directly (only Postgres/etc. support that) — batch mode falls
    # back to its copy-and-move recreate strategy there while still emitting
    # plain ALTER statements on backends that support them.
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.add_column(sa.Column('artifact_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            'fk_chat_messages_artifact_id_artifacts',
            'artifacts',
            ['artifact_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_constraint('fk_chat_messages_artifact_id_artifacts', type_='foreignkey')
        batch_op.drop_column('artifact_id')
    op.drop_table('artifacts')
