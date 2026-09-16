"""
Tests for generate_chart_tool (app/services/chat_agent.py): the chat agent's
tool for attaching an actual chart to a reply instead of only describing
numbers in text. Covers persistence (ChatMessage.chart_data), the live
CHAT_CHART_READY SSE push, and graceful degradation on invalid chart args.
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import app.services.chat_agent as chat_agent_module
from app.models import ChatSession
from app.sse import EventQueue, SSEEvent


@pytest.fixture(autouse=True)
def _reset_settings_after():
    yield
    app.config._settings = None


async def _noop_tool_intent(*args, **kwargs):
    return None


class _CapturingEventQueue(EventQueue):
    def __init__(self):
        super().__init__()
        self.events: list[tuple[SSEEvent, dict]] = []

    async def put(self, event: SSEEvent, data: dict) -> None:
        self.events.append((event, data))
        await super().put(event, data)


def _make_session(db_session, project) -> ChatSession:
    session = ChatSession(project_id=project.id)
    db_session.add(session)
    db_session.commit()
    return session


class _FakeChartToolModel(BaseChatModel):
    """Turn 1: calls generate_chart_tool with the given args. Turn 2: plain
    text reply."""

    _bound_tools: list = []
    _turn: int = 0

    def __init__(self, chart_args: dict):
        super().__init__()
        self._chart_args = chart_args

    @property
    def _llm_type(self) -> str:
        return "fake-chart-tool"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "generate_chart_tool", "args": self._chart_args, "id": "c1"}],
            )
        else:
            msg = AIMessage(content="Here's the comparison, with a chart.")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


_VALID_CHART_ARGS = {
    "chart_type": "bar",
    "title": "TAM vs SAM vs SOM",
    "categories": ["TAM", "SAM", "SOM"],
    "series": [{"name": "USD", "data": [5_000_000, 1_000_000, 200_000]}],
    "x_label": None,
    "y_label": "USD",
}


class TestGenerateChartTool:
    async def test_valid_chart_is_persisted_and_pushed_live(self, db_session, make_project, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeChartToolModel(_VALID_CHART_ARGS))
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)
        queue = _CapturingEventQueue()

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "compare TAM SAM SOM as a chart", queue
        )

        assert result.status == "complete"
        assert result.content == "Here's the comparison, with a chart."

        tool_rows = [m for m in session.messages if m.role == "tool"]
        assert len(tool_rows) == 1
        assert tool_rows[0].tool_name == "generate_chart_tool"
        assert tool_rows[0].chart_data is not None
        assert tool_rows[0].chart_data["chart_type"] == "bar"
        assert tool_rows[0].chart_data["categories"] == ["TAM", "SAM", "SOM"]
        assert tool_rows[0].chart_data["series"][0]["data"] == [5_000_000, 1_000_000, 200_000]

        chart_events = [data for event, data in queue.events if event == SSEEvent.CHAT_CHART_READY]
        assert len(chart_events) == 1
        assert chart_events[0]["tool_name"] == "generate_chart_tool"
        assert chart_events[0]["chart"]["title"] == "TAM vs SAM vs SOM"

    async def test_mismatched_series_length_degrades_gracefully(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        bad_args = {
            "chart_type": "bar",
            "title": "Broken",
            "categories": ["A", "B", "C"],
            "series": [{"name": "x", "data": [1, 2]}],  # only 2 values for 3 categories
        }
        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeChartToolModel(bad_args))
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)
        queue = _CapturingEventQueue()

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "chart this", queue
        )

        # The turn still completes normally — an invalid chart degrades to a
        # plain error-result tool message, it never crashes the whole turn.
        assert result.status == "complete"

        tool_rows = [m for m in session.messages if m.role == "tool"]
        assert len(tool_rows) == 1
        assert tool_rows[0].chart_data is None
        assert not [e for e, _ in queue.events if e == SSEEvent.CHAT_CHART_READY]
