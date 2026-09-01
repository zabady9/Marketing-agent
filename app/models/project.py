from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    business_profile: Mapped["BusinessProfile"] = relationship(
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    study_results: Mapped[list["StudyResult"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="StudyResult.created_at.desc()",
    )
    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )
