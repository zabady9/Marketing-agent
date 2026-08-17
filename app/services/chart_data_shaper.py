"""Deterministic chart data shaper.

Transforms raw tool output (dicts from web_search, get_market_data, or
consulting_schemas outputs) into the exact `data` dict schema expected by
each VisualType in visual_schema.py.

This is NOT an LLM call. Numbers come from the tool outputs, not the generator.
The generator must never freehand chart JSON — it calls this shaper first.
"""
from __future__ import annotations

from typing import Any

from app.agents.visual_schema import VisualType


class ChartShapeError(ValueError):
    """Raised when raw_data is insufficient for the requested visual type."""


def shape_for_chart(
    visual_type: VisualType,
    raw_data: list[dict],
    x_key: str,
    y_key: str,
    series_key: str | None = None,
) -> dict[str, Any]:
    """Transform raw_data rows into the validated data dict for visual_type.

    Parameters
    ----------
    visual_type:
        One of the 14 supported VisualType values.
    raw_data:
        List of dicts, each representing one data point from tool output.
    x_key:
        Field name to use as the category label / x-axis / event label.
    y_key:
        Field name to use as the numeric value / y-axis.
    series_key:
        Field name identifying the series (for multi-series types like
        area_chart, stacked_bar_chart). Pass None for single-series types.

    Returns
    -------
    A dict matching the exact schema for visual_type, ready for VisualBlock.data.

    Raises
    ------
    ChartShapeError
        When raw_data doesn't have enough valid rows for the visual type.
    """
    if not raw_data:
        raise ChartShapeError(f"No data rows provided for {visual_type!r}")

    shapers = {
        "bar_chart":          _shape_bar,
        "line_chart":         _shape_line,
        "area_chart":         _shape_area,
        "pie_chart":          _shape_pie,
        "donut_chart":        _shape_pie,   # Same shape, different render
        "stacked_bar_chart":  _shape_stacked_bar,
        "radar_chart":        _shape_radar,
        "table":              _shape_table,
        "metric_card":        _shape_metric_card,
        "gauge":              _shape_gauge,
        "comparison_grid":    _shape_comparison_grid,
        "timeline":           _shape_timeline,
        "word_cloud":         _shape_word_cloud,
        "progress_list":      _shape_progress_list,
    }
    fn = shapers.get(visual_type)
    if fn is None:
        raise ChartShapeError(f"Unknown visual_type: {visual_type!r}")
    return fn(raw_data, x_key, y_key, series_key)


# ── individual shapers ────────────────────────────────────────────────────────

