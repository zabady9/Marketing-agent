from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import AutonomyLevel


class WorkspaceCreate(BaseModel):
    name: str
    autonomy_level: AutonomyLevel = AutonomyLevel.supervised


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    autonomy_level: str
    created_at: str | datetime
