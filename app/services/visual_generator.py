"""Visual generation pipeline for chat responses.

Two invocation paths:
  - Report-level (batch, post-generation): run_report_visualization_pass()
    Used after synthesis for SWOT, PESTEL, feasibility, market_research, general_analysis.
    Runs the full type-selector → dedup → validate → placement pipeline.
  - Inline (streaming): build_chart_spec()
    Called by agents as an agentic tool with pre-shaped data. The LLM only fills
    in title/labels; numbers come from the Chart-Data Shaper, not the generator.

Both paths validate against the shared VisualBlock schema. A single repair pass
is attempted on invalid blocks before they are silently dropped.

The legacy generate_visuals() remains for backward compatibility but now routes
through the extended validator.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.llm import get_llm
from app.agents.visual_schema import VisualBlock, VisualResponse, VisualType
from app.services.chart_dedup import should_generate_chart
from app.services.chart_placement import resolve_placement
from app.services.chart_type_selector import DataShape, select_chart_type

logger = logging.getLogger(__name__)

# Required top-level keys per visual type
_REQUIRED_KEYS: dict[str, list[str]] = {
    "bar_chart":         ["data"],
    "line_chart":        ["data"],
    "area_chart":        ["data"],
    "pie_chart":         ["data"],
    "donut_chart":       ["data"],
    "table":             ["columns", "rows"],
    "metric_card":       ["label", "value", "trend"],
    "radar_chart":       ["axes", "series"],
    "stacked_bar_chart": ["categories", "series"],
    "gauge":             ["label", "value", "min", "max"],
    "comparison_grid":   ["items"],
    "timeline":          ["events"],
    "word_cloud":        ["words"],
    "progress_list":     ["items"],
}

# Types where the primary data carrier is a list that must be non-empty
_LIST_DATA_KEY: dict[str, str] = {
    "bar_chart":        "data",
    "line_chart":       "data",
    "pie_chart":        "data",
    "donut_chart":      "data",
    "radar_chart":      "series",
    "stacked_bar_chart":"series",
    "comparison_grid":  "items",
    "timeline":         "events",
    "word_cloud":       "words",
    "progress_list":    "items",
}

_GENERATION_SYSTEM_PROMPT = """\
You are a data visualization specialist. Given a user question and the assistant's analytical
answer, select the BEST visual representations that help the user understand the data FASTER
than reading prose.

## When to add a visual (STRICT)
Only create a visual when the answer contains:
- Specific numbers or metrics that can be compared across 2+ items
- Trends over time with at least 3 data points
- Proportional compositions (market share, segment breakdown)
- Side-by-side feature/attribute comparisons

Do NOT create visuals for:
- Qualitative text answers with no specific numbers
- Content-writing outputs (posts, captions, copy)
- Single data points with nothing to compare against

Maximum 3 visuals per response. Return visuals: [] if nothing genuinely adds clarity.
Never fabricate numbers — only visualize data explicitly stated in the answer text.

## Choosing the right type — match data semantics, not aesthetic preference

Data pattern → Best visual:
- 2–8 items compared on ONE numeric metric (followers, revenue, price) → bar_chart
- Single metric changing across time with ≥3 ordered data points → line_chart
- Proportional parts of a whole, ≤6 segments that sum to ~100% → pie_chart or donut_chart
- 1–3 standalone KPIs the user should notice immediately → metric_card
- 2–3 entities compared across 4–7 attributes simultaneously → radar_chart
- Multi-column data with mixed metric types OR more than 4 entities → table
- Named entities compared attribute-by-attribute (text values ok) → comparison_grid
- Multiple series growing/declining together over time → stacked_bar_chart or area_chart
- Single metric benchmarked against a target or maximum → gauge
- Sequence of events or milestones with dates → timeline
- Frequency-weighted terms or keywords → word_cloud

Prefer TABLE when:
- Comparing 3+ entities on 3+ different metrics at the same time
- The data mixes different units (%, $, count, rating) in one view
- There are more than 8 labeled data points (bar chart would be unreadable)

Never use pie/donut for more than 6 segments or data that doesn't represent parts of a whole.

## Data shapes (exact format required)
- bar_chart / line_chart:
    {"data": [{"label": str, "value": number}], "unit"?: str}
- area_chart:
    {"series": [{"name": str, "data": [{"label": str, "value": number}]}]}
- table:
    {"columns": [str], "rows": [[str]]}
