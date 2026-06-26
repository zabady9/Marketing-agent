import uuid

from sqlalchemy import Index, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_action_logs_workspace_id", "workspace_id"),)
