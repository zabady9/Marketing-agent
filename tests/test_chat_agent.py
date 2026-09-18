"""
Integration tests for app/services/chat_agent.py::run_chat_turn — no test
exercised this function before this migration. Covers the Deep Agent code
path (settings.deepagents_enabled=True): a plain-text reply, a tool-call
round with correct persistence, and the call-limit fallback that replaces
the legacy MAX_TOOL_ROUNDS cap. Uses a fake chat model (no real LLM/network).
"""

import app.config
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import app.services.chat_agent as chat_agent_module
from app.models import ChatMessage, ChatSession, StudyResult
from app.sse import EventQueue


@pytest.fixture(autouse=True)
def _reset_settings_after():
    yield
    app.config._settings = None


async def _noop_tool_intent(*args, **kwargs):
    return None


class _FakePlainReplyModel(BaseChatModel):
    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-plain-reply"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Hello there!"))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class _FakeToolCallThenReplyModel(BaseChatModel):
    """Turn 1: calls remember_fact_tool. Turn 2: plain text reply."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-then-reply"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "remember_fact_tool", "args": {"content": "likes tea"}, "id": "c1"}],
            )
        else:
            msg = AIMessage(content="Noted, I'll remember that about you.")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class _FakeNarrationThenSilentModel(BaseChatModel):
    """Turn 1: narration text AND a tool_call in the SAME message (e.g.
    explaining a result while also calling generate_chart_tool). Turn 2:
    only a trailing newline, no tool_calls — the graph ends with nothing
    substantive left to say. This reproduces the real Gemini behavior
    observed live (a lone "\\n" final round after a successful tool call)
    that used to beat a genuinely good last_text because "\\n" is truthy in
    Python even though it's not real content."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-narration-then-silent"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            msg = AIMessage(
                content="Here's the scenario comparison.",
                tool_calls=[{"name": "remember_fact_tool", "args": {"content": "noted"}, "id": "c1"}],
            )
        else:
            msg = AIMessage(content="\n")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class _FakeMultiRoundNarrationModel(BaseChatModel):
    """Reproduces the real sequence observed live: rich narration + a tool
    call, then a short remark + another tool call (e.g. a retry), then a
    final round that's whitespace-only. The rich turn-1 narration is NOT
    the last round with real content — turn-2's short remark is — so a
    fallback that only keeps "the last non-whitespace round" would still
    lose turn-1's narration. Both must survive in the final answer."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-multi-round-narration"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            msg = AIMessage(
                content="Raising your price to 126 improves ROI and NPV substantially.",
                tool_calls=[{"name": "remember_fact_tool", "args": {"content": "noted"}, "id": "c1"}],
            )
        elif self._turn == 1:
            self._turn += 1
            msg = AIMessage(
                content="Here is the chart.",
                tool_calls=[{"name": "remember_fact_tool", "args": {"content": "noted again"}, "id": "c2"}],
            )
        else:
            msg = AIMessage(content="\n")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class _FakeNeverFinalizesModel(BaseChatModel):
    """Always replies with plain text but is scripted to look like it never
    settles — used to force the call-limit path deterministically by setting
    a very low chat_model_call_limit in the test itself."""

    _bound_tools: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-never-finalizes"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        msg = AIMessage(
            content="",
            tool_calls=[{"name": "remember_fact_tool", "args": {"content": "keeps going"}, "id": "loop"}],
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _make_session(db_session, project) -> ChatSession:
    session = ChatSession(project_id=project.id)
    db_session.add(session)
    db_session.commit()
    return session


class TestChatTurnDeepAgentPath:
    async def test_plain_reply_completes_with_no_tool_calls(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakePlainReplyModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(db_session, project, session, "hi", EventQueue())

        assert result.status == "complete"
        assert result.content == "Hello there!"

    async def test_tool_call_round_persists_tool_message_and_memory(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeToolCallThenReplyModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "I like tea, remember that", EventQueue()
        )

        assert result.status == "complete"
        assert result.content == "Noted, I'll remember that about you."

        tool_rows = [m for m in session.messages if m.role == "tool"]
        assert len(tool_rows) == 1
        assert tool_rows[0].tool_name == "remember_fact_tool"

        from app.models import MemoryEntry

        entries = db_session.query(MemoryEntry).all()
        assert any(e.content == "likes tea" for e in entries)

    async def test_narration_with_trailing_tool_call_survives_a_silent_final_round(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeNarrationThenSilentModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "simulate something", EventQueue()
        )

        assert result.status == "complete"
        assert result.content == "Here's the scenario comparison."

    async def test_narration_spread_across_multiple_tool_rounds_is_not_lost(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeMultiRoundNarrationModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "simulate something", EventQueue()
        )

        assert result.status == "complete"
        assert "Raising your price to 126 improves ROI and NPV substantially." in result.content
        assert "Here is the chart." in result.content

    async def test_call_limit_breach_falls_back_gracefully(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        settings = app.config.get_settings()
        settings.deepagents_enabled = True
        settings.chat_model_call_limit = 2  # force the limit to bite quickly

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeNeverFinalizesModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "keep going forever", EventQueue()
        )

        assert result.status == "complete"
        assert result.content == chat_agent_module._FALLBACK_MESSAGE


class TestChatTurnLegacyPath:
    async def test_plain_reply_completes_with_no_tool_calls(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = False

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakePlainReplyModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(db_session, project, session, "hi", EventQueue())

        assert result.status == "complete"
        assert result.content == "Hello there!"

    async def test_narration_spread_across_multiple_tool_rounds_is_not_lost(
        self, db_session, make_project, monkeypatch
    ):
        """This is the code path actually used in production —
        settings.deepagents_enabled defaults to False and nothing in .env
        overrides it — so this is the real-world regression test for the
        "good answer disappears on refresh" bug: each round in
        _run_legacy_tool_loop used to overwrite assistant_message.content
        outright (lines flushing `_extract_text(response.content)` per
        round), discarding any earlier round's narration the moment a later
        round ran, however short (e.g. a one-line "let me try again" after
        a tool validation error, or a plain retry)."""
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = False

        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeMultiRoundNarrationModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "simulate something", EventQueue()
        )

        assert result.status == "complete"
        assert "Raising your price to 126 improves ROI and NPV substantially." in result.content
        assert "Here is the chart." in result.content


class _FakeToolCallThenPlainReplyModel(BaseChatModel):
    """Turn 1: calls run_market_sizing_tool. Turn 2: plain text reply. Used
    to exercise a tool whose body fails with a real DB error."""

    _bound_tools: list = []
    _turn: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-phase-tool-then-reply"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._turn == 0:
            self._turn += 1
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "run_market_sizing_tool", "args": {}, "id": "c1"}],
            )
        else:
            msg = AIMessage(content="Here's what happened.")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


class TestChatTurnDbFailureRecovery:
    """Regression test for a real bug: a DB write failing INSIDE a tool call
    (e.g. an IntegrityError on flush) leaves the SQLAlchemy session in a
    pending-rollback state. Any subsequent ORM attribute access (including
    logging `project.id`) before an explicit db.rollback() raises
    PendingRollbackError itself — masking the real error and crashing the
    whole turn instead of degrading gracefully. Every rollback/log-with-
    plain-project_id fix in chat_agent.py exists to prevent this."""

    async def test_db_failure_inside_a_tool_body_degrades_gracefully(
        self, db_session, make_project, monkeypatch
    ):
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        app.config._settings = None
        app.config.get_settings().deepagents_enabled = True

        async def _broken_run_single_phase_study(db, project, phase, queue):
            # A real flush failure (NOT NULL violation), exactly like the
            # sqlite3.OperationalError hit in production when a migration
            # hadn't been applied yet — this leaves db's session needing an
            # explicit rollback before any further ORM use will succeed.
            db.add(StudyResult(project_id=None))
            db.commit()

        monkeypatch.setattr(chat_agent_module, "run_single_phase_study", _broken_run_single_phase_study)
        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: _FakeToolCallThenPlainReplyModel())
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)

        project = make_project()
        session = _make_session(db_session, project)

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "just check the market", EventQueue()
        )

        # The turn must complete (not crash/raise), and the tool's DB error
        # must be reflected as an ordinary error-result tool message rather
        # than corrupting the whole session.
        assert result.status == "complete"
        assert result.content == "Here's what happened."

        tool_rows = [m for m in session.messages if m.role == "tool"]
        assert len(tool_rows) == 1
        assert "Error running run_market_sizing_tool" in tool_rows[0].content
