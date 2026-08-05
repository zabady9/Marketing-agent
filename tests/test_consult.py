"""Unit tests for /consult endpoint and intent_agent (no live DB, no real LLM)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from app.agents.consulting_agent import _build_queries
from app.agents.intent_agent import IntentClassification, classify_intent
from app.database import get_db
from app.main import app

BRAND = {"industry": "food delivery", "brand_name": "TestBrand"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mock_db():
    """Return an async context-manager session factory that never connects to a real DB."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def _override():
        yield mock_session

    return _override, mock_session


# ── _build_queries ─────────────────────────────────────────────────────────────

def test_build_queries_no_context_returns_template_count():
    queries = _build_queries("pestel", BRAND)
    assert len(queries) == 4


def test_build_queries_context_appends_two_targeted_queries():
    question = "What regulations affect UAE expansion?"
    queries = _build_queries("pestel", BRAND, context=question)
    assert len(queries) == 6
    assert question[:200] in queries
    assert f"food delivery {question[:150]}" in queries


def test_build_queries_context_truncated_to_limits():
    long_q = "x" * 300
    queries = _build_queries("swot", BRAND, context=long_q)
    # The raw question is capped at 200 chars; the industry-prefixed at 150+industry
    raw_appended = next(q for q in queries if q.startswith("x"))
    assert len(raw_appended) <= 200
    industry_prefixed = next(q for q in queries if q.startswith("food delivery x"))
    assert "x" * 151 not in industry_prefixed   # context portion is capped at 150


# ── classify_intent ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_intent_passes_question_to_llm_and_returns_result():
    expected = IntentClassification(
        analysis_type="swot",
        reasoning="mentions strengths and threats",
        suggestion=None,
    )
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = AsyncMock(
        ainvoke=AsyncMock(return_value=expected)
    )
    with patch("app.agents.intent_agent.get_llm", return_value=mock_llm):
        result = await classify_intent("What are our biggest strengths?", BRAND)
    assert result.analysis_type == "swot"
    assert result.suggestion is None


# ── Router: /consult ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_workspace_returns_404():
    override, _ = _mock_db()
    app.dependency_overrides[get_db] = override
    try:
        with patch("app.routers.consult.get_workspace", AsyncMock(return_value=None)):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/workspaces/no-such-ws/consult", json={"question": "hello"})
    finally:
        del app.dependency_overrides[get_db]
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_missing_brand_profile_returns_422():
    override, _ = _mock_db()
    app.dependency_overrides[get_db] = override
    try:
        with (
            patch("app.routers.consult.get_workspace", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.get_brand_profile", AsyncMock(return_value=None)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/workspaces/ws-1/consult", json={"question": "hello"})
    finally:
        del app.dependency_overrides[get_db]
    assert r.status_code == 422
    assert "brand profile" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_classifier_llm_failure_returns_503():
    override, _ = _mock_db()
    app.dependency_overrides[get_db] = override
    try:
        with (
            patch("app.routers.consult.get_workspace", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.get_brand_profile", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.brand_profile_to_dict", return_value=BRAND),
            patch("app.routers.consult.classify_intent", AsyncMock(side_effect=Exception("API timeout"))),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/workspaces/ws-1/consult", json={"question": "What is my SWOT?"})
    finally:
        del app.dependency_overrides[get_db]
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_out_of_scope_returns_422_with_classification():
    override, _ = _mock_db()
    app.dependency_overrides[get_db] = override
    try:
        with (
            patch("app.routers.consult.get_workspace", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.get_brand_profile", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.brand_profile_to_dict", return_value=BRAND),
            patch("app.routers.consult.classify_intent", AsyncMock(return_value=IntentClassification(
                analysis_type="out_of_scope",
                reasoning="creative writing request",
                suggestion="This platform handles strategic analysis. Try asking about market research.",
            ))),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/workspaces/ws-1/consult", json={"question": "Write me a poem"})
    finally:
        del app.dependency_overrides[get_db]
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["classification"] == "out_of_scope"
    assert "market research" in detail["message"]


@pytest.mark.asyncio
async def test_general_returns_422_with_suggestion():
    override, _ = _mock_db()
    app.dependency_overrides[get_db] = override
    suggestion = "Are you looking for a SWOT or a market overview?"
    try:
        with (
            patch("app.routers.consult.get_workspace", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.get_brand_profile", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.brand_profile_to_dict", return_value=BRAND),
            patch("app.routers.consult.classify_intent", AsyncMock(return_value=IntentClassification(
                analysis_type="general",
                reasoning="too broad",
                suggestion=suggestion,
            ))),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post("/api/workspaces/ws-1/consult", json={"question": "Tell me about my business"})
    finally:
        del app.dependency_overrides[get_db]
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["classification"] == "general"
    assert suggestion in detail["message"]


@pytest.mark.asyncio
async def test_valid_classification_returns_202_and_classified_as():
    override, mock_session = _mock_db()
    app.dependency_overrides[get_db] = override

    # Simulate db.refresh() populating the analysis fields
    async def fake_refresh(obj):
        obj.id = "test-id-999"
        obj.status = "generating"
        obj.created_at = "2026-08-02T10:00:00"
    mock_session.refresh = fake_refresh

    try:
        with (
            patch("app.routers.consult.get_workspace", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.get_brand_profile", AsyncMock(return_value=MagicMock())),
            patch("app.routers.consult.brand_profile_to_dict", return_value=BRAND),
            patch("app.routers.consult.classify_intent", AsyncMock(return_value=IntentClassification(
                analysis_type="swot",
                reasoning="mentions strengths and threats",
                suggestion=None,
            ))),
            patch("app.routers.consult.run_consulting_analysis", AsyncMock()),
            patch("app.routers.consult.event_bus") as mock_bus,
        ):
            mock_bus.create = MagicMock()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                r = await c.post(
                    "/api/workspaces/ws-1/consult",
                    json={"question": "What are our biggest strengths and threats?"},
                )
    finally:
        del app.dependency_overrides[get_db]

    assert r.status_code == 202
    body = r.json()
    assert body["classified_as"] == "swot"
    assert body["analysis_type"] == "swot"
    assert body["status"] == "generating"
