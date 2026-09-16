"""Middleware wiring detect_single_tool_intent's per-turn tool restriction
into the chat Deep Agent — reproduces today's `llm.bind_tools([...])`
branching (see chat_agent.py's legacy path) at the middleware layer instead
of pre-binding the model, since a deep agent's tool list is fixed at graph-
construction time otherwise."""

from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse


class ToolIntentRestrictionMiddleware(AgentMiddleware):
    """`restricted` is the precomputed result of detect_single_tool_intent():
    "none" (no tools this turn), a specific tool name (only that tool), or
    None (no restriction — every tool stays available)."""

    def __init__(self, restricted: str | None, tool_by_name: dict) -> None:
        super().__init__()
        self._restricted = restricted
        self._tool_by_name = tool_by_name

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        if self._restricted == "none":
            request.tools = []
        elif self._restricted:
            restricted_tool = self._tool_by_name.get(self._restricted)
            if restricted_tool is not None:
                request.tools = [restricted_tool]
        return await handler(request)
