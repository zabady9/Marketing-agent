from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class ChatAttachment(Base):
    """A user-uploaded file of any type attached to a chat message. The bytes
    never pass through this backend in production — the browser PUTs them
    straight to GCS via a signed URL (Cloud Run caps request bodies at 32MB,
    and uploads go up to settings.max_upload_bytes) — so a row is created
    first (status="pending_upload"), then processed once the client reports
    the upload complete. message_id stays null until the attachment is sent
    with a message, which is what lets an unsent attachment be deleted."""

    __tablename__ = "chat_attachments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    # BigInteger: a 2GB upload overflows a 32-bit Integer on Postgres.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # GCS object name (upload_storage="gcs") or local filesystem path ("local").
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # "pending_upload" | "processing" | "ready" | "failed". A failed
    # attachment can still be sent — the agent is just told its metadata.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_upload")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How the agent sees this file — set by attachment_processing:
    # "gemini_file" (multimodal part via the Gemini File API) | "text"
    # (extracted_text) | "metadata_only" (name/type/size only).
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Gemini File API uploads expire after 48h — chat_agent re-uploads from
    # storage_path when an older session's history is replayed past that.
    gemini_file_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gemini_file_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
