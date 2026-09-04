"""
Unit tests for app/services/tool_intent.py::detect_single_tool_intent.

No real network/LLM call — the module-level _gemini_classify (an async
function) is monkeypatched, and detect_single_tool_intent's own wrapping
logic (result mapping, hallucination guard, exception/timeout fallback) is
what's under test. pytest-asyncio's asyncio_mode="auto" (pyproject.toml)
lets these be plain `async def test_...` functions.
"""

import asyncio

import pytest

from app.services import tool_intent
from app.services.tool_intent import detect_single_tool_intent

_TOOL_DESCRIPTIONS = {
    "run_feasibility_study_tool": "Run the full feasibility study pipeline.",
    "update_business_profile_tool": "Update the project's business profile.",
    "remember_fact_tool": "Persist a durable fact about the user.",
}


def _fake_classify(result):
    async def _classify(user_content, tool_descriptions, google_api_key, cheap_model):
        return result

    return _classify


class TestDetectSingleToolIntent:
    async def test_restricts_to_named_tool(self, monkeypatch):
        monkeypatch.setattr(tool_intent, "_gemini_classify", _fake_classify(("remember_fact_tool", False)))
        result = await detect_single_tool_intent("just remember this", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result == "remember_fact_tool"

    async def test_restricts_to_no_tools(self, monkeypatch):
        monkeypatch.setattr(tool_intent, "_gemini_classify", _fake_classify((None, True)))
        result = await detect_single_tool_intent("don't use any tools", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result == "none"

    async def test_no_restriction_by_default(self, monkeypatch):
        monkeypatch.setattr(tool_intent, "_gemini_classify", _fake_classify((None, False)))
        result = await detect_single_tool_intent("please run the feasibility study", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result is None

    async def test_hallucinated_tool_name_is_ignored(self, monkeypatch):
        # A tool name the model invented that isn't actually available this
        # turn must not be trusted — falls back to unrestricted.
        monkeypatch.setattr(tool_intent, "_gemini_classify", _fake_classify(("made_up_tool", False)))
        result = await detect_single_tool_intent("only use the made up tool", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result is None

    async def test_classification_exception_falls_back_to_unrestricted(self, monkeypatch):
        async def _raise(user_content, tool_descriptions, google_api_key, cheap_model):
            raise RuntimeError("network error")

        monkeypatch.setattr(tool_intent, "_gemini_classify", _raise)
        result = await detect_single_tool_intent("only remember this", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result is None

    async def test_classification_timeout_falls_back_to_unrestricted(self, monkeypatch):
        monkeypatch.setattr(tool_intent, "_CLASSIFY_TIMEOUT_SECONDS", 0.05)

        async def _hang(user_content, tool_descriptions, google_api_key, cheap_model):
            await asyncio.sleep(10)
            return ("remember_fact_tool", False)

        monkeypatch.setattr(tool_intent, "_gemini_classify", _hang)
        result = await detect_single_tool_intent("only remember this", _TOOL_DESCRIPTIONS, google_api_key="x", cheap_model="y")
        assert result is None
