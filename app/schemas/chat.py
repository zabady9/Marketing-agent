from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.artifact import ArtifactSummary
from app.schemas.chart import ChartSpec


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    tool_name: str | None
    study_id: str | None
    # Both previously missing from this response schema despite existing on
    # the ORM model and being expected by the frontend's ChatMessageRecord —
    # without them, a chart/artifact card is only ever seen live via its SSE
    # event and doesn't survive a GET .../messages reload.
    chart_data: ChartSpec | None = None
    artifact_data: ArtifactSummary | None = Field(None, validation_alias="artifact")
    status: str
    created_at: datetime
    deleted_at: datetime | None


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
