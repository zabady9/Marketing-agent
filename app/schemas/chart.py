from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChartSeries(BaseModel):
    """One data series — a bar chart with one series is a simple bar chart;
    multiple series render as grouped/stacked bars or multiple lines."""

    name: str
    data: list[float | None] = Field(..., description="One value per category, same order/length as categories.")


class ChartSpec(BaseModel):
    """A small, constrained chart specification the chat agent fills in via
    generate_chart_tool. Deliberately narrow (bar/line/pie only, flat
    category+series shape) rather than an open-ended plotting DSL — this is
    what the frontend's GenericChart component renders directly, so every
    field here maps 1:1 to something recharts can draw without further
    interpretation on either side."""

    chart_type: Literal["bar", "line", "pie"]
    title: str
    categories: list[str] = Field(..., min_length=1, description="X-axis labels (bar/line) or slice labels (pie).")
    series: list[ChartSeries] = Field(..., min_length=1)
    x_label: str | None = None
    y_label: str | None = None

    @model_validator(mode="after")
    def _series_lengths_match_categories(self) -> "ChartSpec":
        expected = len(self.categories)
        for s in self.series:
            if len(s.data) != expected:
                raise ValueError(
                    f"series {s.name!r} has {len(s.data)} value(s) but there are "
                    f"{expected} categories — each series must have exactly one "
                    "value per category, in the same order."
                )
        if self.chart_type == "pie" and len(self.series) != 1:
            raise ValueError("a pie chart takes exactly one series (one value per slice).")
        return self
