"""
Unit tests for app/services/chat_middleware.py::ToolIntentRestrictionMiddleware
— reproduces today's llm.bind_tools([...]) branching at the middleware layer.
No LLM, no graph — just the middleware's tool-list mutation logic in isolation.
"""

from types import SimpleNamespace

from app.services.chat_middleware import ToolIntentRestrictionMiddleware


def _tool(name: str):
    return SimpleNamespace(name=name)


async def _handler(request):
    return request.tools


class TestToolIntentRestrictionMiddleware:
    async def test_none_restriction_leaves_tools_untouched(self):
        tools = [_tool("a"), _tool("b")]
        tool_by_name = {"a": tools[0], "b": tools[1]}
        middleware = ToolIntentRestrictionMiddleware(None, tool_by_name)
        request = SimpleNamespace(tools=tools)

        result = await middleware.awrap_model_call(request, _handler)

        assert result == tools

    async def test_no_tools_restriction_clears_the_tool_list(self):
        tools = [_tool("a"), _tool("b")]
        tool_by_name = {"a": tools[0], "b": tools[1]}
        middleware = ToolIntentRestrictionMiddleware("none", tool_by_name)
        request = SimpleNamespace(tools=tools)

        result = await middleware.awrap_model_call(request, _handler)

        assert result == []

    async def test_single_tool_restriction_narrows_to_just_that_tool(self):
        tools = [_tool("a"), _tool("b")]
        tool_by_name = {"a": tools[0], "b": tools[1]}
        middleware = ToolIntentRestrictionMiddleware("b", tool_by_name)
        request = SimpleNamespace(tools=tools)

        result = await middleware.awrap_model_call(request, _handler)

        assert result == [tools[1]]

    async def test_unknown_restricted_name_falls_back_to_leaving_tools_untouched(self):
        # Defensive: detect_single_tool_intent already guards against a
        # hallucinated tool name, but the middleware itself must not crash
        # or silently produce an empty tool list if one ever slips through.
        tools = [_tool("a"), _tool("b")]
        tool_by_name = {"a": tools[0], "b": tools[1]}
        middleware = ToolIntentRestrictionMiddleware("nonexistent_tool", tool_by_name)
        request = SimpleNamespace(tools=tools)

        result = await middleware.awrap_model_call(request, _handler)

        assert result == tools
