"""
Integration tests for CitationValidationAgent's deep-agent code path
(settings.deepagents_enabled=True), covering the two QC tiers that make a
real LLM call today:

  * Tier B (faithfulness) — two separate LLM call sites:
      - _check_faithfulness      (narrative vs. computed/source data)
      - _verify_contradictions   (contradiction statements vs. source data)
  * Tier E (citation relevance) — _check_citation_relevance

Each uses a fake chat model (no real LLM, no network) that finalizes the
tier's internal structured-output schema directly via a tool call, following
the same pattern as tests/test_deep_agent_factory.py and
tests/test_market_sizing_deep_agent.py.

This file does NOT touch tests/test_qc_tier_d.py or tests/test_qc_tier_e.py —
both are re-run here unmodified as part of the same verification pass to
confirm the pure-Python tiers (D) and the existing legacy-path Tier E test
still pass untouched.
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.schemas.common import Citation, ClaimType
from app.schemas.market import CompetitiveAnalysisOutput, CompetitorProfile
from app.schemas.qc import QCIssue
from app.schemas.report import LocalizedText
from app.schemas.synthesis import FeasibilitySynthesisOutput, Verdict


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """Reset the module-level Settings singleton before AND after each test —
    without the teardown reset, a deepagents_enabled=True mutation here would
    leak into other test modules that construct CitationValidationAgent()
    without touching settings themselves (e.g. tests/test_qc_tier_e.py),
    since app.config.get_settings() caches one Settings instance process-wide."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    app.config._settings = None
    yield
    app.config._settings = None


class _FakeFinalizingModel(BaseChatModel):
    """Immediately finalizes with the given tool-call args on its first (and
    only) turn — no intermediate tool calls, matching the "no tools" shape
    of these single-shot verification calls."""

    _bound_tools: list = []

    def __init__(self, tool_name: str, args: dict):
        super().__init__()
        self._tool_name = tool_name
        self._args = args

    @property
    def _llm_type(self) -> str:
        return "fake-finalizing-model"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        target = next(t for t in self._bound_tools if t.name == self._tool_name)
        msg = AIMessage(content="", tool_calls=[{"name": target.name, "args": self._args, "id": "call_1"}])
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _enable_deepagents():
    settings = app.config.get_settings()
    settings.deepagents_enabled = True
    return settings


def _synthesis(contradictions: list[str] | None = None) -> FeasibilitySynthesisOutput:
    return FeasibilitySynthesisOutput(
        study_id="s1",
        output_language="en",
        verdict=Verdict.PROCEED_WITH_CAUTION,
        confidence_score=0.6,
        confidence_breakdown={},
        executive_summary=LocalizedText(text="A promising but uncertain venture.", language="en"),
        key_opportunities=["Untapped niche demand"],
        key_risks=["Supply chain disruption"],
        data_gaps=[],
        contradictions=contradictions or [],
        rationale=LocalizedText(text="Balanced upside and risk.", language="en"),
    )


class TestFaithfulnessDeepAgentPath:
    async def test_faithfulness_result_comes_through_via_deep_agent(self):
        _enable_deepagents()

        from app.agents.citation_qc import CitationValidationAgent

        agent = CitationValidationAgent()
        agent._llm = _FakeFinalizingModel(
            "_FaithfulnessReport",
            {
                "items": [
                    {
                        "section": "executive_summary",
                        "claim": "executive summary invents a growth figure",
                        "is_faithful": False,
                        "issue": "Cites a CAGR not present anywhere in market_overview.",
                    }
                ]
            },
        )

        flags = await agent._check_faithfulness(
            financial=None,
            synthesis=_synthesis(),
            market=None,
            competitive=None,
            risk=None,
        )

        assert len(flags) == 1
        flag = flags[0]
        assert flag.section == "executive_summary"
        assert flag.issue == QCIssue.FAITHFULNESS
        # executive_summary faithfulness failures are ERROR severity (most
        # user-facing section) — unchanged behavior, now reached via deep agent.
        assert flag.detail == "Cites a CAGR not present anywhere in market_overview."


class TestContradictionsDeepAgentPath:
    async def test_contradiction_result_comes_through_via_deep_agent(self):
        _enable_deepagents()

        from app.agents.citation_qc import CitationValidationAgent

        agent = CitationValidationAgent()
        agent._llm = _FakeFinalizingModel(
            "_ContradictionReport",
            {
                "checks": [
                    {
                        "contradiction_text": "ROI is negative yet the verdict is proceed.",
                        "accurately_stated": False,
                        "issue": "roi_year_1 is actually positive in the source data.",
                    }
                ]
            },
        )

        flags, contradictions_faithful = await agent._verify_contradictions(
            synthesis=_synthesis(contradictions=["ROI is negative yet the verdict is proceed."]),
            market=None,
            financial=None,
            risk=None,
        )

        assert contradictions_faithful is False
        assert len(flags) == 1
        assert flags[0].section == "contradictions"
        assert flags[0].issue == QCIssue.FAITHFULNESS
        assert flags[0].detail == "roi_year_1 is actually positive in the source data."


class TestCitationRelevanceDeepAgentPath:
    def _competitive_output(self) -> CompetitiveAnalysisOutput:
        mismatched = CompetitorProfile(
            name="Toucano",
            source="user_provided",
            strengths=["established brand"],
            weaknesses=["no subscription model"],
            citations=[Citation(url="https://example.com/wrong-entity", title="Unrelated company", snippet="...")],
            claim_type=ClaimType.VERIFIED_FACT,
            methodology="Cited result [4] places this business in a different city.",
        )
        return CompetitiveAnalysisOutput(
            study_id="s1",
            output_language="en",
            competitors=[mismatched],
            key_differentiators=[],
            market_gaps=[],
            narrative=LocalizedText(text="...", language="en"),
            all_citations=[],
            search_queries_used=[],
        )

    async def test_relevance_result_comes_through_via_deep_agent(self):
        _enable_deepagents()

        from app.agents.citation_qc import CitationValidationAgent

        agent = CitationValidationAgent()
        agent._llm = _FakeFinalizingModel(
            "_RelevanceReport",
            {
                "items": [
                    {
                        "item_id": "competitor:0",
                        "is_relevant": False,
                        "issue": "Cited source describes an unrelated business in a different city.",
                    }
                ]
            },
        )

        competitive = self._competitive_output()
        flags = await agent._check_citation_relevance(None, competitive, None)

        mismatched = competitive.competitors[0]
        assert mismatched.claim_type == ClaimType.OPINION
        assert mismatched.citations == []
        assert "Downgraded to opinion" in mismatched.methodology

        assert len(flags) == 1
        assert flags[0].section == "competitive_landscape"
        assert flags[0].issue == QCIssue.CITATION_RELEVANCE
        assert flags[0].detail == "Cited source describes an unrelated business in a different city."
