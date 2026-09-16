"""
Unit tests for app/services/study_title.py::generate_study_title.

No real network/LLM call — the module-level _gemini_generate_title (an
async function) is monkeypatched, mirroring test_tool_intent.py's pattern.
Under test: the "nothing to summarize yet" short-circuit, successful title
cleanup (quote/whitespace stripping, length cap), and the
exception/timeout-safe fallback to None.
"""

import asyncio

from app.services import study_title
from app.services.study_title import _TitleResult, generate_study_title

_SECTIONS_WITH_DATA = {
    "competitive_landscape": {
        "language": "en",
        "data": {"competitors": [{"name": "Acme Corp"}], "citations": ["noise"]},
    },
}


def _fake_generate(title: str):
    async def _gen(report_label, output_language, human_content, google_api_key, cheap_model):
        return _TitleResult(title=title)

    return _gen


class TestGenerateStudyTitle:
    async def test_no_sections_data_short_circuits_without_calling_the_llm(self, monkeypatch):
        called = False

        async def _should_not_run(*args, **kwargs):
            nonlocal called
            called = True
            return _TitleResult(title="unused")

        monkeypatch.setattr(study_title, "_gemini_generate_title", _should_not_run)

        result = await generate_study_title(
            business_description="x", report_label="Competitive Analysis", sections={},
            output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result is None
        assert called is False

    async def test_successful_generation_returns_cleaned_title(self, monkeypatch):
        monkeypatch.setattr(
            study_title, "_gemini_generate_title", _fake_generate('  "5 Direct Rivals Found"  ')
        )

        result = await generate_study_title(
            business_description="A meal-kit subscription service",
            report_label="Competitive Analysis",
            sections=_SECTIONS_WITH_DATA,
            output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result == "5 Direct Rivals Found"

    async def test_overlong_title_is_truncated(self, monkeypatch):
        long_title = "A" * 200
        monkeypatch.setattr(study_title, "_gemini_generate_title", _fake_generate(long_title))

        result = await generate_study_title(
            business_description="x", report_label="Competitive Analysis",
            sections=_SECTIONS_WITH_DATA, output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result is not None
        assert len(result) == 160
        assert result.endswith("...")

    async def test_empty_title_from_model_falls_back_to_none(self, monkeypatch):
        monkeypatch.setattr(study_title, "_gemini_generate_title", _fake_generate('   ""  '))

        result = await generate_study_title(
            business_description="x", report_label="Competitive Analysis",
            sections=_SECTIONS_WITH_DATA, output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result is None

    async def test_llm_exception_falls_back_to_none(self, monkeypatch):
        async def _raise(*args, **kwargs):
            raise RuntimeError("network error")

        monkeypatch.setattr(study_title, "_gemini_generate_title", _raise)

        result = await generate_study_title(
            business_description="x", report_label="Competitive Analysis",
            sections=_SECTIONS_WITH_DATA, output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result is None

    async def test_llm_timeout_falls_back_to_none(self, monkeypatch):
        monkeypatch.setattr(study_title, "_TITLE_TIMEOUT_SECONDS", 0.05)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(10)
            return _TitleResult(title="too slow")

        monkeypatch.setattr(study_title, "_gemini_generate_title", _hang)

        result = await generate_study_title(
            business_description="x", report_label="Competitive Analysis",
            sections=_SECTIONS_WITH_DATA, output_language="en", google_api_key="x", cheap_model="y",
        )

        assert result is None
