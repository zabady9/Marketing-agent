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
    problem_statement: SourcedValue
    unique_value_proposition: SourcedValue
    target_market_description: SourcedValue
    target_market_geography: SourcedValue
    target_market_type: SourcedValue
    business_model_type: SourcedValue
    capex: SourcedValue
    capex_currency: str
    funding_source: SourcedValue
    opex_monthly: SourcedValue
    opex_monthly_currency: str
    pricing_unit_price: SourcedValue
    pricing_currency: str
    pricing_model: SourcedValue
    expected_monthly_sales: SourcedValue
    competitors: list[dict]
    founder_risks: SourcedValue
    team_size: SourcedValue | None
    key_roles_needed: SourcedValue
    marketing_channels: SourcedValue
    study_goal: SourcedValue
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
    problem_statement: str | None = None
    unique_value_proposition: str | None = None
    target_market_description: str | None = None
    target_market_geography: str | None = None
    target_market_type: str | None = None
    business_model_type: str | None = None
    capex_amount: float | None = None
    capex_currency: str | None = None
    funding_source: str | None = None
    opex_monthly_amount: float | None = None
    opex_monthly_currency: str | None = None
    pricing_unit_price: float | None = None
    pricing_currency: str | None = None
    pricing_model: str | None = None
    expected_monthly_sales: float | None = None
    competitors: list[str] | None = None
    founder_risks: str | None = None
    team_size: int | None = None
    key_roles_needed: list[str] | None = None
    marketing_channels: list[str] | None = None
    study_goal: str | None = None
    analysis_horizon_years: int | None = None
