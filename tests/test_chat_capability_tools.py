"""
Tests for the chat tools in app/services/chat_agent.py::_build_tools — the
single analysis tool (every analysis goes through run_analysis_tool),
explain_figure_tool over report blocks, the what-if scenario tool, and the
artifact-generation tools. No real LLM or network calls.
"""

from unittest.mock import AsyncMock

import app.config
import app.services.chat_agent as chat_agent_module
from app.models import Artifact, ChatMessage, ChatSession
from app.services.artifact_generation import ArtifactFile, ArtifactGenerationError
from app.analysis.engine import AnalysisRun
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


def _report(blocks: list[dict]) -> dict:
    return {
        "title": "Feasibility of the coffee subscription",
        "steps": [
            {"id": "s1", "title": "Unit economics", "status": "completed", "summary": "Break-even in 8 months.",
             "blocks": blocks},
        ],
    }


class TestRunAnalysisTool:
    async def test_passes_goal_name_and_scope_through_and_links_the_study(
        self, db_session, make_project, monkeypatch
    ):
        project = make_project()
        session = _make_session(db_session, project)
        run_mock = AsyncMock(
            return_value=AnalysisRun(study_id="study-c", status="completed", title="SWOT", answer="Go niche.", error=None)
        )
        monkeypatch.setattr(chat_agent_module, "run_analysis", run_mock)

        tools = _build_tools(db_session, project, session)
        content = await tools["run_analysis_tool"].ainvoke(
            {"goal": "find strengths", "analysis_name": "SWOT", "comprehensive": True}
        )

        assert run_mock.await_args.args[1:4] == (project.id, "find strengths", "SWOT")
        assert run_mock.await_args.kwargs["comprehensive"] is True
        assert "Go niche." in content
        assert session.messages[-1].study_id == "study-c"

    async def test_failed_run_returns_summary_instead_of_raising(self, db_session, make_project, monkeypatch):
        project = make_project()
        session = _make_session(db_session, project)
        run_mock = AsyncMock(
            return_value=AnalysisRun(study_id="study-d", status="failed", title=None, answer=None, error="quota")
        )
        monkeypatch.setattr(chat_agent_module, "run_analysis", run_mock)

        tools = _build_tools(db_session, project, session)
        content = await tools["run_analysis_tool"].ainvoke({"goal": "can I compete?"})

        assert run_mock.await_args.args[3] is None
        assert "failed: quota" in content

    async def test_links_the_run_to_the_chat_at_start_then_finishes_the_same_row(
        self, db_session, make_project, monkeypatch
    ):
        project = make_project()
        session = _make_session(db_session, project)
        seen_mid_run: list[tuple[str, str | None]] = []

        async def _fake_run(db, project_id, goal, analysis_name=None, queue=None, *, on_started=None, **kw):
            on_started("study-live")
            # While the run is going, a refreshed page must already find the link.
            rows = [m for m in session.messages if m.role == "tool"]
            seen_mid_run.extend((m.status, m.study_id) for m in rows)
            return AnalysisRun(study_id="study-live", status="completed", title="T", answer="A", error=None)

        monkeypatch.setattr(chat_agent_module, "run_analysis", _fake_run)
        tools = _build_tools(db_session, project, session)
        await tools["run_analysis_tool"].ainvoke({"goal": "g"})

        assert seen_mid_run == [("pending", "study-live")]
        tool_rows = [m for m in session.messages if m.role == "tool"]
        assert len(tool_rows) == 1
        assert (tool_rows[0].status, tool_rows[0].study_id) == ("complete", "study-live")
        assert "A" in tool_rows[0].content

    def test_no_hard_coded_feasibility_tools_remain(self, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)
        names = set(_build_tools(db_session, project, session))
        assert "run_analysis_tool" in names
        assert not {n for n in names if "feasibility" in n or n.startswith("run_market") or "synthesis" in n}


class TestExplainFigureTool:
    async def test_finds_the_block_that_mentions_the_figure(self, db_session, make_project):
        from app.models import StudyResult

        project = make_project()
        session = _make_session(db_session, project)
        db_session.add(
            StudyResult(
                project_id=project.id, status="completed", title="Coffee", goal="g",
                report=_report([
                    {"type": "stats", "items": [{"label": "Break-even", "value": "8", "unit": "months", "basis": "calculated"}],
                     "citations": []},
                    {"type": "text", "markdown": "Unrelated narrative."},
                ]),
            )
        )
        db_session.commit()
        db_session.refresh(project)

        tools = _build_tools(db_session, project, session)
        content = await tools["explain_figure_tool"].ainvoke({"figure_description": "break-even"})

        assert "Unit economics" in content
        assert "calculated" in content
        assert "Unrelated narrative" not in content

    async def test_reports_available_steps_when_nothing_matches(self, db_session, make_project):
        from app.models import StudyResult

        project = make_project()
        session = _make_session(db_session, project)
        db_session.add(StudyResult(project_id=project.id, status="completed", title="Coffee", report=_report([])))
        db_session.commit()
        db_session.refresh(project)

        tools = _build_tools(db_session, project, session)
        content = await tools["explain_figure_tool"].ainvoke({"figure_description": "NPV"})

        assert "Couldn't find" in content
        assert "Unit economics" in content


class TestScenarioToolAfterMove:
    async def test_runs_on_the_relocated_financial_model(self, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)
        tools = _build_tools(db_session, project, session)

        content = await tools["run_scenario_simulation_tool"].ainvoke({"unit_price": 20.0})

        assert "Error running" not in content


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
            report=_report([{"type": "text", "markdown": "Looks good."}]),
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
