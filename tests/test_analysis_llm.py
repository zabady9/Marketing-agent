"""Transient Gemini errors are retried, then fall back to the cheap model."""

import pytest

import app.analysis.llm as llm_module
from app.analysis.llm import AnalysisLLM, parse_json_object


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_):
        return None

    monkeypatch.setattr(llm_module.asyncio, "sleep", _instant)


@pytest.fixture
def llm(db_session):  # db_session sets dummy API keys
    return AnalysisLLM()


async def test_retries_transient_errors_then_succeeds(llm):
    attempts = []

    async def make(cheap):
        attempts.append(cheap)
        if len(attempts) < 3:
            raise RuntimeError("503 UNAVAILABLE high demand")
        return "ok"

    assert await llm._call(False, make) == "ok"
    assert attempts == [False, False, False]


async def test_falls_back_to_cheap_model_after_retries(llm):
    attempts = []

    async def make(cheap):
        attempts.append(cheap)
        if not cheap:
            raise RuntimeError("503 UNAVAILABLE")
        return "cheap"

    assert await llm._call(False, make) == "cheap"
    assert attempts == [False] * 4 + [True]


async def test_non_transient_errors_are_not_retried(llm):
    attempts = []

    async def make(cheap):
        attempts.append(cheap)
        raise ValueError("bad schema")

    with pytest.raises(ValueError):
        await llm._call(False, make)
    assert attempts == [False]


def test_parse_json_object_is_lenient():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here: {"a": 1} done') == {"a": 1}
    assert parse_json_object('[{"type": "text"}]') == {"blocks": [{"type": "text"}]}
