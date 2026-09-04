"""add chat message status and updated_at

Revision ID: d09dbe9c80ba
Revises: 16068391211c
Create Date: 2026-09-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd09dbe9c80ba'
down_revision: Union[str, Sequence[str], None] = '16068391211c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite rejects ADD COLUMN with a non-constant default (CURRENT_TIMESTAMP)
    # outside of CREATE TABLE — batch mode works around this by rebuilding the
    # table, matching the pattern used in 16068391211c.
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.add_column(
            sa.Column('status', sa.String(length=16), nullable=False, server_default='complete')
        )
        batch_op.add_column(
            sa.Column(
                'updated_at',
                sa.DateTime(),
                server_default=sa.text('CURRENT_TIMESTAMP'),
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('status')
