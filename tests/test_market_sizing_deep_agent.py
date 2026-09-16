"""
Integration test for MarketSizingAgent's deep-agent code path
(settings.deepagents_enabled=True): proves the citation guard survives a
mid-loop tavily_search call — a citation_index the model states after
fetching an extra search result must resolve against the SAME all_results
list the guard checks, at a stable index, whether that result came from the
upfront batch or a follow-up tool call.

Uses a fake chat model (no real LLM) and monkeypatches app.tools.web_search's
search() (no real network/Tavily calls).
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.schemas.intake import FeasibilityInput, FieldWithSource
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


class _FakeMarketModel(BaseChatModel):
    """First turn: calls tavily_search for a follow-up query. Second turn:
    finalizes citing citation_index=5 — the index of the result that only
    exists because of that follow-up call (5 upfront results, indices 0-4;
    the follow-up result lands at index 5)."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-market-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            search_tool = next(t for t in self._bound_tools if t.name == "tavily_search")
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "tavily_search", "args": {"query": "SAM follow-up"}, "id": "call_1"}],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        finalize_tool = next(t for t in self._bound_tools if t.name == "_MarketLLMOutput")
        args = {
            "tam": {"value": 5_000_000_000, "currency": "USD", "unit": "billion USD",
                    "confidence": "high", "citation_index": 0, "methodology": "Result [0] states TAM."},
            "sam": {"value": 500_000_000, "currency": "USD", "unit": "million USD",
                    "confidence": "medium", "citation_index": 5, "methodology": "Result [5] states SAM."},
            "som": {"value": None, "currency": "USD", "unit": "million USD",
                    "confidence": "low", "citation_index": None, "methodology": "No result sizes SOM."},
            "growth_rate_cagr": None,
            "growth_rate_citation_index": None,
            "growth_rate_methodology": "No result states a growth rate.",
            "narrative": "A promising market.",
            "key_insights": ["Insight one", "Insight two"],
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


class TestMarketSizingDeepAgentCitationGuard:
    async def test_citation_from_a_mid_loop_search_result_resolves_and_survives_the_guard(
        self, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        settings = app.config.get_settings()
        settings.deepagents_enabled = True

        upfront_results = [
            SearchResult(url=f"https://example.com/{i}", title=f"Result {i}", snippet=f"snippet {i}")
            for i in range(5)
        ]
        followup_result = [SearchResult(url="https://example.com/sam", title="SAM report", snippet="SAM is $500M")]

        call_log = []

        async def fake_search(query, api_key, *, max_results=5, search_depth="advanced"):
            call_log.append(query)
            if len(call_log) <= 5:
                return [upfront_results[len(call_log) - 1]]
            return followup_result

        monkeypatch.setattr("app.tools.web_search.search", fake_search)

        from app.agents.market_sizing import MarketSizingAgent

        agent = MarketSizingAgent()
        agent._llm = _FakeMarketModel()

        queue = EventQueue()
        output = await agent.run(_fi(), queue)
        await queue.close()

        # TAM: cited against an upfront result (index 0) — survives untouched.
        assert output.tam.value == 5_000_000_000
        assert len(output.tam.citations) == 1
        assert output.tam.citations[0].url == "https://example.com/0"

        # SAM: cited against the mid-loop follow-up result (index 5) — this
        # is the guard-survives-the-loop assertion. If citation_index
        # resolution were broken (e.g. renumbered per-call instead of
        # cumulative), this would incorrectly null out to None.
        assert output.sam.value == 500_000_000
        assert len(output.sam.citations) == 1
        assert output.sam.citations[0].url == "https://example.com/sam"

        # SOM: no citation claimed at all — stays null, as today.
        assert output.som.value is None
