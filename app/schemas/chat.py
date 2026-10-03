from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.artifact import ArtifactSummary
from app.schemas.attachment import AttachmentSummary
from app.schemas.chart import ChartSpec


class ChatMessageCreate(BaseModel):
    content: str = ""
    # ChatAttachment ids, uploaded and processed beforehand through the
    # .../attachments routes. A message may be attachments alone.
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _require_content_or_attachments(self) -> "ChatMessageCreate":
        if not self.content.strip() and not self.attachment_ids:
            raise ValueError("A message needs text or at least one attachment.")
        return self


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
    attachments: list[AttachmentSummary] = Field(default_factory=list)
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
