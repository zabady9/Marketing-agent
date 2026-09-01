"""
Regression test for citation_qc.py's Tier E (citation relevance) mutation
logic — locks in the exact failure mode found during manual review of a real
pipeline run: a competitor citation that resolves to a same-named business in
a different city/industry must be downgraded from verified_fact to opinion,
while a genuinely well-grounded competitor must be left untouched.

This does NOT test whether the real LLM judges relevance correctly — that's
an inherent, probabilistic limitation of a cheap-model check (see the
Methodology & Sources appendix note added alongside this test) and can't be
locked in by a code test. What CAN and must be locked in: given a relevance
verdict, does our code correctly act on it (downgrade, clear citations,
overwrite methodology, raise the right QCFlag). The LLM call itself is
stubbed with a canned response mirroring the real Toucano/PURO Coffee case.
"""

from app.agents.citation_qc import CitationValidationAgent, _RelevanceItem, _RelevanceReport
from app.schemas.common import Citation, ClaimType
from app.schemas.market import CompetitiveAnalysisOutput, CompetitorProfile
from app.schemas.report import LocalizedText
from app.schemas.qc import QCIssue


class _FakeStructuredLLM:
    def __init__(self, canned: _RelevanceReport):
        self._canned = canned

    async def ainvoke(self, _messages):
        return self._canned


class _FakeLLM:
    def __init__(self, canned: _RelevanceReport):
        self._canned = canned

    def with_structured_output(self, _schema):
        return _FakeStructuredLLM(self._canned)


def _competitive_output(mismatched_name: str, grounded_name: str) -> CompetitiveAnalysisOutput:
    mismatched = CompetitorProfile(
        name=mismatched_name,
        source="user_provided",
        strengths=["established brand"],
        weaknesses=["no subscription model"],
        citations=[Citation(url="https://example.com/wrong-entity", title="Unrelated company", snippet="...")],
        claim_type=ClaimType.VERIFIED_FACT,
        methodology="Cited result [4] places this business in a different city, unrelated to the named competitor.",
    )
    grounded = CompetitorProfile(
        name=grounded_name,
        source="estimated",
        strengths=["strong local presence"],
        weaknesses=["narrow menu"],
        citations=[Citation(url="https://example.com/cairo-roaster", title="Cairo roaster profile", snippet="...")],
        claim_type=ClaimType.VERIFIED_FACT,
        methodology="Cited result [0] establishes this company as a Cairo-based specialty roaster.",
    )
    return CompetitiveAnalysisOutput(
        study_id="s1",
        output_language="en",
        competitors=[mismatched, grounded],
        key_differentiators=[],
        market_gaps=[],
        narrative=LocalizedText(text="...", language="en"),
        all_citations=[],
        search_queries_used=[],
    )


async def test_mismatched_citation_downgraded_grounded_citation_untouched():
    competitive = _competitive_output("Toucano", "Cairo Coffee Collective")

    # Mirrors the real observed case: the LLM correctly identifies the
    # mismatch (competitor:0) and confirms the well-grounded one (competitor:1).
    canned = _RelevanceReport(items=[
        _RelevanceItem(
            item_id="competitor:0",
            is_relevant=False,
            issue="Cited source describes an unrelated business in a different city, not the named competitor.",
        ),
        _RelevanceItem(item_id="competitor:1", is_relevant=True, issue=None),
    ])

    agent = CitationValidationAgent()
    agent._llm = _FakeLLM(canned)

    flags = await agent._check_citation_relevance(None, competitive, None)

    mismatched, grounded = competitive.competitors

    # Mismatched competitor: downgraded, citations cleared, methodology overwritten.
    assert mismatched.claim_type == ClaimType.OPINION
    assert mismatched.citations == []
    assert "Downgraded to opinion" in mismatched.methodology

    # Grounded competitor: left exactly as-is.
    assert grounded.claim_type == ClaimType.VERIFIED_FACT
    assert len(grounded.citations) == 1
    assert "Cairo-based specialty roaster" in grounded.methodology

    # Exactly one flag, for the mismatched competitor only.
    assert len(flags) == 1
    assert flags[0].section == "competitive_landscape"
    assert flags[0].issue == QCIssue.CITATION_RELEVANCE
    assert flags[0].detail == canned.items[0].issue


async def test_no_verified_fact_items_returns_no_flags_and_skips_llm_call():
    # All-opinion output — nothing to check, so the (fake) LLM must not even
    # be called. A canned report with items would make this test fail loudly
    # if that invariant regresses.
    competitive = _competitive_output("A", "B")
    for c in competitive.competitors:
        c.claim_type = ClaimType.OPINION

    class _ExplodingLLM:
        def with_structured_output(self, _schema):
            raise AssertionError("LLM should not be called when there are no verified_fact items")

    agent = CitationValidationAgent()
    agent._llm = _ExplodingLLM()

    flags = await agent._check_citation_relevance(None, competitive, None)
    assert flags == []
