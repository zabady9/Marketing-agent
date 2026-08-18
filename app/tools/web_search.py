"""
Tavily web search wrapper with exponential backoff.

Returns a list of SearchResult objects, each carrying a URL, title, and snippet
that agents use for citations. Serializes concurrent calls when the dev-tier
rate limit is approached (max_concurrent=2).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from tavily import AsyncTavilyClient

logger = logging.getLogger(__name__)

# Dev-tier Tavily allows ~1 req/s; this semaphore prevents bursting.
_semaphore = asyncio.Semaphore(2)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5  # seconds


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float = 0.0
    raw_content: str | None = field(default=None, repr=False)


async def search(
    query: str,
    api_key: str,
    *,
    max_results: int = 5,
    search_depth: str = "advanced",
) -> list[SearchResult]:
    """
    Run a single Tavily search with retry + backoff.
    Raises RuntimeError after max retries.
    """
    client = AsyncTavilyClient(api_key=api_key)
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES):
        try:
            async with _semaphore:
                response = await client.search(
                    query=query,
                    max_results=max_results,
                    search_depth=search_depth,
                    include_raw_content=False,
                )
            results = [
                SearchResult(
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("content", ""),
                    score=r.get("score", 0.0),
                )
                for r in response.get("results", [])
            ]
            if not results:
                logger.warning("Tavily returned 0 results for query: %r", query)
            return results

        except Exception as exc:
            last_exc = exc
            wait = _BACKOFF_BASE ** attempt
            logger.warning(
                "Tavily search attempt %d/%d failed (%s). Retrying in %.1fs…",
                attempt + 1,
                _MAX_RETRIES,
                exc,
                wait,
            )
            await asyncio.sleep(wait)

    raise RuntimeError(
        f"Tavily search failed after {_MAX_RETRIES} attempts: {last_exc}"
    ) from last_exc


async def estimate_budget_benchmarks(
    business_description: str,
    geography: str,
    business_model: str,
    api_key: str,
) -> dict[str, float | None]:
    """
    Run three parallel searches to estimate capex, monthly opex, and year-1 monthly
    sales benchmarks for a business that omitted these figures.
    Returns {'capex': float|None, 'opex_monthly': float|None, 'monthly_sales': float|None}.

    Called by IntakeFeasibilityAgent. Results are tagged source='estimated',
    low_confidence=True by the caller.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI
    from pydantic import BaseModel as _BaseModel

    from app.config import get_settings

    s = get_settings()

    capex_query = (
        f"typical startup capex initial investment cost {business_model} "
        f"business {geography} USD range"
    )
    opex_query = (
        f"typical monthly operating expenses {business_model} "
        f"small business {geography} USD range"
    )
    sales_query = (
        f"typical year 1 monthly customer count sales volume {business_model} "
        f"startup {geography} realistic"
    )

    capex_results, opex_results, sales_results = await asyncio.gather(
        search(capex_query, api_key, max_results=3),
        search(opex_query, api_key, max_results=3),
        search(sales_query, api_key, max_results=3),
    )

    capex_context = "\n".join(f"- {r.snippet}" for r in capex_results[:3]) or "No data found."
    opex_context = "\n".join(f"- {r.snippet}" for r in opex_results[:3]) or "No data found."
    sales_context = "\n".join(f"- {r.snippet}" for r in sales_results[:3]) or "No data found."

    class _Estimates(_BaseModel):
        capex_usd: float | None = None
        opex_monthly_usd: float | None = None
        monthly_sales_units: float | None = None

    llm = ChatGoogleGenerativeAI(
        model=s.cheap_model,
        google_api_key=s.google_api_key,
        temperature=0,
    )
    structured = llm.with_structured_output(_Estimates)

    estimates: _Estimates = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You are a financial analyst. "
                    "Given web search results about typical startup benchmarks, "
                    "extract a single conservative midpoint estimate for each metric. "
                    "monthly_sales_units is the expected number of paying customers / "
                    "transactions / units sold per month in year 1 of a new startup. "
                    "Return null for any metric where the data is too vague to estimate."
                )
            ),
            HumanMessage(
                content=(
                    f"Business: {business_description}\n"
                    f"Geography: {geography}\n"
                    f"Model: {business_model}\n\n"
                    f"Capex search results:\n{capex_context}\n\n"
                    f"Monthly Opex search results:\n{opex_context}\n\n"
                    f"Year-1 monthly sales search results:\n{sales_context}"
                )
            ),
        ]
    )

    return {
        "capex": estimates.capex_usd,
        "opex_monthly": estimates.opex_monthly_usd,
        "monthly_sales": estimates.monthly_sales_units,
    }
