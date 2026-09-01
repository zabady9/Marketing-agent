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


async def gather_searches_with_sse(
    queue: "EventQueue",
    study_id: str,
    agent: AgentName | str,
    queries: "list[str]",
    api_key: str,
    max_results: int = 5,
) -> "list[SearchResult]":
    """Fire all `queries` concurrently via search_with_sse, isolating per-query
    failures (a failed query just logs a warning and contributes no results,
    same behavior as the old sequential-loop version this replaces). Safe to
    parallelize because app.tools.web_search's semaphore(2) is the real Tavily
    rate limiter, not each agent's own call ordering — this only removes
    artificial staggering, it doesn't raise Tavily request volume."""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    results_or_errors = await asyncio.gather(
        *(search_with_sse(queue, study_id, agent, q, api_key, max_results=max_results) for q in queries),
        return_exceptions=True,
    )

    from app.sse import SSEEvent

    all_results: list = []
    for query, item in zip(queries, results_or_errors):
        if isinstance(item, BaseException):
            logger.warning("%s search failed for %r: %s", agent, query, item)
            await queue.put(
                SSEEvent.AGENT_WARNING,
                {"agent": agent, "study_id": study_id, "warning": f"Search failed: {item}"},
            )
        else:
            all_results.extend(item)
    return all_results
