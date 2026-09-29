"""
Tests for the split of the feasibility study into independently-callable
chat tools (app/services/chat_agent.py::_build_tools). Previously a single
run_pipeline_phase_tool(phase=...) required the model to both (a) choose the
narrow tool over run_feasibility_study_tool AND (b) correctly fill in a
`phase` argument — two separate judgment calls, either of which failing
meant the full pipeline ran instead of just the requested capability. Now
each capability (market sizing, competitive, financial, risk, synthesis) has
its own zero-argument tool: choosing the tool IS choosing the phase, with no
argument-filling step left to get wrong.

These tests exercise each tool directly (no LLM involved) and assert it
calls run_single_phase_study with exactly the right phase — and nothing else
(in particular, never run_feasibility_study, the full-pipeline entry point).
"""

from unittest.mock import AsyncMock

import app.config
import app.services.chat_agent as chat_agent_module
from app.models import Artifact, ChatMessage, ChatSession
from app.services.artifact_generation import ArtifactFile, ArtifactGenerationError
from app.sse import EventQueue


def _make_session(db_session, project) -> ChatSession:
    session = ChatSession(project_id=project.id)
    db_session.add(session)
    db_session.commit()
    return session


def _build_tools(db_session, project, session):
    assistant_message = ChatMessage(role="assistant", content="", status="pending")
    session.messages.append(assistant_message)
    db_session.commit()
    tools = chat_agent_module._build_tools(
        db_session, project, EventQueue(), session, assistant_message, project.id
    )
    return {t.name: t for t in tools}


class TestCapabilityToolsAreIndependent:
    async def test_all_expected_tools_are_present_with_distinct_names(
        self, db_session, make_project
    ):
        project = make_project()
        session = _make_session(db_session, project)
        tools = _build_tools(db_session, project, session)

        assert set(tools) == {
            "run_feasibility_study_tool",
            "run_market_sizing_tool",
            "run_competitive_analysis_tool",
            "run_financial_analysis_tool",
            "run_risk_analysis_tool",
            "run_synthesis_tool",
            "update_business_profile_tool",
            "remember_fact_tool",
            "generate_chart_tool",
            "web_research_tool",
            "explain_figure_tool",
            "run_scenario_simulation_tool",
        }
        # run_pipeline_phase_tool's phase argument is gone — verify none of
        # the new capability tools still expose one (that ambiguity is
        # exactly what made the old single-tool design unreliable).
        for name in (
            "run_market_sizing_tool",
            "run_competitive_analysis_tool",
            "run_financial_analysis_tool",
            "run_risk_analysis_tool",
            "run_synthesis_tool",
        ):
            schema = tools[name].args_schema
            fields = getattr(schema, "model_fields", {}) if schema is not None else {}
            assert not fields, f"{name} should take no arguments, got {list(fields)}"

    async def test_each_capability_tool_calls_single_phase_study_with_its_own_phase_only(
        self, db_session, make_project, monkeypatch
    ):
        project = make_project()
        session = _make_session(db_session, project)

        single_phase_mock = AsyncMock()
        single_phase_mock.return_value.status = "completed"
        single_phase_mock.return_value.id = "study-x"
        single_phase_mock.return_value.sections = {
            "market_overview": {}, "competitive_landscape": {}, "financial_feasibility": {},
            "risk_assessment": {}, "executive_summary": {},
        }
        full_study_mock = AsyncMock()
        monkeypatch.setattr(chat_agent_module, "run_single_phase_study", single_phase_mock)
        monkeypatch.setattr(chat_agent_module, "run_feasibility_study", full_study_mock)

        tools = _build_tools(db_session, project, session)

        expected = {
            "run_market_sizing_tool": "market_sizing",
            "run_competitive_analysis_tool": "competitive",
            "run_financial_analysis_tool": "financial",
            "run_risk_analysis_tool": "risk",
            "run_synthesis_tool": "synthesis",
        }
        for tool_name, expected_phase in expected.items():
            single_phase_mock.reset_mock()
            await tools[tool_name].ainvoke({})
            single_phase_mock.assert_awaited_once()
            called_phase = single_phase_mock.await_args.args[2]
            assert called_phase == expected_phase
            # The defining property this test protects: calling one
            # capability's tool NEVER falls through to the full pipeline.
            full_study_mock.assert_not_awaited()

    async def test_full_study_tool_calls_run_feasibility_study_not_single_phase(
        self, db_session, make_project, monkeypatch
    ):
        project = make_project()
        session = _make_session(db_session, project)

        full_study_mock = AsyncMock()
        full_study_mock.return_value.status = "completed"
        full_study_mock.return_value.id = "study-y"
        full_study_mock.return_value.verdict = "proceed"
        full_study_mock.return_value.confidence_score = 0.9
        full_study_mock.return_value.sections = {"market_overview": {}}
        single_phase_mock = AsyncMock()
        monkeypatch.setattr(chat_agent_module, "run_feasibility_study", full_study_mock)
        monkeypatch.setattr(chat_agent_module, "run_single_phase_study", single_phase_mock)

        tools = _build_tools(db_session, project, session)
        await tools["run_feasibility_study_tool"].ainvoke({})

        full_study_mock.assert_awaited_once()
        single_phase_mock.assert_not_awaited()


