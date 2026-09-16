from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class StudyResult(Base):
    """One row per feasibility-study run. A project may have many, one per
    run_feasibility_study_tool invocation; rows are never overwritten."""

    __tablename__ = "study_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    # "full" (the whole pipeline) or "single_phase" (just one section, via
    # run_pipeline_phase_tool / run_single_phase_study) — lets callers (e.g.
    # the study-context digest injected into chat) distinguish a deliberate
    # partial run from a complete study rather than just checking whether
    # `sections` is non-empty. `requested_phase` names which phase for a
    # single_phase row; always None for a full run.
    study_type: Mapped[str] = mapped_column(String(16), nullable=False, default="full", server_default="full")
    requested_phase: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # LLM-generated, content-specific title (e.g. "Competitive Landscape:
    # 5 Direct Rivals in the US Meal-Kit Market") — see
    # app.services.study_title.generate_study_title. Null when generation
    # failed/timed out (fell back to a deterministic label instead, computed
    # client-side — see frontend's getStudyTitle) or for a run that never
    # reached "completed".
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)

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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="study_results")
