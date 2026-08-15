"""Generate visual blocks after a chat response using a second structured-output LLM call.

Called only for intents in VISUAL_INTENTS — never for plain content-writing queries.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.llm import get_llm
from app.agents.visual_schema import VisualBlock, VisualResponse

logger = logging.getLogger(__name__)

# Required top-level keys per visual type; blocks missing any of these are silently dropped.
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

_SYSTEM_PROMPT = """\
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

Prefer TABLE when:
- Comparing 3+ entities on 3+ different metrics at the same time
- The data mixes different units (%, $, count, rating) in one view
- There are more than 8 labeled data points (bar chart would be unreadable)

Never use pie/donut for more than 6 segments or data that doesn't represent parts of a whole.

## Data shapes (exact format required)
- bar_chart / line_chart / area_chart:
    {"data": [{"label": str, "value": number}], "unit"?: str}
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

## Sources
Include in `sources` only entries that appear in the answer text with a cited URL.
Do NOT fabricate source URLs — omit a source if you are not certain of its URL.
"""


def _validate_blocks(blocks: list[VisualBlock]) -> list[VisualBlock]:
    """Drop any block whose data dict is missing required keys for its declared type."""
    valid: list[VisualBlock] = []
    for block in blocks:
        required = _REQUIRED_KEYS.get(block.type, [])
        if all(k in block.data for k in required):
            valid.append(block)
        else:
            logger.warning(
                "Visual block '%s' dropped — missing required keys %s in data %s",
                block.type, required, list(block.data.keys()),
            )
    return valid


async def generate_visuals(
    user_query: str,
    llm_response_text: str,
    sources_from_tools: list[dict],
    brand_profile: dict,
) -> VisualResponse:
    sources_block = ""
    if sources_from_tools:
        lines = [
            f"- {s.get('title', '')} <{s.get('url', '')}>"
            + (f" (fetched {s.get('fetched_at', '')})" if s.get("fetched_at") else "")
            for s in sources_from_tools
        ]
        sources_block = "\n\nSources from tool calls:\n" + "\n".join(lines)

    human_text = (
        f"User question: {user_query}\n\n"
        f"Assistant answer:\n{llm_response_text}"
        f"{sources_block}"
    )

    llm = get_llm("cheap").with_structured_output(VisualResponse, method="json_schema")
    response: VisualResponse = await llm.ainvoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=human_text)]
    )
    response.visuals = _validate_blocks(response.visuals)
    return response
