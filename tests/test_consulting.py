"""Unit tests for consulting analysis — citation validation, threshold checks, and intent classifier."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.consulting_agent import _build_queries
from app.agents.consulting_schemas import Citation, FeasibilitySection, SWOTItem, SWOTOutput
from app.agents.intent_agent import AnalystIntentClassification


# ── _build_queries ─────────────────────────────────────────────────────────────

_BRAND = {"industry": "food delivery", "subject_name": "TestBrand"}


def test_build_queries_no_context_returns_template_count():
    queries = _build_queries("pestel", _BRAND)
    assert len(queries) == 4


def test_build_queries_context_appends_two_targeted_queries():
    question = "What regulations affect UAE expansion?"
    queries = _build_queries("pestel", _BRAND, context=question)
    assert len(queries) == 6
    assert question[:200] in queries
    assert f"food delivery {question[:150]}" in queries


def test_build_queries_context_truncated_to_limits():
    long_q = "x" * 300
    queries = _build_queries("swot", _BRAND, context=long_q)
    raw_appended = next(q for q in queries if q.startswith("x"))
    assert len(raw_appended) <= 200
    industry_prefixed = next(q for q in queries if q.startswith("food delivery x"))
    assert "x" * 151 not in industry_prefixed


# ── classify_analyst_intent ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_analyst_intent_passes_message_to_llm_and_returns_result():
    expected = AnalystIntentClassification(intent="swot", reasoning="mentions strengths and threats")
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(ainvoke=AsyncMock(return_value=expected))
    with patch("app.agents.intent_agent.get_llm", return_value=mock_llm):
        from app.agents.intent_agent import classify_analyst_intent
        result = await classify_analyst_intent("What are our biggest strengths and threats?", _BRAND)
    assert result.intent == "swot"
    assert result.reasoning == "mentions strengths and threats"


@pytest.mark.asyncio
async def test_classify_analyst_intent_content_creation_is_out_of_scope():
    expected = AnalystIntentClassification(intent="out_of_scope", reasoning="post creation request")
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(ainvoke=AsyncMock(return_value=expected))
    with patch("app.agents.intent_agent.get_llm", return_value=mock_llm):
        from app.agents.intent_agent import classify_analyst_intent
        result = await classify_analyst_intent("Write me a social media post", _BRAND)
    assert result.intent == "out_of_scope"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_citations(n: int) -> list[Citation]:
    return [Citation(title=f"Source {i}", url=f"http://src{i}.com", snippet="...") for i in range(n)]


def _make_swot(strengths_indices, weaknesses_indices, opps_indices, threats_indices):
    return SWOTOutput(
        strengths=[SWOTItem(point="S", evidence="e", citation_indices=strengths_indices)],
        weaknesses=[SWOTItem(point="W", evidence="e", citation_indices=weaknesses_indices)],
        opportunities=[SWOTItem(point="O", evidence="e", citation_indices=opps_indices)],
        threats=[SWOTItem(point="T", evidence="e", citation_indices=threats_indices)],
    )


def _make_db_mock(mock_analysis):
    """Return (session_factory, mock_db) with mock_analysis wired to db.execute()."""
    mock_result = MagicMock()
    mock_result.scalar_one = MagicMock(return_value=mock_analysis)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_cm), mock_db


# ── Test (a): citation index validation ───────────────────────────────────────

def test_validate_strips_out_of_range_index():
    """An index beyond the citation list is stripped and the item is marked unverified."""
    from app.agents.consulting_agent import _validate_citation_indices

    citations = _make_citations(2)  # valid indices: 0, 1
    output = _make_swot(
        strengths_indices=[0, 99],   # 99 is out of range
        weaknesses_indices=[1],       # fully valid
        opps_indices=[],              # empty — no evidence at all
        threats_indices=[5, 6, 7],   # all out of range
    )

    validated = _validate_citation_indices(output, citations)

    # index 99 stripped; 0 kept → still has a citation, but marked unverified (strip happened)
    assert validated.strengths[0].citation_indices == [0]
    assert validated.strengths[0].unverified is True

    # fully valid — not touched
    assert validated.weaknesses[0].citation_indices == [1]
    assert validated.weaknesses[0].unverified is False

    # empty list → no evidence → marked unverified
    assert validated.opportunities[0].citation_indices == []
    assert validated.opportunities[0].unverified is True

    # all out of range → stripped to [] → marked unverified
    assert validated.threats[0].citation_indices == []
    assert validated.threats[0].unverified is True


def test_validate_leaves_valid_output_unchanged():
    """Output with all valid indices passes through without being marked unverified."""
    from app.agents.consulting_agent import _validate_citation_indices

    citations = _make_citations(5)
    output = _make_swot([0], [1, 2], [3], [4])

    validated = _validate_citation_indices(output, citations)

    for section in (validated.strengths, validated.weaknesses,
                    validated.opportunities, validated.threats):
        assert section[0].unverified is False


def test_validate_feasibility_sections():
    """FeasibilitySection items are also validated and marked unverified when needed."""
    from app.agents.consulting_agent import _validate_citation_indices
    from app.agents.consulting_schemas import FeasibilityOutput

    citations = _make_citations(3)
    output = FeasibilityOutput(
        market_size_and_growth=FeasibilitySection(
            title="Market", findings=["big"], citation_indices=[0, 50]  # 50 is out of range
        ),
        competitive_landscape=FeasibilitySection(
            title="Comp", findings=["tough"], citation_indices=[1]  # valid
        ),
        target_customer=FeasibilitySection(
            title="Customer", findings=["SMBs"], citation_indices=[]  # empty
        ),
        key_risks=FeasibilitySection(
            title="Risks", findings=["funding"], citation_indices=[2]  # valid
        ),
        recommendation="proceed_with_caution",
        recommendation_rationale="limited data",
    )

    validated = _validate_citation_indices(output, citations)

    assert validated.market_size_and_growth.citation_indices == [0]
    assert validated.market_size_and_growth.unverified is True

    assert validated.competitive_landscape.citation_indices == [1]
    assert validated.competitive_landscape.unverified is False

    assert validated.target_customer.citation_indices == []
    assert validated.target_customer.unverified is True

    assert validated.key_risks.citation_indices == [2]
    assert validated.key_risks.unverified is False


# ── Test (b): minimum citation threshold ─────────────────────────────────────

@pytest.mark.asyncio
async def test_insufficient_citations_fails_without_calling_run_analysis():
    """When gather_research returns < 4 citations, the analysis fails and run_analysis is never called."""
    from app.services.consulting import run_consulting_analysis

    mock_analysis = MagicMock()
    session_factory, _ = _make_db_mock(mock_analysis)

    few_citations = _make_citations(2)

    with (
        patch("app.services.consulting.gather_research", AsyncMock(return_value=few_citations)),
        patch("app.services.consulting.run_analysis") as mock_run_analysis,
        patch("app.services.consulting.event_bus") as mock_bus,
    ):
        mock_bus.emit = AsyncMock()
        mock_bus.close = MagicMock()

        await run_consulting_analysis(
            analysis_id="test-id",
            workspace_id="ws-test",
            analysis_type="swot",
            brand_profile={"industry": "retail", "brand_name": "TestBrand"},
            context=None,
            session_factory=session_factory,
        )

    mock_run_analysis.assert_not_called()
    assert mock_analysis.status == "failed"
    assert "Could not retrieve enough sources (2)" in mock_analysis.error

    emitted_types = [call.args[1].get("type") for call in mock_bus.emit.call_args_list]
    assert "error" in emitted_types


@pytest.mark.asyncio
async def test_exactly_four_citations_proceeds():
    """When citation count is exactly 4 (the threshold), run_analysis IS called."""
    from app.agents.consulting_schemas import SWOTOutput
    from app.services.consulting import run_consulting_analysis

    mock_analysis = MagicMock()
    session_factory, _ = _make_db_mock(mock_analysis)

    four_citations = _make_citations(4)
    mock_output = _make_swot([0], [1], [2], [3])

    with (
        patch("app.services.consulting.gather_research", AsyncMock(return_value=four_citations)),
        patch("app.services.consulting.run_analysis", AsyncMock(return_value=mock_output)),
        patch("app.services.consulting.event_bus") as mock_bus,
    ):
        mock_bus.emit = AsyncMock()
        mock_bus.close = MagicMock()

        await run_consulting_analysis(
            analysis_id="test-id",
            workspace_id="ws-test",
            analysis_type="swot",
            brand_profile={"industry": "retail", "brand_name": "TestBrand"},
            context=None,
            session_factory=session_factory,
        )

    assert mock_analysis.status == "ready"