- metric_card:
    {"label": str, "value": str, "trend": "up"|"down"|"flat", "comparison"?: str}
- radar_chart:
    {"axes": [str], "series": [{"name": str, "values": [number]}]}
- pie_chart / donut_chart:
    {"data": [{"label": str, "value": number}]}
- stacked_bar_chart:
    {"categories": [str], "series": [{"name": str, "values": [number]}]}
- gauge:
    {"label": str, "value": number, "min": number, "max": number, "target"?: number}
- comparison_grid:
    {"items": [{"name": str, "highlight"?: bool, "metrics": {key: str}}]}
- timeline:
    {"events": [{"date": str, "label": str}]}
- word_cloud:
    {"words": [{"text": str, "weight": number}]}
- progress_list:
    {"items": [{"label": str, "value": number, "max": number}]}

## Sources
Include in `sources` only entries that appear in the answer text with a cited URL.
Do NOT fabricate source URLs — omit a source if you are not certain of its URL.
"""

_REPAIR_SYSTEM_PROMPT = """\
You are fixing a broken visualization spec. The chart block below failed schema validation.
Correct ONLY the `data` field to match the required format. Do NOT change `type` or `title`.
Return a single valid JSON object matching the VisualBlock schema.
"""


# ── schema validation (extended) ─────────────────────────────────────────────

def _validate_block(block: VisualBlock) -> tuple[bool, str]:
    """Return (is_valid, reason). Checks keys, non-empty lists, and numeric values."""
    required = _REQUIRED_KEYS.get(block.type, [])
    for k in required:
        if k not in block.data:
            return False, f"missing required key '{k}'"

    # Non-empty list check
    list_key = _LIST_DATA_KEY.get(block.type)
    if list_key and list_key in block.data:
        lst = block.data[list_key]
        if not isinstance(lst, list) or len(lst) == 0:
            return False, f"'{list_key}' must be a non-empty list"

    # Numeric value check for simple data arrays
    if block.type in ("bar_chart", "line_chart", "pie_chart", "donut_chart"):
        rows = block.data.get("data") or []
        for i, row in enumerate(rows):
            v = row.get("value")
            if v is None or not isinstance(v, (int, float)):
                return False, f"data[{i}].value is not numeric: {v!r}"

    return True, ""


async def _repair_block(block: VisualBlock) -> VisualBlock | None:
    """Attempt a single LLM repair call on a malformed block. Returns None on failure."""
    try:
        llm = get_llm("cheap").with_structured_output(VisualBlock, method="json_schema")
        prompt = (
            f"Broken block:\n```json\n"
            f'{{"type": "{block.type}", "title": "{block.title}", "data": {block.data}}}\n```\n\n'
            f"Required format for {block.type}:\n{_REQUIRED_KEYS.get(block.type, [])}"
        )
        repaired = await llm.ainvoke([
            SystemMessage(content=_REPAIR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        valid, reason = _validate_block(repaired)
        if valid:
            return repaired
        logger.warning("Repair produced still-invalid block for '%s': %s", block.type, reason)
        return None
    except Exception as exc:
        logger.warning("Chart repair LLM call failed: %s", exc)
        return None


async def _validate_and_repair_blocks(blocks: list[VisualBlock]) -> list[VisualBlock]:
    """Validate each block; attempt a single repair pass on failures; drop unrecoverable."""
    result: list[VisualBlock] = []
    for block in blocks:
        valid, reason = _validate_block(block)
        if valid:
            result.append(block)
            continue
        logger.warning("Visual block '%s' ('%s') failed: %s. Attempting repair.",
                       block.type, block.title, reason)
        repaired = await _repair_block(block)
        if repaired:
            result.append(repaired)
        else:
            logger.warning("Dropping block '%s' ('%s') — unrecoverable.", block.type, block.title)
    return result


# ── build_chart_spec: inline / agentic path ───────────────────────────────────

async def build_chart_spec(
    chart_type: VisualType,
    shaped_data: dict,
    title: str,
    axis_labels: dict | None = None,
    annotations: list[str] | None = None,
) -> VisualBlock:
    """Build a validated VisualBlock from pre-shaped data.

    The LLM is used ONLY to improve the title/labels if not provided.
    Numbers come from shaped_data (output of chart_data_shaper.shape_for_chart),
    not from the model.

    Raises ValueError if the resulting block fails schema validation.
    """
    block = VisualBlock(type=chart_type, title=title, data=shaped_data)
    valid, reason = _validate_block(block)
    if not valid:
        raise ValueError(f"build_chart_spec: shaped data is invalid for {chart_type!r}: {reason}")
    return block


# ── run_report_visualization_pass: report-level batch path ───────────────────

_REPORT_INTENTS = frozenset({
    "swot", "pestel", "feasibility", "general_analysis", "market_research",
})


async def run_report_visualization_pass(
    user_query: str,
    synthesis_markdown: str,
    sources_from_tools: list[dict],
    brand_profile: dict,
    intent: str,
) -> VisualResponse:
    """Full report-level visualization pipeline.

    1. Generate candidate VisualBlocks via LLM (from synthesis text + sources)
    2. Validate + repair each block
    3. Dedup across the candidate set
    4. Resolve placement within synthesis markdown
    5. Return VisualResponse with validated, placed, deduplicated visuals

    Called after synthesis completes for report-mode intents.
    """
    # Step 1: Generate candidates (LLM call for data extraction from text)
    raw_response = await _generate_raw_visuals(user_query, synthesis_markdown, sources_from_tools)

    # Step 2: Validate + repair
    validated = await _validate_and_repair_blocks(raw_response.visuals)

    # Step 3: Dedup
    deduped: list[VisualBlock] = []
    for candidate in validated:
        if should_generate_chart(
            candidate_type=candidate.type,
            candidate_title=candidate.title,
            candidate_x_key=_infer_x_key(candidate),
            candidate_series_key=_infer_series_key(candidate),
            existing_visuals=deduped,
        ):
            deduped.append(candidate)

    # Step 4: Placement (metadata only — placement is resolved but not applied here;
    # the caller can use the placement list to inject visuals at the right position)
    if deduped:
        placement = resolve_placement(synthesis_markdown, deduped)
        # Re-order visuals by document position
        ordered = [v for v, _ in placement]
    else:
        ordered = deduped

    raw_response.visuals = ordered
    return raw_response


def _infer_x_key(block: VisualBlock) -> str:
    """Best-effort inference of x_key from a VisualBlock's data."""
    data = block.data or {}
    if "data" in data and data["data"] and isinstance(data["data"][0], dict):
        return list(data["data"][0].keys())[0]
    if "categories" in data:
        return "category"
    if "events" in data:
        return "date"
    if "items" in data:
        return "name"
    return "label"


