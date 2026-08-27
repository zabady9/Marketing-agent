from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    created_at: datetime


class ProjectDetail(ProjectSummary):
    archived_at: datetime | None
    updated_at: datetime


class ProjectCreateResponse(BaseModel):
    project_id: str


class SourcedValue(BaseModel):
    value: object
    source: str
    low_confidence: bool = False


class BusinessProfileResponse(BaseModel):
    project_id: str
    raw_user_input: str
    detected_language: str
    output_language: str

    business_description: SourcedValue
    target_market_description: SourcedValue
    target_market_geography: SourcedValue
    business_model_type: SourcedValue
    capex: SourcedValue
    capex_currency: str
    opex_monthly: SourcedValue
    opex_monthly_currency: str
    pricing_unit_price: SourcedValue
    pricing_currency: str
    pricing_model: SourcedValue
    expected_monthly_sales: SourcedValue
    competitors: list[dict]
    team_size: SourcedValue | None
    analysis_horizon_years: int

    created_at: datetime
    updated_at: datetime


class BusinessProfileUpdate(BaseModel):
    """Direct field edits — no re-extraction (see plan's V1 scoping).

    Any field present here (even if None isn't allowed, see below) is treated as
    user-provided: its value column is overwritten and its paired *_source column
    (where one exists) is flipped to 'user_provided', clearing low_confidence.
    Fields are optional-and-omittable (PATCH semantics) — omit a field to leave it
    untouched. There is intentionally no way to PATCH a field back to null.
    """

    business_description: str | None = None
    target_market_description: str | None = None
    target_market_geography: str | None = None
    business_model_type: str | None = None
    capex_amount: float | None = None
    capex_currency: str | None = None
    opex_monthly_amount: float | None = None
    opex_monthly_currency: str | None = None
    pricing_unit_price: float | None = None
    pricing_currency: str | None = None
    pricing_model: str | None = None
    expected_monthly_sales: float | None = None
    competitors: list[str] | None = None
    team_size: int | None = None
    analysis_horizon_years: int | None = None
