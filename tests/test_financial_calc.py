"""
Unit tests for app/tools/financial_calc.py.

All assertions use exact expected values derived by hand so the test suite
proves the math is correct, not just that the function runs.
No LLM, no network, no async — pure Python.
"""

import pytest

from app.tools.financial_calc import (
    BreakEvenInput,
    CashFlowInput,
    CostStructureInput,
    NPVInput,
    ROIInput,
    SensitivityInput,
    calculate_break_even,
    calculate_cost_structure,
    calculate_npv,
    calculate_roi,
    get_financial_tools,
    project_cash_flow,
    run_sensitivity_analysis,
)


# ──────────────────────────────────────────────────────────────────────────────
# calculate_break_even
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateBreakEven:
    def test_saas_no_variable_cost(self):
        # SaaS: $29/mo price, 0 variable cost, 100 subs/mo, $100k fixed costs
        # exact = 100_000 / 29 = 3448.28 → ceil → 3449 units (3448×29=$99,992 < target)
        # break_even_months = 3449 / 100 = 34.49
        result = calculate_break_even(BreakEvenInput(
            fixed_costs=100_000,
            unit_price=29,
            variable_cost_per_unit=0,
            monthly_unit_sales=100,
        ))
        assert result["break_even_units"] == 3449
        assert result["break_even_months"] == pytest.approx(34.49, rel=1e-3)
        assert result["contribution_margin_per_unit"] == 29.0
        # Verify the ceil is semantically correct: 3449 units covers fixed costs
        assert 3449 * 29 >= 100_000
        assert 3448 * 29 < 100_000

    def test_with_variable_cost(self):
        # price=50, variable=10, margin=40
        # fixed=100_000, break_even_units=2500
        # monthly_sales=100 → break_even_months=25
        result = calculate_break_even(BreakEvenInput(
            fixed_costs=100_000,
            unit_price=50,
            variable_cost_per_unit=10,
            monthly_unit_sales=100,
        ))
        assert result["break_even_units"] == 2500.0
        assert result["break_even_months"] == 25.0
        assert result["contribution_margin_per_unit"] == 40.0

    def test_restaurant_example(self):
        # Egyptian restaurant: 120 EGP/meal, 0 variable (simplified),
        # 500k EGP fixed costs, 200 meals/day * 30 days = 6000/mo
        result = calculate_break_even(BreakEvenInput(
            fixed_costs=500_000,
            unit_price=120,
            variable_cost_per_unit=0,
            monthly_unit_sales=6_000,
        ))
        # break_even_units = 500_000/120 ≈ 4166.67
        # break_even_months = 4166.67/6000 ≈ 0.69
        assert result["break_even_months"] == pytest.approx(0.69, rel=1e-2)

    def test_zero_contribution_margin_raises(self):
        with pytest.raises(ValueError, match="must exceed variable cost"):
            calculate_break_even(BreakEvenInput(
                fixed_costs=100_000,
                unit_price=10,
                variable_cost_per_unit=10,
                monthly_unit_sales=100,
            ))

    def test_negative_margin_raises(self):
        with pytest.raises(ValueError, match="must exceed variable cost"):
            calculate_break_even(BreakEvenInput(
                fixed_costs=100_000,
                unit_price=5,
                variable_cost_per_unit=10,
                monthly_unit_sales=100,
            ))

    def test_zero_monthly_sales_raises(self):
        with pytest.raises(ValueError, match="monthly_unit_sales must be positive"):
            calculate_break_even(BreakEvenInput(
                fixed_costs=100_000,
                unit_price=50,
                monthly_unit_sales=0,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# calculate_roi
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateROI:
    def test_positive_roi(self):
        # invest 100k, profit 15k → ROI = 0.15 = 15%
        result = calculate_roi(ROIInput(total_investment=100_000, net_profit=15_000))
        assert result["roi"] == pytest.approx(0.15)
        assert result["roi_percent"] == pytest.approx(15.0)

    def test_negative_roi(self):
        # invest 100k, loss 20k → ROI = -0.20 = -20%
        result = calculate_roi(ROIInput(total_investment=100_000, net_profit=-20_000))
        assert result["roi"] == pytest.approx(-0.20)
        assert result["roi_percent"] == pytest.approx(-20.0)

    def test_zero_investment_raises(self):
        with pytest.raises(ValueError, match="total_investment must be positive"):
            calculate_roi(ROIInput(total_investment=0, net_profit=10_000))

    def test_3yr_roi(self):
        # 3-year: invest 150k, cumulative net profit 63k → ROI = 0.42
        result = calculate_roi(ROIInput(total_investment=150_000, net_profit=63_000))
        assert result["roi"] == pytest.approx(0.42)
        assert result["roi_percent"] == pytest.approx(42.0)


# ──────────────────────────────────────────────────────────────────────────────
# calculate_npv
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateNPV:
    def test_positive_npv(self):
        # invest 100k, cash flows [30k, 40k, 50k], rate 10%
        # PV1 = 30000/1.1 = 27272.73
        # PV2 = 40000/1.21 = 33057.85
        # PV3 = 50000/1.331 = 37565.74
        # NPV = 27272.73 + 33057.85 + 37565.74 - 100000 = -2103.68
        result = calculate_npv(NPVInput(
            initial_investment=100_000,
            annual_cash_flows=[30_000, 40_000, 50_000],
            discount_rate=0.10,
        ))
        assert result["npv"] == pytest.approx(-2103.68, rel=1e-3)
        assert result["is_positive"] is False
        assert len(result["pv_cash_flows"]) == 3

    def test_zero_discount_rate(self):
        # Rate 0% — NPV is just sum(cash_flows) - investment
        result = calculate_npv(NPVInput(
            initial_investment=100_000,
            annual_cash_flows=[40_000, 40_000, 40_000],
            discount_rate=0.0,
        ))
        assert result["npv"] == pytest.approx(20_000.0)
        assert result["is_positive"] is True

    def test_negative_npv(self):
        result = calculate_npv(NPVInput(
            initial_investment=200_000,
            annual_cash_flows=[10_000, 10_000],
            discount_rate=0.10,
        ))
        assert result["npv"] < 0
        assert result["is_positive"] is False

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError, match="discount_rate must be non-negative"):
            calculate_npv(NPVInput(
                initial_investment=100_000,
                annual_cash_flows=[50_000],
                discount_rate=-0.05,
            ))


# ──────────────────────────────────────────────────────────────────────────────
# run_sensitivity_analysis
# ──────────────────────────────────────────────────────────────────────────────

class TestSensitivityAnalysis:
    def test_three_scenarios(self):
        result = run_sensitivity_analysis(SensitivityInput(
            fixed_costs=100_000,
            unit_price=50,
            variable_cost_per_unit=10,
            monthly_unit_sales=100,
            revenue_multipliers=[0.7, 1.0, 1.3],
        ))
        scenarios = result["scenarios"]
        assert set(scenarios.keys()) == {"pessimistic", "base", "optimistic"}

        # Base: 100 sales/mo → break_even_months = 25 (verified above)
        assert scenarios["base"]["break_even_months"] == pytest.approx(25.0)

        # Pessimistic: 70 sales/mo → break_even_months = 2500/70 ≈ 35.71
        assert scenarios["pessimistic"]["break_even_months"] == pytest.approx(35.71, rel=1e-2)

        # Optimistic: 130 sales/mo → break_even_months = 2500/130 ≈ 19.23
        assert scenarios["optimistic"]["break_even_months"] == pytest.approx(19.23, rel=1e-2)

    def test_pessimistic_always_longest(self):
        result = run_sensitivity_analysis(SensitivityInput(
            fixed_costs=50_000,
            unit_price=100,
            monthly_unit_sales=50,
        ))
        s = result["scenarios"]
        assert s["pessimistic"]["break_even_months"] > s["base"]["break_even_months"]
        assert s["base"]["break_even_months"] > s["optimistic"]["break_even_months"]


# ──────────────────────────────────────────────────────────────────────────────
# project_cash_flow
# ──────────────────────────────────────────────────────────────────────────────

class TestProjectCashFlow:
    def test_simple_12_month(self):
        # revenue=10k/mo, opex=8k/mo, net=2k/mo, capex=20k
        # month 0: -20000; month 1: -18000; ... month 10: 0; month 11: 2000
        result = project_cash_flow(CashFlowInput(
            monthly_revenue=10_000,
            monthly_opex=8_000,
            capex=20_000,
            horizon_months=12,
        ))
        assert result["monthly_net_cash_flow"] == 2_000.0
        assert result["cash_position_by_month"][0] == -20_000.0   # month 0
        assert result["cash_position_by_month"][1] == -18_000.0   # month 1
        assert result["payback_month"] == 10                      # month 10: 0.0
        assert result["final_position"] == pytest.approx(4_000.0) # month 12

    def test_payback_none_when_never_positive(self):
        # Revenue < opex — never profitable
        result = project_cash_flow(CashFlowInput(
            monthly_revenue=5_000,
            monthly_opex=8_000,
            capex=10_000,
            horizon_months=24,
        ))
        assert result["payback_month"] is None
        assert result["final_position"] < 0

    def test_zero_capex(self):
        # Immediately positive if revenue > opex and capex = 0
        result = project_cash_flow(CashFlowInput(
            monthly_revenue=5_000,
            monthly_opex=3_000,
            capex=0,
            horizon_months=6,
        ))
        assert result["payback_month"] == 1   # first month is already positive
        assert result["cash_position_by_month"][0] == 0.0

    def test_output_length(self):
        result = project_cash_flow(CashFlowInput(
            monthly_revenue=10_000,
            monthly_opex=5_000,
            capex=50_000,
            horizon_months=36,
        ))
        # month 0 + 36 months = 37 entries
        assert len(result["cash_position_by_month"]) == 37


# ──────────────────────────────────────────────────────────────────────────────
# calculate_cost_structure
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateCostStructure:
    def test_basic(self):
        # capex=30k, opex=4k/mo, horizon=36mo -> cumulative_opex = 144,000
        result = calculate_cost_structure(CostStructureInput(
            capex=30_000,
            opex_monthly=4_000,
            horizon_months=36,
        ))
        assert result["capex"] == 30_000.0
        assert result["cumulative_opex"] == 144_000.0
        assert result["total_cost"] == 174_000.0
        assert result["horizon_months"] == 36

    def test_zero_opex(self):
        result = calculate_cost_structure(CostStructureInput(
            capex=10_000,
            opex_monthly=0,
            horizon_months=12,
        ))
        assert result["cumulative_opex"] == 0.0
        assert result["total_cost"] == 10_000.0

    def test_zero_capex(self):
        # Pure-service business with no upfront investment — cost is opex-only.
        result = calculate_cost_structure(CostStructureInput(
            capex=0,
            opex_monthly=2_500,
            horizon_months=12,
        ))
        assert result["capex"] == 0.0
        assert result["cumulative_opex"] == 30_000.0
        assert result["total_cost"] == 30_000.0

    def test_rounding(self):
        # 999.995 * 3 = 2999.985 -> rounds to 2999.98 (banker's rounding) or 2999.99;
        # assert via round() itself rather than hardcoding float rounding mode.
        result = calculate_cost_structure(CostStructureInput(
            capex=1_234.567,
            opex_monthly=999.995,
            horizon_months=3,
        ))
        assert result["capex"] == round(1_234.567, 2)
        assert result["cumulative_opex"] == round(999.995 * 3, 2)
        assert result["total_cost"] == round(result["capex"] + result["cumulative_opex"], 2)


# ──────────────────────────────────────────────────────────────────────────────
# get_financial_tools (LangChain wrapper smoke test)
# ──────────────────────────────────────────────────────────────────────────────

class TestGetFinancialTools:
    def test_returns_six_tools(self):
        tools = get_financial_tools()
        assert len(tools) == 6

    def test_tool_names(self):
        names = {t.name for t in get_financial_tools()}
        assert names == {
            "calculate_break_even",
            "calculate_roi",
            "calculate_npv",
            "run_sensitivity_analysis",
            "project_cash_flow",
            "calculate_cost_structure",
        }

    def test_tools_are_callable(self):
        tools = get_financial_tools()
        be_tool = next(t for t in tools if t.name == "calculate_break_even")
        result = be_tool.invoke({
            "fixed_costs": 100_000,
            "unit_price": 50,
            "variable_cost_per_unit": 10,
            "monthly_unit_sales": 100,
        })
        assert result["break_even_months"] == 25.0
