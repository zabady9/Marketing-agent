from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActionLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    actor: str
    action: str
    payload: dict
    result: dict | None
    created_at: str | datetime
