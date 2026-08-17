"""Per-request in-memory source registry.

Assigns stable citation IDs (S1, S2, …) to every chunk or URL retrieved during
a single agent turn. All tool return values are annotated with these IDs so the
generator can reference [S1] instead of paraphrasing raw URLs.

Scope / known limitation
------------------------
The registry lives only for the duration of one message request and is discarded
after the SSE stream closes. Source IDs are NOT persisted to the database in this
phase. Follow-up questions referencing prior IDs (e.g. "explain S3 from before")
are out of scope; the intent classifier will route them as followup_clarification
and trigger a fresh search instead.
"""
from __future__ import annotations

from app.agents.visual_schema import SourceRef


class SourceRegistry:
    """Accumulates sources retrieved during an agent turn and assigns citation IDs."""

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._url_index: dict[str, str] = {}  # url → source_id

    def register(
        self,
        url: str,
        title: str,
        fetched_at: str,
        snippet: str = "",
        stale: bool = False,
    ) -> str:
        """Register a source and return its citation ID (e.g. 'S1').

        Idempotent: registering the same URL a second time returns the existing ID.
        """
        if url in self._url_index:
            return self._url_index[url]
        source_id = f"S{len(self._entries) + 1}"
        self._entries.append({
            "id": source_id,
            "url": url,
            "title": title,
            "fetched_at": fetched_at,
            "snippet": snippet,
            "stale": stale,
        })
        self._url_index[url] = source_id
        return source_id

    def render_bibliography(self) -> str:
        """Return a markdown footnote block listing all registered sources."""
        if not self._entries:
            return ""
        lines = ["**Sources:**"]
        for e in self._entries:
            stale_note = " *(possibly outdated)*" if e.get("stale") else ""
            lines.append(f"- [{e['id']}] [{e['title']}]({e['url']}){stale_note} — {e['fetched_at']}")
        return "\n".join(lines)

    def to_list(self) -> list[SourceRef]:
        """Return SourceRef objects for inclusion in the SSE visuals event."""
        return [
            SourceRef(
                title=f"[{e['id']}] {e['title']}",
                url=e["url"],
                fetched_at=e["fetched_at"],
            )
            for e in self._entries
        ]

    def __len__(self) -> int:
        return len(self._entries)

    def is_empty(self) -> bool:
        return len(self._entries) == 0
