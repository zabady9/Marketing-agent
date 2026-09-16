"""
End-to-end proof that LangSmith tracing now produces ONE hierarchical trace
across the orchestrator and its sub-agents, instead of fragmenting into
separate root traces. Runs the REAL, unmodified app.orchestrator.
run_feasibility_pipeline (legacy fixed-order path) with a real, traceable
MarketSizingAgent (fake LLM + fake Tavily search) so its internal LLM call
is genuinely nested under the pipeline — the other 5 phases are mocked at
the .run() level (their own @traceable wrapping is separately covered by
each phase's own deep-agent test) purely to keep this test's setup light.

No real network calls: langsmith.Client.create_run/update_run are patched
to capture run records instead of posting anywhere.
"""

from unittest.mock import AsyncMock, patch

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langsmith import utils as langsmith_utils


@pytest.fixture(autouse=True)
def _clear_langsmith_env_caches():
    """langsmith.utils.get_env_var/get_tracer_project are functools.lru_cache'd
    — once called with a given os.environ state, later calls return the
    STALE cached result even after monkeypatch changes the env, which would
    otherwise make this test's LANGSMITH_TRACING=true invisible whenever
    another test already forced a "tracing disabled" read into the cache
    first (e.g. via the session-wide default in conftest.py). Clear before
    AND after so this test neither reads a stale cache nor leaves one behind
    for whatever runs next."""
    langsmith_utils.get_env_var.cache_clear()
    langsmith_utils.get_tracer_project.cache_clear()
    yield
    langsmith_utils.get_env_var.cache_clear()
    langsmith_utils.get_tracer_project.cache_clear()

from app.schemas.intake import FeasibilityInput, FieldWithSource
from app.sse import EventQueue
from app.tools.web_search import SearchResult
from tests.test_single_phase_study import (
    _competitive_output,
    _financial_output,
    _risk_output,
    _synthesis_output,
)


