from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AttachmentCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=1000)
    content_type: str = Field("", max_length=255)
    size_bytes: int = Field(..., ge=0)


class AttachmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    kind: str | None
    error: str | None
    created_at: datetime


class UploadTarget(BaseModel):
    url: str
    method: str
    headers: dict[str, str]


class AttachmentCreateResponse(BaseModel):
    attachment: AttachmentSummary
    upload: UploadTarget
