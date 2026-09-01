from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base


class GlossaryCache(Base):
    """Localized jargon-term definitions (TAM, SAM, ROI, ...), one row per
    output language. The English definitions are static and hand-authored
    (see app/services/glossary.py::GLOSSARY_TERMS) — this table only caches
    their translation into non-English languages, computed once per language
    on first use rather than re-translated on every study run."""

    __tablename__ = "glossary_cache"

    # BCP-47 base code, lowercased (e.g. "ar", "fr") — see is_rtl()'s same
    # normalization in app/tools/language.py. One row per language.
    language: Mapped[str] = mapped_column(String(10), primary_key=True)
    # {"TAM": "...", "SAM": "...", ...} — same 17 keys as GLOSSARY_TERMS,
    # values translated into `language`.
    terms: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Soft-deleting a language forces get_or_create_glossary to retranslate and
    # update this row in place on next use (the PK is the language itself, so a
    # deleted row can't just be superseded by a fresh insert).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