class _FakeFinalizingModel(BaseChatModel):
    """Immediately finalizes MarketSizingAgent's structured output — no
    tavily_search follow-up needed for this test."""

    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-finalizing"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        finalize_tool = next(t for t in self._bound_tools if t.name == "_MarketLLMOutput")
        args = {
            "tam": {"value": 1_000_000, "currency": "USD", "unit": "USD", "confidence": "high",
                    "citation_index": 0, "methodology": "Result [0] states TAM."},
            "sam": {"value": None, "currency": "USD", "unit": "USD", "confidence": "low",
                    "citation_index": None, "methodology": "No result sizes SAM."},
            "som": {"value": None, "currency": "USD", "unit": "USD", "confidence": "low",
                    "citation_index": None, "methodology": "No result sizes SOM."},
            "growth_rate_cagr": None, "growth_rate_citation_index": None,
            "growth_rate_methodology": "No result states a growth rate.",
            "narrative": "n/a", "key_insights": [],
        }
        msg = AIMessage(content="", tool_calls=[{"name": finalize_tool.name, "args": args, "id": "c1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _fi() -> FeasibilityInput:
    field = lambda v: FieldWithSource(value=v)  # noqa: E731
    return FeasibilityInput(
        study_id="study-tracing-1",
        raw_user_input="A subscription meal-kit service in the United States.",
        detected_language="en", output_language="en",
        business_description=field("A subscription meal-kit service"),
        problem_statement=field("People don't have time to plan healthy meals"),
        unique_value_proposition=field("Curated, chef-designed weekly meal kits"),
        target_market_description=field("Busy urban professionals"),
        target_market_geography=field("United States"),
        target_market_type=field("B2C"), business_model_type=field("subscription"),
        capex=field(50_000.0), capex_currency="USD", funding_source=field("self-funded"),
        opex_monthly=field(10_000.0), opex_monthly_currency="USD",
        pricing_unit_price=field(60.0), pricing_currency="USD", pricing_model=field("subscription"),
        expected_monthly_sales=field(500.0), competitors=[], founder_risks=field("Supply chain reliability"),
        team_size=field(3), key_roles_needed=field(["ops lead"]), marketing_channels=field(["social"]),
        study_goal=field("validate idea"), analysis_horizon_years=5,
    )


class TestPipelineTraceIsOneHierarchy:
    async def test_market_sizing_llm_call_nests_under_the_pipeline_trace(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_fake_test_key")
        monkeypatch.setenv("LANGSMITH_PROJECT", "test-nesting")
        app.config._settings = None
        settings = app.config.get_settings()
        settings.deepagents_enabled = False  # legacy path — simplest to set up

        # Fake Tavily so MarketSizingAgent's upfront searches don't hit the network.
        async def fake_search(query, api_key, *, max_results=5, search_depth="advanced"):
            return [SearchResult(url="https://example.com/0", title="Result", snippet="TAM is $1M")]

        monkeypatch.setattr("app.tools.web_search.search", fake_search)
        monkeypatch.setattr(
            "app.agents.market_sizing.ChatGoogleGenerativeAI", lambda **kwargs: _FakeFinalizingModel()
        )

        # The other 5 phases are mocked at .run() — each phase's own tracing
        # is already covered individually by its own deep-agent test; this
        # test is specifically about the orchestrator <-> phase-agent link.
        monkeypatch.setattr(
            "app.agents.competitive.CompetitiveAnalysisAgent.run",
            AsyncMock(return_value=_competitive_output()),
        )
        monkeypatch.setattr(
            "app.agents.financial.FinancialModelingAgent.run",
            AsyncMock(return_value=_financial_output()),
        )
        monkeypatch.setattr(
            "app.agents.risk.RiskAssessmentAgent.run", AsyncMock(return_value=_risk_output())
        )
        monkeypatch.setattr(
            "app.agents.synthesis.FeasibilitySynthesisAgent.run",
            AsyncMock(return_value=_synthesis_output()),
        )
        monkeypatch.setattr(
            "app.agents.citation_qc.CitationValidationAgent.run",
            AsyncMock(return_value=_synthesis_output()),  # shape doesn't matter for this test
        )

        captured = []

        def fake_create_run(self, **kwargs):
            captured.append(kwargs)

        from app.orchestrator import run_feasibility_pipeline

        with patch("langsmith.client.Client.create_run", fake_create_run), \
             patch("langsmith.client.Client.update_run", return_value=None):
            await run_feasibility_pipeline("study-tracing-1", _fi(), EventQueue(), glossary=None)

        by_name = {c.get("name"): c for c in captured}

        assert "Feasibility Pipeline" in by_name, [c.get("name") for c in captured]
        assert "Market Sizing Agent" in by_name, [c.get("name") for c in captured]

        pipeline_run_id = by_name["Feasibility Pipeline"]["id"]
        market_sizing_run = by_name["Market Sizing Agent"]

        # The orchestrator <-> phase-agent link: Market Sizing Agent's span
        # is a CHILD of the Feasibility Pipeline span, not a separate root.
        assert market_sizing_run["parent_run_id"] == pipeline_run_id

        # The phase-agent <-> LLM link: the fake model's own call nests
        # (transitively, through LangChain's own with_structured_output
        # RunnableSequence wrapper — a real intermediate hop, not a bug)
        # under Market Sizing Agent, completing the hierarchy end-to-end
        # with NO separate root trace anywhere in the chain.
        by_id = {c["id"]: c for c in captured}

        def ancestor_ids(run: dict) -> set:
            ids, current = set(), run
            while current.get("parent_run_id") is not None:
                ids.add(current["parent_run_id"])
                current = by_id.get(current["parent_run_id"], {})
            return ids

        llm_runs = [c for c in captured if c.get("run_type") == "llm"]
        assert llm_runs, "expected at least one LLM run to be captured"
        llm_ancestors = ancestor_ids(llm_runs[0])
        assert market_sizing_run["id"] in llm_ancestors
        assert pipeline_run_id in llm_ancestors
        # Exactly one root (no parent_run_id) across the whole capture —
        # this is the actual "one hierarchical trace, not fragmented" claim.
        roots = [c for c in captured if c.get("parent_run_id") is None]
        assert len(roots) == 1
        assert roots[0]["name"] == "Feasibility Pipeline"
