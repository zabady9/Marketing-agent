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
You are a data visualization assistant. Given a user question and the AI assistant's answer, \
decide whether any visual blocks would genuinely help communicate the answer more clearly.

RULES:
- ONLY create visuals when the answer contains specific numbers, metrics, comparisons between \
2+ items, or trends over time. Plain advice, content-writing requests, and qualitative answers \
must return visuals: [].
- Never fabricate numbers — only visualize data explicitly stated in the answer text.
- Limit to 3 visuals maximum per response.
- Supported types: bar_chart, line_chart, area_chart, table, metric_card, radar_chart, \
pie_chart, donut_chart, stacked_bar_chart, gauge, comparison_grid, timeline.
  Do NOT use word_cloud or progress_list.

DATA SHAPES:
- bar_chart / line_chart / area_chart: {"data": [{"label": str, "value": number}], "series"?: str}
- table: {"columns": [str], "rows": [[str]]}
- metric_card: {"label": str, "value": str, "trend": "up"|"down"|"flat", "comparison"?: str}
- radar_chart: {"axes": [str], "series": [{"name": str, "values": [number]}]}
- pie_chart / donut_chart: {"data": [{"label": str, "value": number}]}
- stacked_bar_chart: {"categories": [str], "series": [{"name": str, "values": [number]}]}
- gauge: {"label": str, "value": number, "min": number, "max": number, "target"?: number}
- comparison_grid: {"items": [{"name": str, "highlight"?: bool, "metrics": {key: str}}]}
- timeline: {"events": [{"date": str, "label": str}]}

For sources: include only entries that were directly cited in the answer.
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
