from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import ClaimType


class LocalizedText(BaseModel):
    text: str
    language: str  # BCP-47


class CalcTrace(BaseModel):
    """Proof that a financial figure came from the financial_calc tool, not LLM text."""

    tool: Literal["financial_calc"] = "financial_calc"
    fn: str                          # function name, e.g. "calculate_break_even"
    inputs: dict[str, Any]
    output: dict[str, Any]
    # "low" when any input field carried low_confidence=True (e.g. estimated capex)
    input_confidence: Literal["high", "low"] = "high"
    # One-sentence plain-language explanation of the formula. Populated from a
    # static lookup keyed by `fn` (app/tools/financial_calc.py::CALC_METHODOLOGY);
    # empty until that lookup is wired in.
    methodology: str = ""


class CalculatedFigure(BaseModel):
    """A single numeric output that must carry a CalcTrace."""

    value: Any
    currency: str | None = None
    source: Literal["calculated"] = "calculated"
    calculation_trace: CalcTrace
    # Propagated from CalcTrace for quick frontend access
    input_confidence: Literal["high", "low"] = "high"
    # Always calculated_estimate — a CalculatedFigure only ever exists because
    # deterministic Python math (not the LLM) produced it.
    claim_type: ClaimType = ClaimType.CALCULATED_ESTIMATE


class FinancialModelOutput(BaseModel):
    """Full output of FinancialModelingAgent — passed to downstream agents."""

    study_id: str
    output_language: str

    # Pass-through of source inputs so downstream agents have full context
    capex_value: float | None
    capex_currency: str
    capex_source: str          # "user_provided" | "estimated"
    opex_monthly_value: float | None
    opex_monthly_currency: str
    opex_monthly_source: str
    unit_price: float
    pricing_currency: str
    expected_monthly_sales: float | None
    expected_monthly_sales_source: str
    analysis_horizon_years: int

    # Calculated figures — every one has a CalcTrace
    break_even: CalculatedFigure
    roi_year_1: CalculatedFigure
    roi_year_n: CalculatedFigure   # n = analysis_horizon_years
    npv: CalculatedFigure
    sensitivity: CalculatedFigure  # value = {scenarios: {...}}
    cash_flow: CalculatedFigure    # value = {cash_position_by_month: [...], payback_month: ...}
    cost_structure: CalculatedFigure  # value = {capex, cumulative_opex, total_cost, horizon_months}

    narrative: LocalizedText
    review_recommended: bool = False   # True when any input_confidence == "low"

    # Legend for fields whose classification never varies per-run — lets the
    # frontend render a "why is this labeled X" legend without per-field logic.
    claim_types: dict[str, ClaimType] = {
        "capex_value": ClaimType.ASSUMPTION,
        "opex_monthly_value": ClaimType.ASSUMPTION,
        "unit_price": ClaimType.ASSUMPTION,
        "expected_monthly_sales": ClaimType.ASSUMPTION,
        "narrative": ClaimType.OPINION,
    }
