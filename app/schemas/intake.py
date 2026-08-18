from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Source(StrEnum):
    USER_PROVIDED = "user_provided"
    ESTIMATED = "estimated"


class FieldWithSource(BaseModel):
    value: Any
    source: Source = Source.USER_PROVIDED
    low_confidence: bool = False


class StudyStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IntakeExtraction(BaseModel):
    """Structured output the LLM fills from the user's free-form input."""

    business_description: str = Field(
        ..., description="Clear restatement of the business idea"
    )
    target_market_description: str | None = Field(
        None, description="Target customer segment"
    )
    target_market_geography: str | None = Field(
        None, description="Geographic target market (country / region)"
    )
    business_model_type: str | None = Field(
        None, description="e.g. SaaS, marketplace, D2C, B2B service, retail"
    )

    capex_amount: float | None = Field(
        None, description="One-time capital expenditure amount (number only)"
    )
    capex_currency: str = Field("USD", description="ISO-4217 currency code for capex")
    opex_monthly_amount: float | None = Field(
        None, description="Monthly operating cost (number only)"
    )
    opex_monthly_currency: str = Field(
        "USD", description="ISO-4217 currency code for opex"
    )

    pricing_unit_price: float | None = Field(
        None,
        description=(
            "Price per unit / subscription / transaction. "
            "CRITICAL — set to null only if truly absent."
        ),
    )
    pricing_currency: str = Field("USD", description="ISO-4217 currency code for pricing")
    pricing_model: str | None = Field(
        None, description="subscription | one-time | usage-based | freemium | etc."
    )

    expected_monthly_sales: float | None = Field(
        None,
        description=(
            "Expected monthly unit sales / subscribers / transactions in year 1. "
            "Extract if the user mentions customer counts, subscriber targets, "
            "or daily/weekly/monthly sales volumes."
        ),
    )

    competitors: list[str] = Field(
        default_factory=list, description="Competitor names explicitly mentioned"
    )
    team_size: int | None = Field(None, description="Current or planned team headcount")
    analysis_horizon_years: int = Field(3, description="Projection horizon in years")

    # Validation metadata — the LLM sets these; Python validation acts on them
    missing_critical_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Names of critically missing fields. Include 'pricing_unit_price' "
            "if the user provided no price at all."
        ),
    )
    soft_missing_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Fields that can be estimated via web research: "
            "'capex', 'opex_monthly', 'expected_monthly_sales', 'competitors', 'team_size'"
        ),
    )


class FeasibilityStartRequest(BaseModel):
    raw_user_input: str = Field(..., min_length=20)
    output_language: str | None = Field(
        None,
        description=(
            "Override auto-detected language. "
            "BCP-47 code (e.g. 'en', 'ar'). Null = use detected language."
        ),
    )
    analysis_horizon_years: int = Field(3, ge=1, le=10)
    # Optional pre-filled structured overrides (take precedence over LLM extraction)
    pricing_unit_price: float | None = None
    pricing_currency: str = "USD"
    capex_amount: float | None = None
    opex_monthly_amount: float | None = None


class FeasibilityStartResponse(BaseModel):
    study_id: str
    status: StudyStatus = StudyStatus.PENDING


class FeasibilityInput(BaseModel):
    """Fully validated input passed between pipeline agents."""

    study_id: str
    raw_user_input: str
    detected_language: str
    output_language: str

    business_description: FieldWithSource
    target_market_description: FieldWithSource
    target_market_geography: FieldWithSource
    business_model_type: FieldWithSource

    capex: FieldWithSource           # value: float, currency stored in metadata
    capex_currency: str
    opex_monthly: FieldWithSource    # value: float
    opex_monthly_currency: str

    pricing_unit_price: FieldWithSource   # always user_provided (hard-required)
    pricing_currency: str
    pricing_model: FieldWithSource

    expected_monthly_sales: FieldWithSource  # value: float | None; low_confidence when estimated

    competitors: list[dict]          # [{name, source}]
    team_size: FieldWithSource | None
    analysis_horizon_years: int