def _extract_num(row: dict, key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _shape_bar(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    points = [
        {"label": str(r[x_key]), "value": _extract_num(r, y_key)}
        for r in raw
        if x_key in r and _extract_num(r, y_key) is not None
    ]
    if len(points) < 2:
        raise ChartShapeError("bar_chart needs ≥2 data points")
    return {"data": points}


def _shape_line(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    points = [
        {"label": str(r[x_key]), "value": _extract_num(r, y_key)}
        for r in raw
        if x_key in r and _extract_num(r, y_key) is not None
    ]
    if len(points) < 3:
        raise ChartShapeError("line_chart needs ≥3 data points")
    return {"data": points}


def _shape_area(raw: list[dict], x_key: str, y_key: str, series_key: str | None) -> dict:
    if not series_key:
        raise ChartShapeError("area_chart requires series_key for multi-series data")
    series_map: dict[str, list] = {}
    for r in raw:
        s_name = str(r.get(series_key, "Value"))
        val = _extract_num(r, y_key)
        label = str(r.get(x_key, ""))
        if val is None or not label:
            continue
        series_map.setdefault(s_name, []).append({"label": label, "value": val})
    if not series_map:
        raise ChartShapeError("area_chart has no valid series data")
    # Convert to the [{name, data: [{label, value}]}] format
    return {"series": [{"name": k, "data": v} for k, v in series_map.items()]}


def _shape_pie(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    slices = [
        {"label": str(r[x_key]), "value": _extract_num(r, y_key)}
        for r in raw
        if x_key in r and _extract_num(r, y_key) is not None
    ]
    if not slices:
        raise ChartShapeError("pie/donut chart has no valid data")
    return {"data": slices}


def _shape_stacked_bar(raw: list[dict], x_key: str, y_key: str, series_key: str | None) -> dict:
    if not series_key:
        raise ChartShapeError("stacked_bar_chart requires series_key")
    categories: list[str] = []
    series_map: dict[str, list] = {}
    seen_cats: list[str] = []
    for r in raw:
        cat = str(r.get(x_key, ""))
        s_name = str(r.get(series_key, "Value"))
        val = _extract_num(r, y_key)
        if not cat or val is None:
            continue
        if cat not in seen_cats:
            seen_cats.append(cat)
        series_map.setdefault(s_name, {})[cat] = val

    if not seen_cats or not series_map:
        raise ChartShapeError("stacked_bar_chart has no valid data")

    series_out = [
        {"name": s, "values": [vals.get(c, 0.0) for c in seen_cats]}
        for s, vals in series_map.items()
    ]
    return {"categories": seen_cats, "series": series_out}


def _shape_radar(raw: list[dict], x_key: str, y_key: str, series_key: str | None) -> dict:
    axes = sorted({str(r[x_key]) for r in raw if x_key in r})
    if not (4 <= len(axes) <= 7):
        raise ChartShapeError(f"radar_chart needs 4-7 axes, got {len(axes)}")
    series_names = sorted({str(r.get(series_key or y_key, "")) for r in raw})

    series_out = []
    for s_name in series_names:
        values = []
        for axis in axes:
            match = next(
                (r for r in raw if str(r.get(x_key, "")) == axis
                 and str(r.get(series_key or "series", "")) == s_name),
                None,
            )
            values.append(_extract_num(match, y_key) if match else 0.0)
        series_out.append({"name": s_name, "values": values})
    return {"axes": axes, "series": series_out}


def _shape_table(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    if not raw:
        raise ChartShapeError("table has no rows")
    columns = list(raw[0].keys())
    rows = [[str(row.get(col, "")) for col in columns] for row in raw]
    return {"columns": columns, "rows": rows}


def _shape_metric_card(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    row = raw[0]
    label = str(row.get(x_key, row.get("label", "Metric")))
    value = str(row.get(y_key, row.get("value", "")))
    trend = str(row.get("trend", "flat"))
    if trend not in ("up", "down", "flat"):
        trend = "flat"
    result: dict = {"label": label, "value": value, "trend": trend}
    if "comparison" in row:
        result["comparison"] = str(row["comparison"])
    return result


def _shape_gauge(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    row = raw[0]
    label = str(row.get(x_key, row.get("label", "Metric")))
    value = _extract_num(row, y_key) or _extract_num(row, "value")
    minimum = _extract_num(row, "min") or 0.0
    maximum = _extract_num(row, "max") or 100.0
    if value is None:
        raise ChartShapeError("gauge requires a numeric value")
    result: dict = {"label": label, "value": value, "min": minimum, "max": maximum}
    target = _extract_num(row, "target")
    if target is not None:
        result["target"] = target
    return result


def _shape_comparison_grid(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    items = []
    for r in raw:
        name = str(r.get(x_key, r.get("name", "")))
        if not name:
            continue
        metrics = {k: str(v) for k, v in r.items() if k not in (x_key, "name", "highlight")}
        items.append({
            "name": name,
            "highlight": bool(r.get("highlight", False)),
            "metrics": metrics,
        })
    if not items:
        raise ChartShapeError("comparison_grid has no valid items")
    return {"items": items}


def _shape_timeline(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    events = [
        {"date": str(r.get(x_key, "")), "label": str(r.get(y_key, r.get("label", "")))}
        for r in raw
        if r.get(x_key)
    ]
    if not events:
        raise ChartShapeError("timeline has no valid events")
    return {"events": events}


def _shape_word_cloud(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    words = [
        {"text": str(r.get(x_key, r.get("word", r.get("text", "")))),
         "weight": _extract_num(r, y_key) or _extract_num(r, "weight") or 1.0}
        for r in raw
        if r.get(x_key) or r.get("word") or r.get("text")
    ]
    if not words:
        raise ChartShapeError("word_cloud has no valid words")
    return {"words": words}


def _shape_progress_list(raw: list[dict], x_key: str, y_key: str, _series_key: str | None) -> dict:
    items = [
        {
            "label": str(r.get(x_key, r.get("label", ""))),
            "value": _extract_num(r, y_key) or _extract_num(r, "value") or 0.0,
            "max": _extract_num(r, "max") or 100.0,
        }
        for r in raw
        if r.get(x_key) or r.get("label")
    ]
    if not items:
        raise ChartShapeError("progress_list has no valid items")
    return {"items": items}
