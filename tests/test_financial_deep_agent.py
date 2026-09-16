"""
Tests for FinancialModelingAgent's deep-agent code path
(settings.deepagents_enabled=True).

Key invariants under test:
  (a) When the deep agent finalizes the narrative directly, the narrative
      text is populated AND every calculated numeric field (break-even, ROI,
      NPV, sensitivity, cash flow, cost structure) is byte-for-byte identical
      to what calling the pure-Python calculator functions directly with the
      same inputs would produce — i.e. the LLM never touches the numbers,
      only the narrative prose.
  (b) When the deep agent never calls the narrative finalize tool (the
      "silent None" case LangChain does not treat as an error), the phase
      degrades gracefully to a fallback narrative instead of raising or
      aborting — this is a deliberate behavior change from before, where an
      uncaught narrative exception would have propagated and aborted the
      whole financial phase.
  (c) A FinancialCalcError raised by a calculator (simulated via monkeypatch)
      propagates as FinancialCalcError completely unaffected by whether
      deepagents_enabled is True or False — the calculator block and its
      exception semantics are untouched by this migration.

Uses a fake chat model (no real LLM, no network) exactly like
tests/test_market_sizing_deep_agent.py and tests/test_deep_agent_factory.py.
"""

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import app.config
from app.schemas.intake import FeasibilityInput, FieldWithSource
from app.sse import EventQueue
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
    project_cash_flow,
    run_sensitivity_analysis,
)


