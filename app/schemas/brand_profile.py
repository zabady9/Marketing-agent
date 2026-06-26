from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BrandProfileUpsert(BaseModel):
    name: str
    audience: str
    tone: str
    language: str
    avoid: list[str] = []
    extra: dict = {}


class BrandProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    audience: str
    tone: str
    language: str
    avoid: list[str]
    extra: dict
    created_at: str | datetime
    updated_at: str | datetime
