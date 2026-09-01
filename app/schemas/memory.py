from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemoryEntryCreate(BaseModel):
    content: str = Field(..., min_length=1)


class MemoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
