"""add soft delete columns

Revision ID: 16068391211c
Revises: bb1e9084512c
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16068391211c'
down_revision: Union[str, Sequence[str], None] = 'bb1e9084512c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # projects.archived_at was reserved but never used by any endpoint — rename
    # it in place rather than adding a second, redundant nullable timestamp.
    with op.batch_alter_table('projects') as batch_op:
        batch_op.alter_column('archived_at', new_column_name='deleted_at')

    with op.batch_alter_table('business_profiles') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('study_results') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('chat_sessions') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('memory_entries') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))

    with op.batch_alter_table('glossary_cache') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('glossary_cache') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('memory_entries') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('chat_sessions') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('study_results') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('business_profiles') as batch_op:
        batch_op.drop_column('deleted_at')

    with op.batch_alter_table('projects') as batch_op:
        batch_op.alter_column('deleted_at', new_column_name='archived_at')
