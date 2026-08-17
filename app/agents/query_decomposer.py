"""Query decomposition for broad analytical intents.

Breaks a user's high-level question into 3-5 targeted web-search sub-queries
so the Tavily calls in _auto_preflight_search are specific and evidence-rich
rather than a single vague combined query.

Only called for broad intents where a single search would miss important angles:
  market_research, competitive_analysis, gap_analysis, subject_analysis,
  strategic_recommendation, general_analysis.
"""
from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agents.llm import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a search strategy expert. Given a user's analytical question and the brand/subject profile,
decompose the question into 3 to 5 highly specific web search queries.

Rules:
- Each query must be independently searchable (not dependent on the others).
- Include the subject/brand name and industry in at least one query.
- Cover different angles: market sizing, competitor landscape, trends, regulatory/macro factors, risks.
- Queries must be in the SAME LANGUAGE as the user's question.
- Do NOT include generic queries like "latest news" or "overview of X".
- Max 5 queries. If the question is narrow, return fewer.

Return ONLY a JSON object with this exact schema:
{
  "queries": ["query 1", "query 2", "query 3"]
}
"""

_BROAD_INTENTS = frozenset({
    "market_research",
    "competitive_analysis",
    "gap_analysis",
    "subject_analysis",
    "strategic_recommendation",
    "general_analysis",
})


class _DecomposedQueries(BaseModel):
    queries: list[str]


async def decompose_query(
    user_message: str,
    intent: str,
    brand_profile: dict,
) -> list[str]:
    """Return 3-5 targeted search sub-queries for the user's analytical question.

    Returns an empty list if the intent is not in _BROAD_INTENTS (caller falls
    back to its own query construction) or if decomposition fails.
    """
    if intent not in _BROAD_INTENTS:
        return []

    subject = (
        brand_profile.get("subject_name")
        or brand_profile.get("legal_name")
        or "the company"
    )
    industry = brand_profile.get("industry") or "general business"

    human_prompt = (
        f"Subject: {subject}\n"
        f"Industry: {industry}\n"
        f"User question: {user_message}\n\n"
        "Decompose into 3-5 targeted search queries."
    )

    try:
        llm = get_llm("cheap").with_structured_output(
            _DecomposedQueries, method="json_schema"
        )
        result = await llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=human_prompt),
        ])
        queries = [q.strip() for q in result.queries if q.strip()]
        return queries[:5]
    except Exception as exc:
        logger.warning("Query decomposition failed: %s", exc)
        return []
