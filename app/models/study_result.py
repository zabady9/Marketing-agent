from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class StudyResult(Base):
    """The latest feasibility-study run for a project. V1 is intentionally a
    single row per project, overwritten in place on every new run — see the
    plan doc's "StudyResult overwrite behavior" note: no run history is kept."""

    __tablename__ = "study_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    # {"market_overview": {...}, "competitive_landscape": {...},
    #  "financial_feasibility": {...}, "risk_assessment": {...},
    #  "executive_summary": {...}} — only sections that completed are present.
    sections: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qc_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fatal_agent_failures: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="study_result")
