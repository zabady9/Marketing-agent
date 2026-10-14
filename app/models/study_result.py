from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class StudyResult(Base):
    """One row per analysis run (see app.analysis.engine). Every analysis —
    a feasibility study, a SWOT, or a plain question — has the same shape:
    `report` holds the plan and each step's blocks, and is rewritten after
    every step so a run in progress can be viewed. Rows are never overwritten."""

    __tablename__ = "study_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    # pending -> running -> completed | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # What the user wanted to learn, as passed to run_analysis_tool.
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # {language, title, goal, rationale, frameworks, key_questions,
    #  method_sources, steps: [{id, title, objective, status, summary, blocks}],
    #  answer, findings, recommendations, sources} — see app.analysis.engine.
    report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="study_results")
