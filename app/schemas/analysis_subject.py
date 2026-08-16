from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BusinessLine(BaseModel):
    name: str
    description: str
    notes: str | None = None


class TrackedCompetitor(BaseModel):
    name: str
    description: str | None = None
    notes: str | None = None


class AnalysisSubjectUpsert(BaseModel):
    """All fields are optional to support partial/step-by-step setup updates."""
    subject_name: str | None = None
    legal_name: str | None = None
    subject_type: str | None = None
    industry: str | None = None
    business_lines: list[BusinessLine] | None = None
    tracked_competitors: list[TrackedCompetitor] | None = None
    subject_description: str | None = None
    areas_of_interest: list[str] | None = None
    setup_status: str | None = None
    extra: dict | None = None


class AnalysisSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    subject_name: str | None
    legal_name: str | None
    subject_type: str | None
    industry: str | None
    business_lines: list
    tracked_competitors: list
    subject_description: str | None
    areas_of_interest: list
    setup_status: str
    extra: dict
    created_at: str | datetime
    updated_at: str | datetime
