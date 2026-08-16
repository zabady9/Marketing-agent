import uuid

from sqlalchemy import ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalysisSubject(Base):
    __tablename__ = "analysis_subjects"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_name: Mapped[str | None] = mapped_column(String, nullable=True)
    legal_name: Mapped[str | None] = mapped_column(String, nullable=True)
    subject_type: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    business_lines: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tracked_competitors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    subject_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    areas_of_interest: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    setup_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="in_progress"
    )
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[str] = mapped_column(server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
