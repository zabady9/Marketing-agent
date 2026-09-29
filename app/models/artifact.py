from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class Artifact(Base):
    """A generated DOCX/PPTX/PDF file. Its own table (not a JSON column like
    ChatMessage.chart_data) because it wraps a binary file on disk rather
    than a small inline spec — storage_path/size_bytes describe that file,
    while spec_json keeps the validated outline that produced it so
    revise_artifact_tool can regenerate from an edited version of the same
    spec instead of binary-patching the file."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[str] = mapped_column(String(8), nullable=False)  # "docx" | "pptx" | "pdf"
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # The validated PresentationOutline/DocumentOutline (app.schemas.artifact)
    # that produced this file — lets revise_artifact_tool apply an LLM edit to
    # the outline and regenerate, rather than needing to parse the binary back.
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Set when this artifact is a revision of an earlier one — never
    # overwritten, mirroring StudyResult's per-run history convention.
    parent_artifact_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
