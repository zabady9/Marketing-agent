from __future__ import annotations

from pydantic import BaseModel


class ChatExportRequest(BaseModel):
    """study_ids optionally grounds the synthesis in specific studies'
    section data, in addition to the conversation itself."""

    study_ids: list[str] | None = None
