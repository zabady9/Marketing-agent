import uuid

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConsultingAnalysis(Base):
    __tablename__ = "consulting_analyses"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="generating")
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(server_default=func.now())
    updated_at: Mapped[str] = mapped_column(server_default=func.now(), onupdate=func.now())
