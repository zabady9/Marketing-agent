from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class MemoryEntry(Base):
    """Global, project-independent memory notes — not scoped to any user (there
    is no auth/user system; this app is single-tenant) or any project. Every
    chat across every project reads the full list and injects it into its
    system prompt."""

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # "agent_extracted" | "user_added" — kept as a plain string, same rationale
    # as ChatMessage.role: adding a new source later is a data-only change.
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
