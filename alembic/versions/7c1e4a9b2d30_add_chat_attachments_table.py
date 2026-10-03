"""add chat_attachments table

Revision ID: 7c1e4a9b2d30
Revises: 2f64df5ca8d0
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1e4a9b2d30'
down_revision: Union[str, Sequence[str], None] = '2f64df5ca8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'chat_attachments',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('message_id', sa.String(length=36), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('storage_path', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=True),
        sa.Column('gemini_file_uri', sa.String(length=500), nullable=True),
        sa.Column('gemini_file_expires_at', sa.DateTime(), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        # func.now(), not text('now()') — see 2f64df5ca8d0 for why.
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_chat_attachments_message_id', 'chat_attachments', ['message_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chat_attachments_message_id', table_name='chat_attachments')
    op.drop_table('chat_attachments')
