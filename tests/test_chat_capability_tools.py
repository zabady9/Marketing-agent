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

import app.services.chat_agent as chat_agent_module
from app.models import ChatMessage, ChatSession
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
