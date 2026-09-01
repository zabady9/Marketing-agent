"""
Unit tests for the other two deterministic ClaimType classifiers added
alongside market_sizing's `_guard`/`_classify_figure`:
app/agents/competitive.py::_classify_competitor and
app/agents/risk.py::_classify_risk.

No LLM, no network, no async.
"""

from app.agents.competitive import _classify_competitor
from app.agents.risk import _classify_risk
from app.schemas.common import Citation, ClaimType

_CITATION = Citation(url="https://example.com/competitor", title="Competitor page", snippet="...")


class TestClassifyCompetitor:
    def test_cited_competitor_is_verified_fact_regardless_of_source(self):
        assert _classify_competitor("estimated", [_CITATION]) == ClaimType.VERIFIED_FACT
        assert _classify_competitor("user_provided", [_CITATION]) == ClaimType.VERIFIED_FACT

    def test_uncited_user_provided_competitor_is_assumption(self):
        # The user told us this competitor exists — that's an assumption
        # carried in, not a citation-backed fact and not the LLM's opinion.
        assert _classify_competitor("user_provided", []) == ClaimType.ASSUMPTION

    def test_uncited_llm_discovered_competitor_is_opinion(self):
        assert _classify_competitor("estimated", []) == ClaimType.OPINION


class TestClassifyRisk:
    def test_cited_risk_is_verified_fact(self):
        assert _classify_risk([_CITATION]) == ClaimType.VERIFIED_FACT

    def test_uncited_risk_is_opinion(self):
        assert _classify_risk([]) == ClaimType.OPINION
