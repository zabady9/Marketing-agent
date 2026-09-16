"""
Integration test for FeasibilitySynthesisAgent's deep-agent code path
(settings.deepagents_enabled=True).

Synthesis has no tools and no TodoListMiddleware — it's a single structured-
output LLM call synthesizing four already-validated upstream Pydantic outputs.
This test proves two things at once:

1. Task 1 — the new `demand_assumption_flagged` field plumbs all the way
   from the internal `_SynthesisLLMOutput` through to the public
   `FeasibilitySynthesisOutput`.
2. Task 2 — the deep-agent call path (`run_structured_deep_agent`, no tools)
   works end to end for this phase.

Uses a fake chat model (no real LLM, no network calls).
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.schemas.common import Citation
from app.schemas.intake import FeasibilityInput, FieldWithSource
from app.schemas.market import (
    CompetitiveAnalysisOutput,
    CompetitorProfile,
    EstimatedMarketFigure,
    MarketSizingOutput,
)
from app.schemas.report import CalcTrace, CalculatedFigure, FinancialModelOutput, LocalizedText
from app.schemas.risk import RiskAssessmentOutput, RiskCategory, RiskEntry, RiskLevel
from app.sse import EventQueue


class _FakeSynthesisModel(BaseChatModel):
    """Finalizes the structured-output tool directly on the first turn, with
    a configurable `demand_assumption_flagged` value in its args."""

    _bound_tools: list = []
    _flag_value: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake-synthesis-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        finalize_tool = next(t for t in self._bound_tools if t.name == "_SynthesisLLMOutput")
        args = {
            "verdict": "proceed_with_caution",
            "executive_summary": "A cautiously promising opportunity.",
            "key_opportunities": ["Growing demand", "Low competition"],
            "key_risks": ["Unvalidated demand assumption", "Thin margins"],
            "data_gaps": ["SAM unavailable"],
            "contradictions": ["Demand assumption cannot be validated against SAM"],
            "rationale": "Financial model looks sound but market validation is incomplete.",
        }
        if self._flag_value:
            args["demand_assumption_flagged"] = True
        msg = AIMessage(content="", tool_calls=[{"name": finalize_tool.name, "args": args, "id": "call_1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _fi() -> FeasibilityInput:
    field = lambda v: FieldWithSource(value=v)  # noqa: E731
    return FeasibilityInput(
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


def _market_output() -> MarketSizingOutput:
    fig = lambda v: EstimatedMarketFigure(  # noqa: E731
        value=v, currency="USD", unit="million USD", confidence="medium",
        citations=[Citation(url="https://example.com/m", title="Market report", snippet="snippet")],
    )
    return MarketSizingOutput(
        study_id="study-1",
        output_language="en",
        tam=fig(1_000_000_000),
        sam=fig(100_000_000),
        som=fig(10_000_000),
        growth_rate_cagr=8.5,
        narrative=LocalizedText(text="A growing market.", language="en"),
        key_insights=["Insight one"],
        all_citations=[],
        search_queries_used=["query one"],
    )


def _competitive_output() -> CompetitiveAnalysisOutput:
    return CompetitiveAnalysisOutput(
        study_id="study-1",
        output_language="en",
        competitors=[
            CompetitorProfile(name="Acme Meals", source="estimated", market_position="leader")
        ],
        key_differentiators=["Chef-curated recipes"],
        market_gaps=["Underserved rural segment"],
        narrative=LocalizedText(text="Moderately competitive landscape.", language="en"),
        all_citations=[],
        search_queries_used=["query two"],
    )


def _financial_output() -> FinancialModelOutput:
    def calc(fn: str, output: dict) -> CalculatedFigure:
        return CalculatedFigure(
            value=output,
            calculation_trace=CalcTrace(fn=fn, inputs={}, output=output),
        )

    return FinancialModelOutput(
        study_id="study-1",
        output_language="en",
        capex_value=50_000.0,
        capex_currency="USD",
        capex_source="user_provided",
        opex_monthly_value=10_000.0,
        opex_monthly_currency="USD",
        opex_monthly_source="user_provided",
        unit_price=60.0,
        pricing_currency="USD",
        expected_monthly_sales=500.0,
        expected_monthly_sales_source="user_provided",
        analysis_horizon_years=5,
        break_even=calc("calculate_break_even", {"break_even_months": 8, "break_even_units": 833}),
        roi_year_1=calc("calculate_roi", {"roi_percent": 15.0}),
        roi_year_n=calc("calculate_roi", {"roi_percent": 60.0}),
        npv=calc("calculate_npv", {"npv": 25000.0, "is_positive": True}),
        sensitivity=calc("calculate_sensitivity", {"scenarios": {}}),
        cash_flow=calc("calculate_cash_flow", {"cash_position_by_month": [], "payback_month": 8}),
        cost_structure=calc("calculate_cost_structure", {"capex": 50_000.0, "cumulative_opex": 600_000.0, "total_cost": 650_000.0, "horizon_months": 60}),
        narrative=LocalizedText(text="Sound financials.", language="en"),
    )


def _risk_output() -> RiskAssessmentOutput:
    return RiskAssessmentOutput(
        study_id="study-1",
        output_language="en",
        risks=[
            RiskEntry(
                risk_description="Demand may not materialize as assumed",
                category=RiskCategory.MARKET,
                probability=RiskLevel.MEDIUM,
                impact=RiskLevel.HIGH,
                mitigation="Run a pilot before scaling",
            )
        ],
        high_critical_count=0,
        narrative=LocalizedText(text="Manageable risk profile.", language="en"),
        search_queries_used=["query three"],
        citations=[],
    )


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """Isolate the global Settings singleton so flipping deepagents_enabled=True
    here doesn't leak into other test modules run in the same session."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    app.config._settings = None
    yield
    app.config._settings = None


class TestSynthesisDeepAgentDemandAssumptionFlag:
    async def _run_agent(self, monkeypatch, *, flag_value: bool):
        settings = app.config.get_settings()
        settings.deepagents_enabled = True

        from app.agents.synthesis import FeasibilitySynthesisAgent

        agent = FeasibilitySynthesisAgent()
        fake_model = _FakeSynthesisModel()
        fake_model._flag_value = flag_value
        agent._llm = fake_model
        agent._settings = settings

        queue = EventQueue()
        output = await agent.run(
            _fi(),
            queue,
            market_output=_market_output(),
            competitive_output=_competitive_output(),
            financial_output=_financial_output(),
            risk_output=_risk_output(),
            fatal_agent_failures=[],
        )
        await queue.close()
        return output

    async def test_demand_assumption_flagged_true_plumbs_through(self, monkeypatch):
        output = await self._run_agent(monkeypatch, flag_value=True)
        assert output.demand_assumption_flagged is True
        # Sanity: the rest of the structured output still made it through too.
        assert output.verdict == "proceed_with_caution"

    async def test_demand_assumption_flagged_defaults_to_false(self, monkeypatch):
        output = await self._run_agent(monkeypatch, flag_value=False)
        assert output.demand_assumption_flagged is False
