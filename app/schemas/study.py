from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StudyResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    status: str
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
