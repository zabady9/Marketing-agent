"""
Integration test for CompetitiveAnalysisAgent's deep-agent code path
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


class _FakeCompetitiveModel(BaseChatModel):
    """First turn: calls tavily_search for a follow-up query about a named
    competitor that came back with zero citations. Second turn: finalizes
    citing citation_index=3 for that competitor — the index of the result
    that only exists because of the follow-up call. CompetitiveAnalysisAgent
    fires 3 upfront queries when no user-provided competitors are given (2
    generic + 1 market-share query), yielding upfront indices 0-2; the
    follow-up result lands at index 3."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-competitive-model"

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
                    {"name": "tavily_search", "args": {"query": "Acme Corp pricing strengths weaknesses"}, "id": "call_1"}
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        finalize_tool = next(t for t in self._bound_tools if t.name == "_CompetitiveLLMOutput")
        args = {
            "competitors": [
                {
                    "name": "Widgets Inc",
                    "market_position": "leader",
                    "strengths": ["Strong brand"],
                    "weaknesses": ["High prices"],
                    "citation_indices": [0],
                    "methodology": "Result [0] describes their brand and pricing.",
                },
                {
                    "name": "Acme Corp",
                    "market_position": "challenger",
                    "strengths": ["Aggressive pricing"],
                    "weaknesses": ["No subscription tier"],
                    "citation_indices": [3],
                    "methodology": "Result [5] describes their pricing and lack of a subscription tier.",
                },
            ],
            "key_differentiators": ["Curated onboarding"],
            "market_gaps": ["Underserved SMB segment"],
            "narrative": "A competitive but fragmented market.",
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


class TestCompetitiveDeepAgentCitationGuard:
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
            for i in range(3)
        ]
        followup_result = [
            SearchResult(
                url="https://example.com/acme",
                title="Acme Corp pricing report",
                snippet="Acme Corp has aggressive pricing and no subscription tier",
            )
        ]

        call_log = []

        async def fake_search(query, api_key, *, max_results=5, search_depth="advanced"):
            call_log.append(query)
            if len(call_log) <= 3:
                return [upfront_results[len(call_log) - 1]]
            return followup_result

        monkeypatch.setattr("app.tools.web_search.search", fake_search)

        from app.agents.competitive import CompetitiveAnalysisAgent

        agent = CompetitiveAnalysisAgent()
        agent._llm = _FakeCompetitiveModel()

        queue = EventQueue()
        output = await agent.run(_fi(), queue)
        await queue.close()

        widgets = next(c for c in output.competitors if c.name == "Widgets Inc")
        acme = next(c for c in output.competitors if c.name == "Acme Corp")

        # Widgets Inc: cited against an upfront result (index 0) — survives untouched.
        assert len(widgets.citations) == 1
        assert widgets.citations[0].url == "https://example.com/0"
        assert widgets.claim_type.value == "verified_fact"

        # Acme Corp: cited against the mid-loop follow-up result (index 5) — this
        # is the guard-survives-the-loop assertion. If citation_index resolution
        # were broken (e.g. renumbered per-call instead of cumulative), this
        # would incorrectly resolve to no citation and fall back to an
        # unverified claim type instead.
        assert len(acme.citations) == 1
        assert acme.citations[0].url == "https://example.com/acme"
        assert acme.claim_type.value == "verified_fact"
        assert acme.weaknesses == ["No subscription tier"]
