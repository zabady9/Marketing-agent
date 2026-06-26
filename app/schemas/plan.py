from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanCreateRequest(BaseModel):
    goal: str | None = None


class PostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    day: int
    theme: str
    format: str
    angle: str
    content: str
    hashtags: list[str]
    suggested_time: str
    status: str
    created_at: str | datetime


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    goal: str | None
    status: str
    error: str | None
    posts: list[PostResponse] = []
    created_at: str | datetime
