"""
Integration test for RiskAssessmentAgent's deep-agent code path
(settings.deepagents_enabled=True): proves the citation guard survives a
mid-loop tavily_search call — a citation_index the model states after
fetching an extra search result must resolve against the SAME all_results
list the per-entry citation resolution checks, at a stable index, whether
that result came from the upfront batch or a follow-up tool call.

Uses a fake chat model (no real LLM) and monkeypatches app.tools.web_search's
search() (no real network/Tavily calls).
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.schemas.common import ClaimType
from app.schemas.intake import FeasibilityInput, FieldWithSource
from app.schemas.market import (
    CompetitiveAnalysisOutput,
    EstimatedMarketFigure,
    MarketSizingOutput,
)
from app.schemas.report import CalcTrace, CalculatedFigure, FinancialModelOutput, LocalizedText
from app.sse import EventQueue
from app.tools.web_search import SearchResult


@pytest.fixture(autouse=True)
def _reset_settings_after():
    """Reset the module-level Settings singleton after this test — without
    it, this test's `settings.deepagents_enabled = True` mutation leaks into
    whichever test module runs next (monkeypatch only undoes the env vars,
    not the cached Settings object app.config.get_settings() returns)."""
    yield
    app.config._settings = None


class _FakeRiskModel(BaseChatModel):
    """First turn: calls tavily_search for a follow-up query. Second turn:
    finalizes citing citation_index=3 — the index of the result that only
    exists because of that follow-up call (3 upfront results, indices 0-2;
    the follow-up result lands at index 3)."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-risk-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            search_tool = next(t for t in self._bound_tools if t.name == "tavily_search")
            msg = AIMessage(
                content="",
                tool_calls=[
                    {"name": "tavily_search", "args": {"query": "founder supply chain risk follow-up"}, "id": "call_1"}
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        finalize_tool = next(t for t in self._bound_tools if t.name == "_RiskLLMOutput")
        args = {
            "risks": [
                {
                    "risk_description": "Supply chain disruption could delay meal-kit deliveries.",
                    "category": "operational",
                    "probability": "high",
                    "impact": "medium",
                    "mitigation": "Diversify suppliers across at least two regions.",
                    "citation_index": 3,
                    "methodology": "Result [3] specifically states supply chain risk.",
                },
                {
                    "risk_description": "Market growth may be slower than forecast.",
                    "category": "market",
                    "probability": "medium",
                    "impact": "medium",
                    "mitigation": "Monitor CAGR estimates quarterly and adjust spend.",
                    "citation_index": None,
                    "methodology": "Analyst judgment based on typical risk patterns in United States.",
                },
            ],
            "narrative": "Several manageable risks were identified.",
        }
        msg = AIMessage(content="", tool_calls=[{"name": finalize_tool.name, "args": args, "id": "call_2"}])
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
    figure = EstimatedMarketFigure(value=None, confidence="low")
    return MarketSizingOutput(
        study_id="study-1",
        output_language="en",
        tam=figure,
        sam=figure,
        som=figure,
        growth_rate_cagr=None,
        narrative=LocalizedText(text="Market overview.", language="en"),
        key_insights=["Insight one"],
        all_citations=[],
        search_queries_used=["query"],
        review_recommended=True,
    )


def _competitive_output() -> CompetitiveAnalysisOutput:
    return CompetitiveAnalysisOutput(
        study_id="study-1",
        output_language="en",
        competitors=[],
        key_differentiators=["Faster delivery"],
        market_gaps=["Underserved rural segment"],
        narrative=LocalizedText(text="Competitive overview.", language="en"),
        all_citations=[],
        search_queries_used=["query"],
    )


def _financial_output() -> FinancialModelOutput:
    def calc(fn: str, value) -> CalculatedFigure:
        return CalculatedFigure(
            value=value,
            currency="USD",
            calculation_trace=CalcTrace(fn=fn, inputs={}, output={}),
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
        break_even=calc("calculate_break_even", {"break_even_months": 6, "break_even_units": 800}),
        roi_year_1=calc("calculate_roi", {"roi_percent": -5.0}),
        roi_year_n=calc("calculate_roi", {"roi_percent": 40.0}),
        npv=calc("calculate_npv", {"npv": 20_000.0, "is_positive": True}),
        sensitivity=calc("calculate_sensitivity", {"scenarios": {}}),
        cash_flow=calc("calculate_cash_flow", {"cash_position_by_month": [], "payback_month": 8}),
        cost_structure=calc("calculate_cost_structure", {}),
        narrative=LocalizedText(text="Financial overview.", language="en"),
        review_recommended=False,
    )


class TestRiskDeepAgentCitationGuard:
    async def test_citation_from_a_mid_loop_search_result_resolves_and_survives(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        settings = app.config.get_settings()
        settings.deepagents_enabled = True

        upfront_results = [
            SearchResult(url=f"https://example.com/{i}", title=f"Result {i}", snippet=f"snippet {i}")
            for i in range(3)
        ]
        followup_result = [
            SearchResult(
                url="https://example.com/supply-chain",
                title="Supply chain risk report",
                snippet="Supply chain disruptions are a top risk for meal-kit startups.",
            )
        ]

        call_log = []

        async def fake_search(query, api_key, *, max_results=5, search_depth="advanced"):
            call_log.append(query)
            if len(call_log) <= 3:
                return [upfront_results[len(call_log) - 1]]
            return followup_result

        monkeypatch.setattr("app.tools.web_search.search", fake_search)

        from app.agents.risk import RiskAssessmentAgent

        agent = RiskAssessmentAgent()
        agent._llm = _FakeRiskModel()

        queue = EventQueue()
        output = await agent.run(
            _fi(),
            queue,
            market_output=_market_output(),
            competitive_output=_competitive_output(),
            financial_output=_financial_output(),
        )
        await queue.close()

        assert len(output.risks) == 2

        # Risk 0: cited against the mid-loop follow-up result (index 3) — this
        # is the guard-survives-the-loop assertion. If citation_index
        # resolution were broken (e.g. renumbered per-call instead of
        # cumulative), this would incorrectly fail to resolve any citation.
        risk0 = output.risks[0]
        assert risk0.risk_description == "Supply chain disruption could delay meal-kit deliveries."
        assert len(risk0.citations) == 1
        assert risk0.citations[0].url == "https://example.com/supply-chain"
        assert risk0.claim_type == ClaimType.VERIFIED_FACT

        # Risk 1: no citation claimed at all — stays uncited/opinion, as today.
        risk1 = output.risks[1]
        assert risk1.citations == []
        assert risk1.claim_type == ClaimType.OPINION

        # Aggregate citations include the mid-loop-resolved one.
        assert any(c.url == "https://example.com/supply-chain" for c in output.citations)
