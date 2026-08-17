"""Chart dedup / necessity filter.

Before generating a chart, this filter checks whether:
  1. A semantically equivalent chart already exists in the response (by type,
     normalized title tokens, AND data-shape keys).
  2. The candidate has ≥2 concrete data points worth visualizing.

Matching on (type, title tokens, x_key, series_key) prevents the same
underlying data slice from producing two bar charts with different titles —
e.g. "Revenue by Year" and "Annual Revenue Comparison" over the same
year/revenue fields.
"""
from __future__ import annotations

import re

from app.agents.visual_schema import VisualBlock, VisualType


def _tokenize(text: str) -> frozenset[str]:
    """Lower-case word tokens, ignoring stop words and punctuation."""
    _STOP = {
        "a", "an", "the", "of", "in", "by", "for", "and", "or", "vs",
        "chart", "graph", "plot", "data",
    }
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(t for t in tokens if t not in _STOP and len(t) > 1)


def _title_overlap(title_a: str, title_b: str) -> float:
    """Jaccard overlap between the token sets of two titles."""
    ta = _tokenize(title_a)
    tb = _tokenize(title_b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def should_generate_chart(
    candidate_type: VisualType,
    candidate_title: str,
    candidate_x_key: str,
    candidate_series_key: str | None,
    existing_visuals: list[VisualBlock],
) -> bool:
    """Return True if the candidate chart should be generated, False to skip.

    Parameters
    ----------
    candidate_type:
        The proposed chart type.
    candidate_title:
        The proposed chart title.
    candidate_x_key:
        Field name being used as the x-axis / category key.
    candidate_series_key:
        Field name identifying the series (None for single-series types).
    existing_visuals:
        Charts already committed to this response.

    Returns
    -------
    False when a semantically duplicate chart already exists.
    True otherwise (caller should still check data sufficiency separately).
    """
    for existing in existing_visuals:
        if existing.type != candidate_type:
            continue

        # Title token overlap ≥60% → likely duplicate topic
        if _title_overlap(existing.title, candidate_title) >= 0.60:
            return False

        # Same data-shape keys even if the title words differ.
        # Skip this check for generic structural keys ("label", "name", "date")
        # since they don't carry semantic meaning after the shaper normalizes them.
        _GENERIC_KEYS = {"label", "name", "date", "text", "value", None}
        if candidate_x_key not in _GENERIC_KEYS:
            existing_data = existing.data or {}
            existing_keys = _infer_data_keys(existing_type=existing.type, data=existing_data)
            if (
                existing_keys.get("x_key") == candidate_x_key
                and existing_keys.get("series_key") == candidate_series_key
            ):
                return False

    return True


def _infer_data_keys(existing_type: VisualType, data: dict) -> dict[str, str | None]:
    """Best-effort inference of x_key and series_key from existing chart data."""
    # For simple list-of-{label, value} types
    if existing_type in ("bar_chart", "line_chart", "pie_chart", "donut_chart"):
        rows = data.get("data") or []
        if rows and isinstance(rows, list) and isinstance(rows[0], dict):
            return {"x_key": "label", "series_key": None}

    # For multi-series types, infer series from the "series" array's "name" key
    if existing_type in ("area_chart", "stacked_bar_chart", "radar_chart"):
        series = data.get("series") or []
        if series and isinstance(series, list) and isinstance(series[0], dict):
            return {"x_key": data.get("categories") and "category" or "label",
                    "series_key": "name"}

    if existing_type == "table":
        cols = data.get("columns") or []
        return {"x_key": cols[0] if cols else None, "series_key": None}

    if existing_type == "comparison_grid":
        items = data.get("items") or []
        return {"x_key": "name", "series_key": None}

    return {"x_key": None, "series_key": None}