class _FakeNarrativeModel(BaseChatModel):
    """Finalizes the narrative structured-output tool on the very first turn."""

    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-narrative-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        finalize_tool = next(t for t in self._bound_tools if t.name == "_Narrative")
        args = {
            "summary": "A financially promising venture with a clear path to break-even.",
            "key_insights": ["Break-even reached within the horizon.", "Positive NPV."],
            "risks_from_numbers": ["Sensitive to a drop in monthly sales."],
        }
        msg = AIMessage(content="", tool_calls=[{"name": finalize_tool.name, "args": args, "id": "call_1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class _FakeSilentModel(BaseChatModel):
    """Never calls the narrative finalize tool — replies with plain text
    forever, exercising the "silent None" failure mode that
    run_structured_deep_agent must catch (LangChain does not treat this as
    an error on its own)."""

    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-silent-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="just chatting"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _fi(**overrides) -> FeasibilityInput:
    field = lambda v: FieldWithSource(value=v)  # noqa: E731
    defaults = dict(
        study_id="study-1",
        raw_user_input="A subscription meal-kit service in the United States.",
        detected_language="en",
        output_language="en",
        business_description=field("A subscription meal-kit service"),
        problem_statement=field("People don't have time to plan healthy meals"),
        unique_value_proposition=field("Curated, chef-designed weekly meal kits"),
        target_market_description=field("Busy urban professionals"),
        target_market_geography=field("United States"),
        target_market_type=field("B2C"),
        business_model_type=field("subscription"),
        capex=field(50_000.0),
        capex_currency="USD",
        funding_source=field("self-funded"),
        opex_monthly=field(10_000.0),
        opex_monthly_currency="USD",
        pricing_unit_price=field(60.0),
        pricing_currency="USD",
        pricing_model=field("subscription"),
        expected_monthly_sales=field(500.0),
        competitors=[],
        founder_risks=field("Supply chain reliability"),
        team_size=field(3),
        key_roles_needed=field(["ops lead", "chef"]),
        marketing_channels=field(["social media", "referrals"]),
        study_goal=field("validate idea"),
        analysis_horizon_years=5,
    )
    defaults.update(overrides)
    return FeasibilityInput(**defaults)


def _expected_calculated_figures(fi: FeasibilityInput) -> dict:
    """Replicates FinancialModelingAgent's own arithmetic + calculator calls
    so the test can assert the deep-agent path's numeric output is identical
    to pure-Python calculation — i.e. the LLM never touches the numbers."""
    unit_price = fi.pricing_unit_price.value
    capex = fi.capex.value
    opex_monthly = fi.opex_monthly.value
    monthly_sales = fi.expected_monthly_sales.value
    horizon_months = fi.analysis_horizon_years * 12
    monthly_revenue = unit_price * monthly_sales
    annual_net = (monthly_revenue - opex_monthly) * 12

    be_output = calculate_break_even(BreakEvenInput(
        fixed_costs=capex, unit_price=unit_price,
        variable_cost_per_unit=0.0, monthly_unit_sales=monthly_sales,
    ))
    yr1_net = annual_net - capex
    roi1_output = calculate_roi(ROIInput(total_investment=capex, net_profit=yr1_net))
    roin_net = annual_net * fi.analysis_horizon_years - capex
    roin_output = calculate_roi(ROIInput(total_investment=capex, net_profit=roin_net))
    npv_output = calculate_npv(NPVInput(
        initial_investment=capex,
        annual_cash_flows=[annual_net] * fi.analysis_horizon_years,
        discount_rate=0.10,
    ))
    sens_output = run_sensitivity_analysis(SensitivityInput(
        fixed_costs=capex, unit_price=unit_price, variable_cost_per_unit=0.0,
        monthly_unit_sales=monthly_sales, revenue_multipliers=[0.7, 1.0, 1.3],
    ))
    cf_output = project_cash_flow(CashFlowInput(
        monthly_revenue=monthly_revenue, monthly_opex=opex_monthly,
        capex=capex, horizon_months=horizon_months,
    ))
    cs_output = calculate_cost_structure(CostStructureInput(
        capex=capex, opex_monthly=opex_monthly, horizon_months=horizon_months,
    ))
    return dict(
        break_even=be_output, roi_year_1=roi1_output, roi_year_n=roin_output,
        npv=npv_output, sensitivity=sens_output, cash_flow=cf_output,
        cost_structure=cs_output,
    )


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    app.config._settings = None
    yield
    app.config._settings = None


class TestNarrativeDeepAgentHappyPath:
    async def test_narrative_populated_and_numbers_match_pure_python(self):
        settings = app.config.get_settings()
        settings.deepagents_enabled = True

        from app.agents.financial import FinancialModelingAgent

        agent = FinancialModelingAgent()
        agent._llm = _FakeNarrativeModel()

        fi = _fi()
        queue = EventQueue()
        output = await agent.run(fi, queue)
        await queue.close()

        # Narrative is populated from the deep agent's finalize call.
        assert output.narrative.text == (
            "A financially promising venture with a clear path to break-even."
        )

        # Every calculated figure is identical to calling the calculators
        # directly with the same inputs — proving the LLM never touched the
        # numbers, only the narrative.
        expected = _expected_calculated_figures(fi)
        assert output.break_even.value == expected["break_even"]
        assert output.roi_year_1.value == expected["roi_year_1"]
        assert output.roi_year_n.value == expected["roi_year_n"]
        assert output.npv.value == expected["npv"]
        assert output.sensitivity.value == expected["sensitivity"]
        assert output.cash_flow.value == expected["cash_flow"]
        assert output.cost_structure.value == expected["cost_structure"]


class TestNarrativeSilentNoneDegradesGracefully:
    async def test_missing_finalize_call_falls_back_instead_of_raising(self):
        settings = app.config.get_settings()
        settings.deepagents_enabled = True

        from app.agents.financial import FinancialModelingAgent

        agent = FinancialModelingAgent()
        agent._llm = _FakeSilentModel()

        fi = _fi()
        queue = EventQueue()
        # Must NOT raise — the whole financial phase must not abort just
        # because the narrative write-up failed; the numbers are still valid.
        output = await agent.run(fi, queue)
        await queue.close()

        assert output.narrative.text == "[Narrative unavailable]"

        # Numeric figures are still fully populated and correct even though
        # the narrative degraded.
        expected = _expected_calculated_figures(fi)
        assert output.break_even.value == expected["break_even"]
        assert output.npv.value == expected["npv"]


class TestFinancialCalcErrorUnaffectedByDeepAgentsFlag:
    @pytest.mark.parametrize("deepagents_enabled", [True, False])
    async def test_calc_error_propagates_regardless_of_deepagents_flag(
        self, monkeypatch, deepagents_enabled
    ):
        settings = app.config.get_settings()
        settings.deepagents_enabled = deepagents_enabled

        import app.agents.financial as financial_module
        from app.agents.financial import FinancialCalcError, FinancialModelingAgent

        def _boom(*args, **kwargs):
            raise ValueError("simulated calculator failure")

        monkeypatch.setattr(financial_module, "calculate_break_even", _boom)

        agent = FinancialModelingAgent()
        agent._llm = _FakeNarrativeModel()

        fi = _fi()
        queue = EventQueue()
        with pytest.raises(FinancialCalcError, match="calculate_break_even failed"):
            await agent.run(fi, queue)
        await queue.close()
