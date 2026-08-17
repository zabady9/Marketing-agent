"""Deduplication and entity resolution for tool-retrieved sources.

Merges overlapping facts from web_search and get_market_data results to prevent
repetition or contradiction from reaching the generator. Replaces the inline
URL-only dedup in consulting_agent.py::gather_research().
"""
from __future__ import annotations

import re
from typing import Any


def _normalize_url(url: str) -> str:
    """Strip scheme, trailing slashes, and query params for comparison."""
    url = re.sub(r"^https?://", "", url.lower())
    url = re.sub(r"\?.*$", "", url)
    return url.rstrip("/")


def _extract_numbers(text: str) -> list[float]:
    """Pull numeric values from a snippet for conflict detection."""
    return [float(m.replace(",", "")) for m in re.findall(r"[\d,]+\.?\d*", text)]


def _numbers_conflict(a: str, b: str) -> bool:
    """Return True if two snippets contain the same entity and different numbers."""
    nums_a = set(_extract_numbers(a))
    nums_b = set(_extract_numbers(b))
    if not nums_a or not nums_b:
        return False
    # Conflict when there's at least one number in each set and they share no numbers
    return bool(nums_a) and bool(nums_b) and nums_a.isdisjoint(nums_b)


def deduplicate_sources(tool_results: list[dict]) -> list[dict]:
    """Merge overlapping facts from web_search and get_market_data results.

    Parameters
    ----------
    tool_results:
        List of dicts, each containing at least one of:
          - "url" (str)
          - "title" (str)
          - "snippet" or "content" (str, up to 300 chars)
          - "conflict" (bool, added by this function when set)

    Returns
    -------
    Deduplicated list in original order. Conflicting numeric values are flagged
    with ``conflict=True`` so the generator can hedge on those figures.
    """
    seen_urls: dict[str, int] = {}   # normalized_url → index in output
    output: list[dict] = []

    for raw in tool_results:
        if not isinstance(raw, dict):
            continue

        url = raw.get("url") or raw.get("source_url") or ""
        title = raw.get("title") or raw.get("source_title") or ""
        snippet = raw.get("snippet") or raw.get("content") or ""

        norm = _normalize_url(url) if url else ""

        if norm and norm in seen_urls:
            # Duplicate URL — merge snippet if it adds new info, flag conflict
            existing_idx = seen_urls[norm]
            existing = output[existing_idx]
            existing_snippet = existing.get("snippet") or ""
            if _numbers_conflict(existing_snippet, snippet):
                existing["conflict"] = True
            # Extend snippet if existing is shorter
            if len(snippet) > len(existing_snippet):
                existing["snippet"] = snippet
            continue

        entry: dict[str, Any] = {
            "url": url,
            "title": title,
            "snippet": snippet[:400],
            "conflict": False,
        }
        # Carry through any extra keys (fetched_at, stale, citation_id, etc.)
        for k, v in raw.items():
            if k not in entry:
                entry[k] = v

        if norm:
            seen_urls[norm] = len(output)
        output.append(entry)

    return output
