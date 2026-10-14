"""Web research for one unit of work (the method search, or one step).

Results are numbered in the order they arrive, and that numbering is what
blocks cite through `citation_indices`. Duplicate URLs keep their first number.
"""

from __future__ import annotations

import asyncio
import logging

from app.tools import web_search
from app.tools.web_search import SearchResult

logger = logging.getLogger(__name__)

_RAW_CHARS = 1500


class RunCounters:
    """Per-run cost counters, shared by every Research of one analysis."""

    def __init__(self) -> None:
        self.searches = 0


class Research:
    def __init__(self, api_key: str, counters: RunCounters, *, max_results: int = 4) -> None:
        self._api_key = api_key
        self._counters = counters
        self._max_results = max_results
        self._results: list[SearchResult] = []
        self._index_by_url: dict[str, int] = {}

    async def search(self, queries: list[str]) -> list[tuple[int, SearchResult]]:
        queries = [q.strip() for q in queries if q and q.strip()]
        if not queries:
            return []
        self._counters.searches += len(queries)
        batches = await asyncio.gather(
            *(
                web_search.search(
                    q, self._api_key, max_results=self._max_results, include_raw_content=True
                )
                for q in queries
            ),
            return_exceptions=True,
        )
        added: list[tuple[int, SearchResult]] = []
        for query, batch in zip(queries, batches):
            if isinstance(batch, BaseException):
                logger.warning("Search failed for %r: %s", query, batch)
                continue
            for r in batch:
                if not r.url:
                    continue
                if r.url in self._index_by_url:
                    continue
                self._index_by_url[r.url] = len(self._results)
                self._results.append(r)
                added.append((self._index_by_url[r.url], r))
        return added

    def seed(self, citations: list[dict]) -> list[tuple[int, SearchResult]]:
        """Make sources an earlier step already used citable here too, so a
        step that builds on earlier figures can point back to where they came
        from. No search is made."""
        added: list[tuple[int, SearchResult]] = []
        for c in citations:
            url = c.get("url")
            if not url or url in self._index_by_url:
                continue
            self._index_by_url[url] = len(self._results)
            self._results.append(SearchResult(url=url, title=c.get("title", ""), snippet=c.get("snippet", "")))
            added.append((self._index_by_url[url], self._results[-1]))
        return added

    def result(self, index: int) -> SearchResult | None:
        return self._results[index] if 0 <= index < len(self._results) else None

    def all(self) -> list[tuple[int, SearchResult]]:
        return list(enumerate(self._results))

    @staticmethod
    def format(results: list[tuple[int, SearchResult]], *, with_raw: bool = False) -> str:
        parts = []
        for i, r in results:
            body = r.snippet
            if with_raw and r.raw_content:
                body = r.raw_content[:_RAW_CHARS]
            parts.append(f"[{i}] {r.title}\n    {r.url}\n    {body}")
        return "\n\n".join(parts)
