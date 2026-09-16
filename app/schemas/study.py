from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StudyResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    study_type: str
    requested_phase: str | None
    title: str | None
    sections: dict
    verdict: str | None
    confidence_score: float | None
    qc_summary: dict | None
    fatal_agent_failures: list[str]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
