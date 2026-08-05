"""Pydantic schemas for structured visual blocks returned alongside chat responses."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

VisualType = Literal[
    "bar_chart",
    "line_chart",
    "area_chart",
    "table",
    "metric_card",
    "radar_chart",
    "pie_chart",
    "donut_chart",
    "stacked_bar_chart",
    "gauge",
    "comparison_grid",
    "timeline",
    "word_cloud",
    "progress_list",
]


class VisualBlock(BaseModel):
    type: VisualType
    title: str
    data: dict[str, Any]


class SourceRef(BaseModel):
    title: str
    url: str
    fetched_at: str


class VisualResponse(BaseModel):
    visuals: list[VisualBlock] = []
    sources: list[SourceRef] = []
