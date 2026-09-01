"""study results history and chat message study link

Revision ID: bb1e9084512c
Revises: dec34c97004c
Create Date: 2026-08-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb1e9084512c'
down_revision: Union[str, Sequence[str], None] = 'dec34c97004c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # study_results.project_id was UNIQUE (one row per project); a project can
    # now have many study runs, so drop it. SQLite backs an unnamed
    # UniqueConstraint with an anonymous autoindex (sqlite_autoindex_...), which
    # batch mode can't address directly by that name — supplying a
    # naming_convention makes Alembic assign the constraint a deterministic
    # name at reflection time that drop_constraint can then match.
    naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table(
        'study_results', recreate='always', naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint('uq_study_results_project_id', type_='unique')

    # chat_messages.study_id links a "run_feasibility_study_tool" tool message
    # to the specific study it created, so historical chat cards can link to
    # that exact run rather than "whichever one is current". SQLite can't add a
    # column with an inline FK via plain ADD COLUMN, so this also needs batch
    # mode.
    with op.batch_alter_table('chat_messages', recreate='always') as batch_op:
        batch_op.add_column(
            sa.Column(
                'study_id',
                sa.String(length=36),
                sa.ForeignKey(
                    'study_results.id',
                    ondelete='SET NULL',
                    name='fk_chat_messages_study_id',
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('chat_messages', recreate='always') as batch_op:
        batch_op.drop_column('study_id')

    with op.batch_alter_table('study_results', recreate='always') as batch_op:
        batch_op.create_unique_constraint('uq_study_results_project_id', ['project_id'])
