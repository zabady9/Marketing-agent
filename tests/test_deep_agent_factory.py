"""
Unit tests for app/agents/deep_agent_factory.py's run_structured_deep_agent —
the one shared entry point every phase agent routes its Deep Agent calls
through. Uses a hand-rolled fake BaseChatModel (no network, no real LLM) that
scripts tool-call behavior directly, so these exercise the real
create_deep_agent/LangGraph machinery without any external dependency.
"""

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

from app.agents.deep_agent_factory import DeepAgentPhaseError, run_structured_deep_agent


class _Out(BaseModel):
    value: int
    note: str


class _FakeToolCallingModel(BaseChatModel):
    """Binds whatever tools it's given and, on each call, invokes a scripted
    callback to decide how to respond — lets each test script the exact
    sequence of tool calls / plain-text replies it wants to exercise."""

    _bound_tools: list = []
    _script: list

    def __init__(self, script):
        super().__init__()
        self._script = list(script)
        self._call_index = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools, **kwargs):
        self._bound_tools = list(tools)
        return self

    def _respond(self):
        if self._call_index >= len(self._script):
            # Script exhausted — keep repeating the last scripted response so
            # a call-limit test can run past a fixed limit deterministically.
            step = self._script[-1]
        else:
            step = self._script[self._call_index]
        self._call_index += 1
        return step(self)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._respond())])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


def _call_structured_tool(args: dict):
    def step(model: _FakeToolCallingModel) -> AIMessage:
        target = next(t for t in model._bound_tools if t.name == "_Out")
        return AIMessage(content="", tool_calls=[{"name": target.name, "args": args, "id": "call_1"}])

    return step


def _plain_text(text: str):
    def step(_model: _FakeToolCallingModel) -> AIMessage:
        return AIMessage(content=text)

    return step


class TestHappyPath:
    async def test_valid_tool_call_returns_validated_output(self):
        model = _FakeToolCallingModel([_call_structured_tool({"value": 42, "note": "hi"})])
        out = await run_structured_deep_agent(
            model=model, tools=[], system_prompt="test", human_message="go", output_schema=_Out,
        )
        assert out == _Out(value=42, note="hi")


class TestSilentNoneCase:
    async def test_plain_text_with_no_tool_call_raises_instead_of_silently_succeeding(self):
        # This is the critical regression case: LangChain's create_agent does
        # NOT treat "model never called the structured-output tool" as an
        # error on its own — structured_response just stays None and the
        # graph completes "successfully". run_structured_deep_agent must
        # catch this itself.
        model = _FakeToolCallingModel([_plain_text("just chatting, no tool calls")])
        with pytest.raises(DeepAgentPhaseError, match="without producing a structured response"):
            await run_structured_deep_agent(
                model=model, tools=[], system_prompt="test", human_message="go",
                output_schema=_Out, model_call_limit=3, tool_call_limit=10,
            )


class TestCallLimits:
    async def test_model_that_never_finalizes_hits_the_call_limit_deterministically(self):
        # A model that keeps replying with plain text forever must not hang
        # or burn through deepagents' internal recursion_limit=9999 — the
        # bounded ModelCallLimitMiddleware must cut it off quickly.
        model = _FakeToolCallingModel([_plain_text("thinking...")])
        with pytest.raises(DeepAgentPhaseError):
            await run_structured_deep_agent(
                model=model, tools=[], system_prompt="test", human_message="go",
                output_schema=_Out, model_call_limit=2, tool_call_limit=10,
            )
