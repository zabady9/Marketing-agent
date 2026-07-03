from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductItem(BaseModel):
    name: str
    description: str
    price_point: str | None = None


class AudienceSegment(BaseModel):
    name: str
    description: str
    pain_points: list[str] = []
    channels: list[str] = []


class BrandProfileUpsert(BaseModel):
    """All fields are optional to support partial/step-by-step onboarding updates."""
    company_name: str | None = None
    brand_name: str | None = None
    industry: str | None = None
    products: list[ProductItem] | None = None
    audience_segments: list[AudienceSegment] | None = None
    tone: str | None = None
    voice_guidelines: str | None = None
    positioning: str | None = None
    goals: list[str] | None = None
    avoid: list[str] | None = None
    extra: dict | None = None
    onboarding_status: str | None = None


class BrandProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    company_name: str | None
    brand_name: str | None
    industry: str | None
    products: list
    audience_segments: list
    tone: str | None
    voice_guidelines: str | None
    positioning: str | None
    goals: list
    avoid: list
    extra: dict
    onboarding_status: str
    created_at: str | datetime
    updated_at: str | datetime
