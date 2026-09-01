from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from app.schemas.project import ProjectDetail

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ProjectAdminUpdate(BaseModel):
    name: str | None = None
    status: str | None = None


class ProjectAdminResponse(ProjectDetail):
    # Live counts of this project's non-deleted children — lets the admin UI
    # show accurate cascade-impact text before a delete, without a separate
    # round trip per child collection.
    active_study_count: int
    active_chat_session_count: int


class StudyResultAdminCreate(BaseModel):
    project_id: str
    status: str = "pending"
    sections: dict = {}
    verdict: str | None = None
    confidence_score: float | None = None
    qc_summary: dict | None = None
    fatal_agent_failures: list[str] = []
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StudyResultAdminUpdate(BaseModel):
    """PATCH semantics (exclude_unset) — same convention as
    BusinessProfileUpdate: omit a field to leave it untouched."""

    status: str | None = None
    sections: dict | None = None
    verdict: str | None = None
    confidence_score: float | None = None
    qc_summary: dict | None = None
    fatal_agent_failures: list[str] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ChatSessionAdminUpdate(BaseModel):
    title: str | None = None


class ChatMessageAdminUpdate(BaseModel):
    content: str | None = None
    role: str | None = None
    tool_name: str | None = None
    study_id: str | None = None


class MemoryEntryAdminUpdate(BaseModel):
    content: str | None = None
    source: str | None = None


class GlossaryCacheResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    language: str
    terms: dict[str, str]
    created_at: datetime
    deleted_at: datetime | None


class GlossaryCacheAdminUpdate(BaseModel):
    terms: dict[str, str]
