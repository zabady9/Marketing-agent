"""
Report blocks — the only building material of an analysis report.

A report is a list of steps; each step's result is a list of blocks. The
frontend has one renderer per block `type` (frontend/src/components/report/
blocks/) and nothing analysis-specific, so any analysis — feasibility, SWOT,
personas, "can I compete?" — is expressed with the same vocabulary.

LLM output is messy, so `parse_blocks` REPAIRS rather than rejects: chart
series are trimmed/padded to the categories, unknown chart types become bars,
table rows are padded to the column count, and a block that still doesn't
validate is kept as a `text` block carrying its content — a step never loses
its output to one malformed block.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

Basis = Literal["sourced", "calculated", "estimate"]
Level = Literal["high", "medium", "low"]

CHART_TYPES = ("bar", "line", "area", "pie", "stacked_bar", "scatter", "radar", "funnel")
_CHART_ALIASES = {
    "column": "bar", "combo": "bar", "histogram": "bar", "horizontal_bar": "bar",
    "stacked": "stacked_bar", "stacked_column": "stacked_bar",
    "donut": "pie", "doughnut": "pie",
    "spider": "radar", "bubble": "scatter",
}


class Citation(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""


class _Block(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    title: str | None = None
    # Indices into the step's research results; resolved into `citations` by
    # the engine and then cleared.
    citation_indices: list[int] = []
    citations: list[Citation] = []


class AnswerBlock(_Block):
    type: Literal["answer"] = "answer"
    headline: str
    body: str = ""
    confidence: Level = "medium"


class TextBlock(_Block):
    type: Literal["text"] = "text"
    kind: Literal["reasoning", "explanation", "narrative", "assumption", "note"] = "explanation"
    markdown: str


class StatItem(BaseModel):
    label: str
    value: str  # display value; keep the number as the author formatted it
    unit: str = ""
    note: str = ""
    basis: Basis = "estimate"

    @field_validator("value", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> str:
        return "" if v is None else str(v)


class StatsBlock(_Block):
    type: Literal["stats"] = "stats"
    items: list[StatItem]


class ChartSeries(BaseModel):
    name: str
    data: list[float | None]


class ChartBlock(_Block):
    type: Literal["chart"] = "chart"
    chart_type: str = "bar"
    categories: list[str]
    series: list[ChartSeries]
    x_label: str | None = None
    y_label: str | None = None
    unit: str = ""
    basis: Basis = "estimate"

    @field_validator("chart_type", mode="before")
    @classmethod
    def _normalize_type(cls, v: Any) -> str:
        t = str(v or "bar").strip().lower().replace(" ", "_").replace("-", "_")
        t = _CHART_ALIASES.get(t, t)
        return t if t in CHART_TYPES else "bar"

    @model_validator(mode="after")
    def _repair_lengths(self) -> "ChartBlock":
        n = len(self.categories)
        if n == 0 or not self.series:
            raise ValueError("chart needs at least one category and one series")
        for s in self.series:
            s.data = (s.data + [None] * n)[:n]
        if self.chart_type in ("pie", "funnel") and len(self.series) > 1:
            self.series = self.series[:1]
        return self


class TableBlock(_Block):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    caption: str = ""

    @field_validator("rows", mode="before")
    @classmethod
    def _stringify_cells(cls, rows: Any) -> list[list[str]]:
        return [["" if c is None else str(c) for c in row] for row in (rows or [])]

    @model_validator(mode="after")
    def _pad_rows(self) -> "TableBlock":
        n = len(self.columns)
        if n == 0:
            raise ValueError("table needs columns")
        self.rows = [(r + [""] * n)[:n] for r in self.rows]
        return self


class ComparisonBlock(_Block):
    type: Literal["comparison"] = "comparison"
    options: list[str]
    criteria: list[str]
    # scores[i][j] = option i on criterion j, 0-10 (None = unknown)
    scores: list[list[float | None]]
    notes: list[str] = []  # optional per-option note, same order as options
    verdict: str = ""

    @model_validator(mode="after")
    def _repair_matrix(self) -> "ComparisonBlock":
        if not self.options or not self.criteria:
            raise ValueError("comparison needs options and criteria")
        rows = (self.scores + [[]] * len(self.options))[: len(self.options)]
        m = len(self.criteria)
        self.scores = [
            [None if v is None else max(0.0, min(10.0, float(v))) for v in (r + [None] * m)[:m]]
            for r in rows
        ]
        return self


class BoardItem(BaseModel):
    label: str
    detail: str = ""
    tag: str = ""


class BoardCell(BaseModel):
    title: str
    subtitle: str = ""
    items: list[BoardItem] = []


class BoardBlock(_Block):
    """SWOT (2x2), business model canvas, persona cards, kanban columns..."""

    type: Literal["board"] = "board"
    layout: Literal["grid", "columns"] = "grid"
    columns_count: int = 2
    cells: list[BoardCell]

    @field_validator("columns_count", mode="before")
    @classmethod
    def _clamp_columns(cls, v: Any) -> int:
        try:
            return max(1, min(4, int(v)))
        except (TypeError, ValueError):
            return 2


class MatrixPoint(BaseModel):
    label: str
    x: float
    y: float
    highlight: bool = False  # e.g. the user's own business


class MatrixBlock(_Block):
    """2D positioning / perception map (0-10 on both axes)."""

    type: Literal["matrix"] = "matrix"
    x_axis: str
    y_axis: str
    x_low: str = ""
    x_high: str = ""
    y_low: str = ""
    y_high: str = ""
    points: list[MatrixPoint]

    @model_validator(mode="after")
    def _clamp(self) -> "MatrixBlock":
        for p in self.points:
            p.x = max(0.0, min(10.0, p.x))
            p.y = max(0.0, min(10.0, p.y))
        return self


class DiagramBlock(_Block):
    """Any drawing: flowchart, mind map, journey, org/tree. Mermaid source, plus
    a plain nested-bullet fallback shown if the Mermaid fails to render."""

    type: Literal["diagram"] = "diagram"
    mermaid: str
    fallback: str = ""


class TimelinePhase(BaseModel):
    label: str
    start: str = ""
    end: str = ""
    items: list[str] = []


class TimelineBlock(_Block):
    type: Literal["timeline"] = "timeline"
    phases: list[TimelinePhase]


class ListItem(BaseModel):
    label: str
    detail: str = ""
    rating: Level | None = None
    tag: str = ""


class ListBlock(_Block):
    type: Literal["list"] = "list"
    style: Literal["bullets", "numbered", "checklist"] = "bullets"
    items: list[ListItem]


Block = Annotated[
    Union[
        AnswerBlock, TextBlock, StatsBlock, ChartBlock, TableBlock, ComparisonBlock,
        BoardBlock, MatrixBlock, DiagramBlock, TimelineBlock, ListBlock,
    ],
    Field(discriminator="type"),
]
BLOCK_TYPES = (
    "answer", "text", "stats", "chart", "table", "comparison",
    "board", "matrix", "diagram", "timeline", "list",
)

_block_adapter: TypeAdapter = TypeAdapter(Block)


def _as_text_block(raw: Any, reason: str) -> TextBlock:
    """Keep a block's content readable when it can't be validated as its own type."""
    title = raw.get("title") if isinstance(raw, dict) else None
    body = {k: v for k, v in raw.items() if k not in ("type", "id", "title")} if isinstance(raw, dict) else raw
    logger.info("Repairing invalid block into text (%s)", reason)
    return TextBlock(
        title=title if isinstance(title, str) else None,
        kind="note",
        markdown=_content_to_markdown(body),
    )


def _content_to_markdown(value: Any, depth: int = 0) -> str:
    indent = "  " * depth
    if isinstance(value, dict):
        return "\n".join(
            f"{indent}- **{k}**:\n{_content_to_markdown(v, depth + 1)}"
            if isinstance(v, (dict, list)) and v
            else f"{indent}- **{k}**: {v}"
            for k, v in value.items()
            if v not in (None, "", [], {})
        )
    if isinstance(value, list):
        return "\n".join(
            _content_to_markdown(v, depth) if isinstance(v, (dict, list)) else f"{indent}- {v}"
            for v in value
        )
    return f"{indent}{value}"


def parse_block(raw: Any) -> BaseModel:
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return TextBlock(markdown=raw)
    if not isinstance(raw, dict):
        return _as_text_block(raw, "not an object")
    raw = dict(raw)
    t = str(raw.get("type", "")).strip().lower()
    raw["type"] = t if t in BLOCK_TYPES else "text"
    if raw["type"] == "text" and "markdown" not in raw:
        raw["markdown"] = raw.pop("content", None) or raw.pop("body", None) or ""
    try:
        return _block_adapter.validate_python(raw)
    except ValidationError as exc:
        return _as_text_block(raw, f"{raw['type']}: {exc.error_count()} error(s)")


def parse_blocks(raws: list[Any]) -> list[BaseModel]:
    return [parse_block(r) for r in raws or []]
