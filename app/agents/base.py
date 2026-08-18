from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.sse import EventQueue
    from app.tools.web_search import SearchResult


class AgentName(StrEnum):
    INTAKE = "intake"
    MARKET_SIZING = "market_sizing"
    COMPETITIVE = "competitive"
    FINANCIAL = "financial"
    RISK = "risk"
    SYNTHESIS = "synthesis"
    CITATION_QC = "citation_qc"


class AgentSoftError(Exception):
    """Non-fatal agent failure. Pipeline continues; section marked unavailable."""


async def search_with_sse(
    queue: "EventQueue",
    study_id: str,
    agent: AgentName | str,
    query: str,
    api_key: str,
    max_results: int = 5,
) -> "list[SearchResult]":
    """Run one Tavily search, emitting search_query_sent / search_results_received."""
    from app.sse import SSEEvent
    from app.tools.web_search import search

    await queue.put(
        SSEEvent.SEARCH_QUERY_SENT,
        {"agent": agent, "study_id": study_id, "query": query},
    )
    results = await search(query, api_key, max_results=max_results)
    await queue.put(
        SSEEvent.SEARCH_RESULTS_RECEIVED,
        {
            "agent": agent,
            "study_id": study_id,
            "n_results": len(results),
            "top_urls": [r.url for r in results[:3]],
        },
    )
    return results
