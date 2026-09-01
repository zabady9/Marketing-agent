from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db import Base


class BusinessProfile(Base):
    __tablename__ = "business_profiles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Persisted equivalent of app.schemas.intake.FeasibilityInput
    raw_user_input: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[str] = mapped_column(String(16), nullable=False)
    output_language: Mapped[str] = mapped_column(String(16), nullable=False)

    business_description: Mapped[str] = mapped_column(Text, nullable=False)
    business_description_source: Mapped[str] = mapped_column(String(16), nullable=False)

    problem_statement: Mapped[str] = mapped_column(Text, nullable=False, default="")
    problem_statement_source: Mapped[str] = mapped_column(String(16), nullable=False)

    unique_value_proposition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unique_value_proposition_source: Mapped[str] = mapped_column(String(16), nullable=False)

    target_market_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_market_description_source: Mapped[str] = mapped_column(String(16), nullable=False)

    target_market_geography: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_market_geography_source: Mapped[str] = mapped_column(String(16), nullable=False)

    # Loose string ("B2C" | "B2B" | ""), consistent with business_model_type — no DB enum
    target_market_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    target_market_type_source: Mapped[str] = mapped_column(String(16), nullable=False)

    business_model_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_model_type_source: Mapped[str] = mapped_column(String(16), nullable=False)

    capex_amount: Mapped[float] = mapped_column(Float, nullable=False)
    capex_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    capex_source: Mapped[str] = mapped_column(String(16), nullable=False)
    capex_low_confidence: Mapped[bool] = mapped_column(default=False)

    funding_source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    funding_source_source: Mapped[str] = mapped_column(String(16), nullable=False)

    opex_monthly_amount: Mapped[float] = mapped_column(Float, nullable=False)
    opex_monthly_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    opex_monthly_source: Mapped[str] = mapped_column(String(16), nullable=False)
    opex_monthly_low_confidence: Mapped[bool] = mapped_column(default=False)

    pricing_unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    pricing_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    pricing_source: Mapped[str] = mapped_column(String(16), nullable=False)

    pricing_model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pricing_model_source: Mapped[str] = mapped_column(String(16), nullable=False)

    expected_monthly_sales: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_monthly_sales_source: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_monthly_sales_low_confidence: Mapped[bool] = mapped_column(default=False)

    # [{"name": str, "source": "user_provided" | "estimated"}, ...]
    competitors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    founder_risks: Mapped[str] = mapped_column(Text, nullable=False, default="")
    founder_risks_source: Mapped[str] = mapped_column(String(16), nullable=False)

    team_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_size_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    key_roles_needed: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    key_roles_needed_source: Mapped[str] = mapped_column(String(16), nullable=False)

    marketing_channels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    marketing_channels_source: Mapped[str] = mapped_column(String(16), nullable=False)

    study_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    study_goal_source: Mapped[str] = mapped_column(String(16), nullable=False)

    analysis_horizon_years: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # Only ever set as a side effect of its parent Project being soft-deleted —
    # this row has no independent lifecycle in the UI.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="business_profile")
