"""
Pure-Python financial calculation tool.

Every public function returns a dict that becomes a CalcTrace payload.
The LangChain StructuredTool wrapper is at the bottom of this file.
NO LLM involvement here — all math is deterministic.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Input schemas (used by LangChain with_structured_output / StructuredTool)
# ──────────────────────────────────────────────────────────────────────────────

class BreakEvenInput(BaseModel):
    fixed_costs: float = Field(..., description="Total fixed costs (Capex + monthly Opex × horizon)")
    unit_price: float = Field(..., description="Revenue per unit / transaction / subscription")
    variable_cost_per_unit: float = Field(0.0, description="Variable cost per unit (default 0 for pure SaaS)")
    monthly_unit_sales: float = Field(..., description="Expected monthly unit sales / subscribers")


class ROIInput(BaseModel):
    total_investment: float = Field(..., description="Total capital invested")
    net_profit: float = Field(..., description="Net profit over the period")


class NPVInput(BaseModel):
    initial_investment: float = Field(..., description="Initial cash outflow (positive number)")
    annual_cash_flows: list[float] = Field(..., description="Cash flow for each year")
    discount_rate: float = Field(0.10, description="Annual discount rate as a decimal (e.g. 0.10 = 10%)")


class SensitivityInput(BaseModel):
    fixed_costs: float
    unit_price: float
    variable_cost_per_unit: float = 0.0
    monthly_unit_sales: float
    revenue_multipliers: list[float] = Field(
        default=[0.7, 1.0, 1.3],
        description="Revenue multipliers for pessimistic, base, optimistic scenarios",
    )


class CashFlowInput(BaseModel):
    monthly_revenue: float = Field(..., description="Monthly revenue (price × units)")
    monthly_opex: float = Field(..., description="Monthly operating expenses")
    capex: float = Field(..., description="One-time capital expenditure (month 0)")
    horizon_months: int = Field(..., description="Projection horizon in months")


class CostStructureInput(BaseModel):
    capex: float = Field(..., description="One-time capital expenditure")
    opex_monthly: float = Field(..., description="Monthly operating expenses")
    horizon_months: int = Field(..., description="Analysis horizon in months")


# ──────────────────────────────────────────────────────────────────────────────
# Pure calculation functions
# ──────────────────────────────────────────────────────────────────────────────

def calculate_break_even(inp: BreakEvenInput) -> dict[str, Any]:
    """
    Break-even in months using contribution margin.

    break_even_units = fixed_costs / (price - variable_cost)
    break_even_months = break_even_units / monthly_unit_sales
    """
    contribution_margin = inp.unit_price - inp.variable_cost_per_unit
    if contribution_margin <= 0:
        raise ValueError(
            f"Unit price ({inp.unit_price}) must exceed variable cost "
            f"({inp.variable_cost_per_unit}) to reach break-even."
        )
    if inp.monthly_unit_sales <= 0:
        raise ValueError("monthly_unit_sales must be positive.")

    # ceil: you can't sell a fractional unit, and floor would leave costs uncovered.
    break_even_units = math.ceil(inp.fixed_costs / contribution_margin)
    break_even_months = round(break_even_units / inp.monthly_unit_sales, 2)

    return {
        "break_even_units": break_even_units,
        "break_even_months": break_even_months,
        "contribution_margin_per_unit": round(contribution_margin, 2),
        "monthly_revenue_at_break_even": round(inp.monthly_unit_sales * inp.unit_price, 2),
    }


def calculate_roi(inp: ROIInput) -> dict[str, Any]:
    """ROI = net_profit / total_investment."""
    if inp.total_investment <= 0:
        raise ValueError("total_investment must be positive.")

    roi = inp.net_profit / inp.total_investment
    return {
        "roi": round(roi, 4),
        "roi_percent": round(roi * 100, 2),
        "net_profit": round(inp.net_profit, 2),
        "total_investment": round(inp.total_investment, 2),
    }


def calculate_npv(inp: NPVInput) -> dict[str, Any]:
    """Net Present Value discounted at the given annual rate."""
    if inp.discount_rate < 0:
        raise ValueError("discount_rate must be non-negative.")

    pv_cash_flows: list[float] = []
    for year, cf in enumerate(inp.annual_cash_flows, start=1):
        pv = cf / ((1 + inp.discount_rate) ** year)
        pv_cash_flows.append(round(pv, 2))

    npv = sum(pv_cash_flows) - inp.initial_investment

    return {
        "npv": round(npv, 2),
        "pv_cash_flows": pv_cash_flows,
        "initial_investment": round(inp.initial_investment, 2),
        "discount_rate": inp.discount_rate,
        "is_positive": npv > 0,
    }


def run_sensitivity_analysis(inp: SensitivityInput) -> dict[str, Any]:
    """
    Run break-even for each revenue multiplier scenario.
    Returns pessimistic / base / optimistic results.
    """
    labels = ["pessimistic", "base", "optimistic"]
    scenarios: dict[str, Any] = {}

    for label, multiplier in zip(labels, inp.revenue_multipliers):
        adjusted_sales = inp.monthly_unit_sales * multiplier
        be_input = BreakEvenInput(
            fixed_costs=inp.fixed_costs,
            unit_price=inp.unit_price,
            variable_cost_per_unit=inp.variable_cost_per_unit,
            monthly_unit_sales=adjusted_sales,
        )
        result = calculate_break_even(be_input)
        scenarios[label] = {
            "revenue_multiplier": multiplier,
            "monthly_unit_sales": round(adjusted_sales, 2),
            **result,
        }

    return {"scenarios": scenarios}


def project_cash_flow(inp: CashFlowInput) -> dict[str, Any]:
    """
    Monthly cash-flow projection.
    Month 0 is the capex outflow; months 1-N are (revenue - opex).
    Returns cumulative cash position per month.
    """
    monthly_net = inp.monthly_revenue - inp.monthly_opex
    cash_position: list[float] = [-inp.capex]  # month 0: capex outflow

    for _ in range(inp.horizon_months):
        cash_position.append(round(cash_position[-1] + monthly_net, 2))

    # Find payback month (first month cumulative ≥ 0 after month 0)
    payback_month: int | None = None
    for month, position in enumerate(cash_position):
        if month > 0 and position >= 0:
            payback_month = month
            break

    return {
        "monthly_net_cash_flow": round(monthly_net, 2),
        "cash_position_by_month": cash_position,
        "payback_month": payback_month,
        "final_position": cash_position[-1],
        "horizon_months": inp.horizon_months,
    }


def calculate_cost_structure(inp: CostStructureInput) -> dict[str, Any]:
    """
    Cost structure over the analysis horizon: one-time Capex vs. cumulative
    Opex (monthly Opex × horizon months).
    """
    cumulative_opex = round(inp.opex_monthly * inp.horizon_months, 2)
    return {
        "capex": round(inp.capex, 2),
        "cumulative_opex": cumulative_opex,
        "total_cost": round(inp.capex + cumulative_opex, 2),
        "horizon_months": inp.horizon_months,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Methodology text — one plain-language sentence per function, keyed by name.
# Deterministic and static (no LLM), so it's correct by construction: it's a
# direct restatement of the formula each function actually runs above. Consumed
# by app/agents/financial.py::_emit_calc to populate CalcTrace.methodology.
# ──────────────────────────────────────────────────────────────────────────────

CALC_METHODOLOGY: dict[str, str] = {
    "calculate_break_even": (
        "Break-even units = fixed costs ÷ (unit price − variable cost per unit); "
        "break-even months = break-even units ÷ expected monthly unit sales."
    ),
    "calculate_roi": (
        "ROI % = net profit ÷ total investment × 100, using capex as the "
        "investment and (monthly revenue − monthly opex) × 12 × years − capex "
        "as net profit."
    ),
    "calculate_npv": (
        "NPV = Σ (annual cash flow ÷ (1 + discount rate)^year) − initial "
        "investment, at a 10% annual discount rate."
    ),
    "run_sensitivity_analysis": (
        "Break-even recomputed at 0.7×, 1.0×, 1.3× base monthly sales to model "
        "pessimistic / base / optimistic demand scenarios."
    ),
    "project_cash_flow": (
        "Cumulative cash position by month = −capex at month 0, then + "
        "(monthly revenue − monthly opex) each subsequent month."
    ),
    "calculate_cost_structure": (
        "Cumulative Opex = monthly Opex × horizon months; shown alongside "
        "one-time Capex to compare cost structure."
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# LangChain StructuredTool registry
# (imported by FinancialModelingAgent in Phase 3)
# ──────────────────────────────────────────────────────────────────────────────

def get_financial_tools():
    """Return LangChain StructuredTools wrapping the pure-math functions."""
    from langchain_core.tools import StructuredTool

    # LangChain's StructuredTool.from_function unpacks the args_schema fields as
    # individual kwargs and passes them to func(**kwargs). Our pure functions expect
    # a single Pydantic model instance, so each tool wraps via a lambda that
    # constructs the model from the unpacked kwargs.
    return [
        StructuredTool.from_function(
            func=lambda **kw: calculate_break_even(BreakEvenInput(**kw)),
            name="calculate_break_even",
            description=(
                "Calculate break-even point in months and units. "
                "Requires: fixed_costs, unit_price, monthly_unit_sales. "
                "Optional: variable_cost_per_unit (default 0)."
            ),
            args_schema=BreakEvenInput,
        ),
        StructuredTool.from_function(
            func=lambda **kw: calculate_roi(ROIInput(**kw)),
            name="calculate_roi",
            description="Calculate ROI from total investment and net profit.",
            args_schema=ROIInput,
        ),
        StructuredTool.from_function(
            func=lambda **kw: calculate_npv(NPVInput(**kw)),
            name="calculate_npv",
            description=(
                "Calculate Net Present Value given initial investment, "
                "annual cash flows, and discount rate."
            ),
            args_schema=NPVInput,
        ),
        StructuredTool.from_function(
            func=lambda **kw: run_sensitivity_analysis(SensitivityInput(**kw)),
            name="run_sensitivity_analysis",
            description=(
                "Run break-even sensitivity analysis across pessimistic/base/optimistic "
                "revenue scenarios."
            ),
            args_schema=SensitivityInput,
        ),
        StructuredTool.from_function(
            func=lambda **kw: project_cash_flow(CashFlowInput(**kw)),
            name="project_cash_flow",
            description=(
                "Project monthly cash flow over a horizon. "
                "Returns cumulative cash position per month and payback month."
            ),
            args_schema=CashFlowInput,
        ),
        StructuredTool.from_function(
            func=lambda **kw: calculate_cost_structure(CostStructureInput(**kw)),
            name="calculate_cost_structure",
            description=(
                "Compare one-time Capex against cumulative Opex over the "
                "analysis horizon."
            ),
            args_schema=CostStructureInput,
        ),
    ]