class TestArtifactGenerationTools:
    """generate_presentation_tool/generate_word_document_tool/
    generate_pdf_report_tool/revise_artifact_tool — gated behind
    mcp_artifacts_enabled, so absent entirely from the tool list when that
    flag is off (the default), and never making a real HTTP call to the
    sibling MCP services here (app.services.artifact_generation's drivers
    are monkeypatched)."""

    def test_absent_when_flag_is_off(self, db_session, make_project):
        app.config.get_settings().mcp_artifacts_enabled = False
        project = make_project()
        session = _make_session(db_session, project)
        tools = _build_tools(db_session, project, session)

        for name in (
            "generate_presentation_tool",
            "generate_word_document_tool",
            "generate_pdf_report_tool",
            "revise_artifact_tool",
        ):
            assert name not in tools

    def test_present_when_flag_is_on(self, db_session, make_project):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)
        tools = _build_tools(db_session, project, session)

        assert {
            "generate_presentation_tool",
            "generate_word_document_tool",
            "generate_pdf_report_tool",
            "revise_artifact_tool",
        }.issubset(tools)

    async def test_generate_presentation_tool_persists_artifact_and_links_message(
        self, db_session, make_project, monkeypatch
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        pptx_mock = AsyncMock(
            return_value=ArtifactFile(path="/tmp/x.pptx", filename="x.pptx", size_bytes=42)
        )
        monkeypatch.setattr(chat_agent_module, "generate_pptx", pptx_mock)

        tools = _build_tools(db_session, project, session)
        result = await tools["generate_presentation_tool"].ainvoke(
            {"title": "Deck", "slides": [{"heading": "Intro", "bullets": ["a", "b"]}]}
        )

        assert "Deck" in result
        pptx_mock.assert_awaited_once()
        outline = pptx_mock.await_args.args[0]
        assert outline.title == "Deck"
        assert outline.slides[0].heading == "Intro"

        tool_row = next(m for m in session.messages if m.role == "tool")
        assert tool_row.artifact_id is not None
        artifact = db_session.query(Artifact).filter_by(id=tool_row.artifact_id).one()
        assert artifact.format == "pptx"
        assert artifact.title == "Deck"
        assert artifact.size_bytes == 42

    async def test_generate_word_document_tool_persists_artifact(
        self, db_session, make_project, monkeypatch
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        docx_mock = AsyncMock(
            return_value=ArtifactFile(path="/tmp/x.docx", filename="x.docx", size_bytes=7)
        )
        monkeypatch.setattr(chat_agent_module, "generate_docx", docx_mock)

        tools = _build_tools(db_session, project, session)
        await tools["generate_word_document_tool"].ainvoke(
            {"title": "Report", "sections": [{"heading": "Overview", "body": "Text."}]}
        )

        docx_mock.assert_awaited_once()
        tool_row = next(m for m in session.messages if m.role == "tool")
        artifact = db_session.query(Artifact).filter_by(id=tool_row.artifact_id).one()
        assert artifact.format == "docx"

    async def test_generate_pdf_report_tool_uses_completed_study_when_available(
        self, db_session, make_project, monkeypatch
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        from app.models import StudyResult

        study = StudyResult(
            project_id=project.id, status="completed", title="T",
            sections={"executive_summary": {"data": {"verdict": "proceed"}}},
        )
        db_session.add(study)
        db_session.commit()
        db_session.refresh(project)

        pdf_mock = AsyncMock(
            return_value=ArtifactFile(path="/tmp/x.pdf", filename="x.pdf", size_bytes=99)
        )
        export_mock = AsyncMock()
        monkeypatch.setattr(chat_agent_module, "generate_pdf", pdf_mock)
        monkeypatch.setattr(chat_agent_module, "synthesize_chat_export", export_mock)

        tools = _build_tools(db_session, project, session)
        await tools["generate_pdf_report_tool"].ainvoke({"title": "Report"})

        pdf_mock.assert_awaited_once()
        # A completed study exists — the cheaper deterministic renderer must
        # be used, never the LLM-synthesis fallback.
        export_mock.assert_not_awaited()

    async def test_generate_tool_failure_is_reported_without_persisting_artifact(
        self, db_session, make_project, monkeypatch
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        pptx_mock = AsyncMock(side_effect=ArtifactGenerationError("service unavailable"))
        monkeypatch.setattr(chat_agent_module, "generate_pptx", pptx_mock)

        tools = _build_tools(db_session, project, session)
        result = await tools["generate_presentation_tool"].ainvoke(
            {"title": "Deck", "slides": [{"heading": "Intro", "bullets": ["a"]}]}
        )

        assert "failed" in result.lower()
        assert db_session.query(Artifact).count() == 0
        tool_row = next(m for m in session.messages if m.role == "tool")
        assert tool_row.artifact_id is None

    async def test_revise_artifact_tool_defaults_to_most_recent_artifact(
        self, db_session, make_project, monkeypatch
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        original = Artifact(
            project_id=project.id, format="pptx", title="Deck", filename="a.pptx",
            storage_path="/tmp/a.pptx", size_bytes=10,
            spec_json={"title": "Deck", "slides": [{"heading": "Intro", "bullets": ["a"]}]},
        )
        db_session.add(original)
        db_session.commit()

        revise_mock = AsyncMock(
            return_value=(
                ArtifactFile(path="/tmp/b.pptx", filename="b.pptx", size_bytes=20),
                {"title": "Deck", "slides": [{"heading": "Intro (shorter)", "bullets": ["a"]}]},
            )
        )
        monkeypatch.setattr(chat_agent_module, "run_artifact_revision", revise_mock)

        tools = _build_tools(db_session, project, session)
        await tools["revise_artifact_tool"].ainvoke({"instructions": "make it shorter"})

        revise_mock.assert_awaited_once()
        assert revise_mock.await_args.args[0].id == original.id
        new_artifact = (
            db_session.query(Artifact).filter(Artifact.id != original.id).one()
        )
        assert new_artifact.parent_artifact_id == original.id
        assert new_artifact.filename == "b.pptx"

    async def test_revise_artifact_tool_with_no_prior_artifact_reports_gracefully(
        self, db_session, make_project
    ):
        app.config.get_settings().mcp_artifacts_enabled = True
        project = make_project()
        session = _make_session(db_session, project)

        tools = _build_tools(db_session, project, session)
        result = await tools["revise_artifact_tool"].ainvoke({"instructions": "make it shorter"})

        assert "no previously generated" in result.lower()
