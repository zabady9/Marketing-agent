from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Derived server-side from the session's first user message once it's sent
    # (see app.services.chat.maybe_set_title) — null until then.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # "user" | "assistant" | "tool" — kept as a plain string rather than a DB enum
    # so adding a role later (e.g. "system") is a data-only change, no migration.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Set when role == "tool" (or an assistant turn that invoked one) — e.g.
    # "run_feasibility_study". Null for plain user/assistant text turns.
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set only on the tool row for a successful run_feasibility_study_tool call —
    # lets chat history reconstruction link a historical card to the specific
    # study it came from. ON DELETE SET NULL: a study deleted independently of
    # its project clears the reference instead of leaving a dangling id.
    study_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("study_results.id", ondelete="SET NULL"), nullable=True
    )
    # "pending" (row created, no tokens yet) | "streaming" (partial content
    # written) | "complete" (terminal) | "error" (terminal, turn failed).
    # user/tool rows are always "complete" immediately — only assistant rows
    # pass through the other states while a turn is in flight, which is what
    # lets a client reconnect mid-generation (after a refresh) and find
    # whatever text has been generated so far. See app.services.chat_agent.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="complete")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Bumped on every incremental content/status write while a generation is
    # in flight — the stuck-generation sweep (app.main) uses this, not
    # created_at, to tell "still legitimately streaming/running a long tool
    # call" apart from "orphaned by a server crash".
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