def _infer_series_key(block: VisualBlock) -> str | None:
    data = block.data or {}
    if "series" in data and data["series"] and isinstance(data["series"][0], dict):
        return "name"
    return None


# ── legacy generate_visuals (backward-compatible entry point) ─────────────────

async def generate_visuals(
    user_query: str,
    llm_response_text: str,
    sources_from_tools: list[dict],
    brand_profile: dict,
) -> VisualResponse:
    """Generate and validate visual blocks for a chat response.

    For report-mode intents, prefer run_report_visualization_pass() which adds
    dedup, placement resolution, and stricter pipeline controls.

    This function remains for backward compatibility and for inline streaming
    path callers that don't yet use the full report pipeline.
    """
    response = await _generate_raw_visuals(user_query, llm_response_text, sources_from_tools)
    response.visuals = await _validate_and_repair_blocks(response.visuals)
    return response


async def _generate_raw_visuals(
    user_query: str,
    llm_response_text: str,
    sources_from_tools: list[dict],
) -> VisualResponse:
    """LLM call that generates VisualResponse from text. Used by both paths."""
    sources_block = ""
    if sources_from_tools:
        lines = [
            f"- [{s.get('title', 'Source')}]({s.get('url', '')})"
            + (f" (fetched {s.get('fetched_at', '')})" if s.get("fetched_at") else "")
            for s in sources_from_tools
        ]
        sources_block = "\n\nSources from tool calls:\n" + "\n".join(lines)

    human_text = (
        f"User question: {user_query}\n\n"
        f"Assistant answer:\n{llm_response_text}"
        f"{sources_block}"
    )

    try:
        llm = get_llm("cheap").with_structured_output(VisualResponse, method="json_schema")
        response: VisualResponse = await llm.ainvoke([
            SystemMessage(content=_GENERATION_SYSTEM_PROMPT),
            HumanMessage(content=human_text),
        ])
        return response
    except Exception as exc:
        logger.warning("Visual generation LLM call failed: %s", exc)
        return VisualResponse()
