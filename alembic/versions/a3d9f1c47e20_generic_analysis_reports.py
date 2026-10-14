"""generic analysis reports: replace feasibility sections with a step/block report

Every analysis now has the same shape (app.analysis.engine): `goal` plus a
`report` JSON of steps and blocks. The old feasibility-specific columns are
dropped, and existing study rows are DELETED (they can't be rendered by the
new report). The glossary cache, used only by the old pipeline, is dropped.

Revision ID: a3d9f1c47e20
Revises: 7c1e4a9b2d30
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3d9f1c47e20'
down_revision: Union[str, Sequence[str], None] = '7c1e4a9b2d30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_COLUMNS = (
    'study_type',
    'requested_phase',
    'sections',
    'verdict',
    'confidence_score',
    'qc_summary',
    'fatal_agent_failures',
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(sa.text("UPDATE chat_messages SET study_id = NULL WHERE study_id IS NOT NULL"))
    op.execute(sa.text("DELETE FROM study_results"))

    with op.batch_alter_table('study_results') as batch:
        for name in _OLD_COLUMNS:
            batch.drop_column(name)
        batch.add_column(sa.Column('goal', sa.Text(), nullable=True))
        batch.add_column(sa.Column('report', sa.JSON(), nullable=False, server_default='{}'))

    op.drop_table('glossary_cache')


def downgrade() -> None:
    """Downgrade schema. Deleted study rows are not restored."""
    op.create_table(
        'glossary_cache',
        sa.Column('language', sa.String(length=10), nullable=False),
        sa.Column('terms', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('language'),
    )
    op.execute(sa.text("DELETE FROM study_results"))
    with op.batch_alter_table('study_results') as batch:
        batch.drop_column('report')
        batch.drop_column('goal')
        batch.add_column(sa.Column('study_type', sa.String(length=16), nullable=False, server_default='full'))
        batch.add_column(sa.Column('requested_phase', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('sections', sa.JSON(), nullable=False, server_default='{}'))
        batch.add_column(sa.Column('verdict', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('confidence_score', sa.Float(), nullable=True))
        batch.add_column(sa.Column('qc_summary', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('fatal_agent_failures', sa.JSON(), nullable=False, server_default='[]'))
