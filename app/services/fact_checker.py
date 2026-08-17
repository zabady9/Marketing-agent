"""Lightweight consistency / fact-check pass over assembled tool results.

A cheap-tier LLM call that scans the deduplicated tool outputs for contradictions
(same metric, same entity, different values from different sources) before the
generator synthesizes them. The resulting warnings are injected into the synthesis
prompt so the generator can hedge on contested figures rather than confidently
citing a wrong number.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agents.llm import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a fact-consistency reviewer. You receive a list of source excerpts retrieved
from the web and structured market data. Your job is to identify contradictions:
cases where two sources report different numeric values for the same metric and entity.

Rules:
- Only flag contradictions that involve specific numbers (revenue, growth rate, headcount, etc.).
- Do NOT flag sources that are simply discussing different time periods as contradictions.
- Do NOT flag a figure vs. an estimate/proxy as a contradiction — they are different data types.
- Keep each contradiction description brief (one sentence each).
- Return at most 5 contradictions.

Output JSON only:
{
  "contradictions": [
    {
      "entity": "<entity name>",
      "metric": "<what metric>",
      "claim_a": "<value from source A>",
      "source_a": "<source title or URL>",
      "claim_b": "<value from source B>",
      "source_b": "<source title or URL>"
    }
  ],
  "warnings": ["<one-line warning for the generator, e.g. 'Revenue for X is disputed: ...'>"]
}
"""


class _Contradiction(BaseModel):
    entity: str
    metric: str
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str


class ConsistencyReport(BaseModel):
    contradictions: list[_Contradiction] = []
    warnings: list[str] = []


async def check_consistency(
    tool_results: list[dict],
    source_count: int = 0,
) -> ConsistencyReport:
    """Scan tool results for contradicting numeric claims.

    Parameters
    ----------
    tool_results:
        Deduplicated list of dicts from fact_dedup.deduplicate_sources().
    source_count:
        Number of registered sources (used to skip the call when evidence is thin).

    Returns
    -------
    ConsistencyReport with contradictions list and plain-English warnings for the
    generator's system prompt.
    """
    # Skip if there's too little evidence to check (avoids wasting tokens)
    if len(tool_results) < 2:
        return ConsistencyReport()

    # Build a compact evidence summary (title + snippet, ≤150 chars each)
    lines = []
    for i, r in enumerate(tool_results[:20], 1):
        title = (r.get("title") or "Unknown")[:60]
        snippet = (r.get("snippet") or r.get("content") or "")[:150]
        conflict_note = " [CONFLICT FLAGGED]" if r.get("conflict") else ""
        lines.append(f"{i}. [{title}]{conflict_note}: {snippet}")

    evidence_text = "\n".join(lines)

    try:
        llm = get_llm("cheap").with_structured_output(
            ConsistencyReport, method="json_schema"
        )
        result = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"Sources to check:\n\n{evidence_text}"),
        ])
        return result
    except Exception as exc:
        logger.warning("Fact-check pass failed (non-fatal): %s", exc)
        return ConsistencyReport()
