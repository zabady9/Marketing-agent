"""Shared Deep Agent tool/middleware builders reused across the 3 iterative
research phases (Market Sizing, Competitive Analysis, Risk Assessment)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.tools import tool

if TYPE_CHECKING:
    from app.agents.base import AgentName
    from app.sse import EventQueue
    from app.tools.web_search import SearchResult


def make_tavily_search_tool(
    queue: "EventQueue",
    study_id: str,
    agent_name: "AgentName | str",
    api_key: str,
    all_results: "list[SearchResult]",
):
    """Builds a `tavily_search` tool for one phase's Deep Agent run. `all_results`
    is the SAME mutable list the phase pre-populated with its upfront batch of
    canonical searches — every call this tool makes appends to it, and the
    numbered context returned always starts counting at `len(all_results)` at
    call time. This is what keeps a later `citation_index` (chosen by the LLM
    from the full numbered list, upfront + mid-loop) resolvable against a
    stable position in the same list the anti-hallucination guard checks —
    the guard itself lives entirely outside the agent loop and needs no
    changes to keep working against results fetched this way."""

    from app.agents.base import search_with_sse

    @tool
    async def tavily_search(query: str) -> str:
        """Run one additional web search when a gap remains after the initial
        research (e.g. a figure has no citation yet, or confidence is low).
        Only call this for a specific, targeted gap — not to re-run searches
        that already returned results."""
        start_idx = len(all_results)
        new_results = await search_with_sse(queue, study_id, agent_name, query, api_key, max_results=5)
        all_results.extend(new_results)
        if not new_results:
            return "No results found for this query."
        return "\n\n".join(
            f"[{start_idx + i}] TITLE: {r.title}\n    URL: {r.url}\n    SNIPPET: {r.snippet}"
            for i, r in enumerate(new_results)
        )

    return tavily_search


class TodoSSEMiddleware(AgentMiddleware):
    """Forwards a Deep Agent's write_todos state to the frontend via SSE
    whenever it changes, so a "here's the plan" UI can render it. Purely
    additive/observational — never touches control flow."""

    def __init__(self, queue: "EventQueue", study_id: str, agent_name: "AgentName | str") -> None:
        super().__init__()
        self._queue = queue
        self._study_id = study_id
        self._agent_name = agent_name

    async def aafter_model(self, state, runtime) -> dict | None:
        from app.sse import SSEEvent

        todos = state.get("todos")
        if todos:
            await self._queue.put(
                SSEEvent.AGENT_PLAN_UPDATED,
                {"agent": self._agent_name, "study_id": self._study_id, "todos": todos},
            )
        return None
