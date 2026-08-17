"""Consulting agent: web research + structured report generation."""
from __future__ import annotations

import asyncio
import logging
from typing import Union

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.consulting_schemas import (
    BrandAnalysisOutput,
    Citation,
    FeasibilityOutput,
    MarketResearchOutput,
    PESTELOutput,
    SWOTOutput,
)
from app.agents.llm import get_llm

logger = logging.getLogger(__name__)

_SEARCH_QUERIES: dict[str, list[str]] = {
    "swot": [
        "{industry} market competition landscape 2025",
        "{brand_name} brand positioning strengths weaknesses",
        "{industry} industry trends opportunities threats 2025",
    ],
    "pestel": [
        "{industry} regulatory policy legal changes 2025",
        "{industry} economic outlook consumer spending trends",
        "{industry} technology digital innovation disruption",
        "{industry} social demographic consumer behavior trends",
    ],
    "feasibility": [
        "{industry} market size growth forecast 2025",
        "{industry} competitive landscape key players market share",
        "{brand_name} {products_summary} target customer demand",
        "{industry} startup business challenges success factors risks",
    ],
    "brand_analysis": [
        "{brand_name} brand positioning vs competitors {industry}",
        "{industry} brand messaging best practices 2025",
        "{brand_name} target audience consumer perception",
        "{industry} brand differentiation competitive advantage",
    ],
    "market_research": [
        "{industry} market size segments growth 2025",
        "{industry} market leaders key players market share",
        "{industry} consumer trends buyer behavior 2025",
        "{industry} emerging opportunities disruption trends",
    ],
}

_OUTPUT_SCHEMAS = {
    "swot": SWOTOutput,
    "pestel": PESTELOutput,
    "feasibility": FeasibilityOutput,
    "brand_analysis": BrandAnalysisOutput,
    "market_research": MarketResearchOutput,
}

_SYSTEM_PROMPTS: dict[str, str] = {
    "swot": (
        "You are a strategic business analyst. Produce a rigorous SWOT analysis based ONLY on "
        "the provided brand profile and numbered search results. Each item must include a point, "
        "a one-sentence evidence rationale, and citation_indices listing which numbered sources "
        "support it. Never invent facts not backed by provided sources."
    ),
    "pestel": (
        "You are a strategic management consultant. Produce a PESTEL analysis based ONLY on "
        "the provided brand profile and numbered search results. Each item must include factor, "
        "observation, implication, and citation_indices listing which numbered sources support it. "
        "Never invent facts not backed by provided sources."
    ),
    "feasibility": (
        "You are a business feasibility analyst. Produce a structured feasibility study based ONLY on "
        "the provided brand profile and numbered search results. Each section must include findings "
        "and citation_indices listing which numbered sources support each finding. "
        "The recommendation must be one of: proceed, proceed_with_caution, or do_not_proceed. "
        "Never invent facts not backed by provided sources."
    ),
    "brand_analysis": (
        "You are a brand strategist. Assess each brand dimension — positioning, messaging, audience_alignment — "
        "by comparing the brand profile claims against what competitors and industry sources say in the numbered search results. "
        "Cite index numbers for every claim. For each BrandItem, state the current_state of the brand, "
        "the gap_or_strength identified from the sources, and a concrete recommendation. "
        "Never generalize without a source."
    ),
    "market_research": (
        "You are a market research analyst. Describe the market using ONLY data from the numbered search results. "
        "For every size estimate, growth rate, or trend, cite the source index in citation_indices. "
        "key_trends and competitive_dynamics reuse the same structure as SWOT items (point, evidence, citation_indices). "
        "strategic_implications must be a concise paragraph summarizing what the findings mean for the brand. "
        "Never state a figure not found in the sources."
    ),
}


def _build_queries(analysis_type: str, brand_profile: dict, context: str | None = None) -> list[str]:
    industry = brand_profile.get("industry") or "general business"
    brand_name = brand_profile.get("subject_name") or brand_profile.get("legal_name") or "the company"
    products = brand_profile.get("business_lines") or []
    products_summary = ", ".join(p.get("name", "") for p in products[:3]) if products else "products"

    templates = _SEARCH_QUERIES.get(analysis_type, _SEARCH_QUERIES["swot"])
    queries = [
        t.format(industry=industry, brand_name=brand_name, products_summary=products_summary)
        for t in templates
    ]
    if context:
        queries.append(context[:200])
        queries.append(f"{industry} {context[:150]}")
    return queries


def _ddg_search(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def gather_research(
    brand_profile: dict,
    analysis_type: str,
    context: str | None = None,
) -> list[Citation]:
    """Run targeted DuckDuckGo searches and return deduplicated citations."""
    from app.services.fact_dedup import deduplicate_sources

    queries = _build_queries(analysis_type, brand_profile, context)

    raw_results: list[dict] = []
    for query in queries:
        try:
            results = await asyncio.to_thread(_ddg_search, query, 6)
        except Exception as exc:
            logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
            continue

        for r in results:
            url = r.get("href", "")
            if not url:
                continue
            raw_results.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": (r.get("body") or "")[:300],
            })

    deduped = deduplicate_sources(raw_results)

    citations = [
        Citation(
            title=d.get("title", ""),
            url=d.get("url", ""),
            snippet=d.get("snippet", "")[:300],
        )
        for d in deduped
        if d.get("url")
    ]
    return citations[:15]


def _validate_citation_indices(
    output: Union[SWOTOutput, PESTELOutput, FeasibilityOutput, BrandAnalysisOutput, MarketResearchOutput],
    citations: list[Citation],
) -> Union[SWOTOutput, PESTELOutput, FeasibilityOutput, BrandAnalysisOutput, MarketResearchOutput]:
    """Strip out-of-range citation indices; mark affected items as unverified."""
    n = len(citations)

    def clean(item):
        valid = [i for i in item.citation_indices if 0 <= i < n]
        if len(valid) < len(item.citation_indices) or not valid:
            return item.model_copy(update={"citation_indices": valid, "unverified": True})
        return item

    if isinstance(output, SWOTOutput):
        return output.model_copy(update={
            "strengths": [clean(x) for x in output.strengths],
            "weaknesses": [clean(x) for x in output.weaknesses],
            "opportunities": [clean(x) for x in output.opportunities],
            "threats": [clean(x) for x in output.threats],
        })
    if isinstance(output, PESTELOutput):
        return output.model_copy(update={
            "political": [clean(x) for x in output.political],
            "economical": [clean(x) for x in output.economical],
            "social": [clean(x) for x in output.social],
            "technological": [clean(x) for x in output.technological],
            "environmental": [clean(x) for x in output.environmental],
            "legal": [clean(x) for x in output.legal],
        })
    if isinstance(output, FeasibilityOutput):
        return output.model_copy(update={
            "market_size_and_growth": clean(output.market_size_and_growth),
            "competitive_landscape": clean(output.competitive_landscape),
            "target_customer": clean(output.target_customer),
            "key_risks": clean(output.key_risks),
        })
    if isinstance(output, BrandAnalysisOutput):
        return output.model_copy(update={
            "positioning": [clean(x) for x in output.positioning],
            "messaging": [clean(x) for x in output.messaging],
            "audience_alignment": [clean(x) for x in output.audience_alignment],
        })
    if isinstance(output, MarketResearchOutput):
        return output.model_copy(update={
            "market_overview": clean(output.market_overview),
            "segments": [clean(x) for x in output.segments],
            "key_trends": [clean(x) for x in output.key_trends],
            "competitive_dynamics": [clean(x) for x in output.competitive_dynamics],
        })
    return output


def _format_citations_for_prompt(citations: list[Citation]) -> str:
    lines = []
    for i, c in enumerate(citations):
        lines.append(f"[{i}] {c.title}\n    {c.snippet}\n    URL: {c.url}")
    return "\n\n".join(lines)


async def run_analysis(
    brand_profile: dict,
    analysis_type: str,
    citations: list[Citation],
    context: str | None = None,
) -> Union[SWOTOutput, PESTELOutput, FeasibilityOutput, BrandAnalysisOutput, MarketResearchOutput]:
    """Generate a structured consulting report grounded in the provided citations."""
    schema = _OUTPUT_SCHEMAS[analysis_type]
    llm = get_llm("reasoning").with_structured_output(schema, method="json_schema")

    bp_summary = (
        f"Subject: {brand_profile.get('subject_name') or brand_profile.get('legal_name', 'N/A')}\n"
        f"Industry: {brand_profile.get('industry', 'N/A')}\n"
        f"Business Lines: {', '.join(p.get('name','') for p in (brand_profile.get('business_lines') or [])[:5])}\n"
        f"Areas of Interest: {', '.join((brand_profile.get('areas_of_interest') or [])[:3])}\n"
        f"Description: {brand_profile.get('subject_description', 'N/A')}"
    )

    citations_text = _format_citations_for_prompt(citations) if citations else "No external sources found."
    if context:
        context_line = (
            f"\n\nSpecific context from user: {context}\n\n"
            "Relevance instruction: For every section you produce, explicitly check whether your "
            "cited evidence actually speaks to the specific situation described above — not just to "
            "the industry in general. Being cited is not the same as being relevant to this specific "
            "question. If citations only support generic industry-level observations disconnected from "
            "the context, say so explicitly in the implication or recommendation field (e.g., "
            "'Available sources address X in general but do not speak to [the specific question] "
            "directly') rather than presenting off-topic findings as if they answer the question. "
            "Prefer a thinner, context-grounded section over a fuller one of technically-cited but "
            "contextually irrelevant content."
        )
    else:
        context_line = ""

    human_content = (
        f"Brand Profile:\n{bp_summary}\n\n"
        f"Search Results (reference by index in citation_indices):\n{citations_text}"
        f"{context_line}\n\n"
        f"Produce the {analysis_type.upper()} analysis now."
    )

    if not citations:
        human_content += (
            "\n\nNote: No external web sources were retrieved. Produce the analysis "
            "using the brand profile above and general strategic knowledge. "
            "Set unverified=true on all items and citation_indices=[]."
        )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPTS[analysis_type]),
        HumanMessage(content=human_content),
    ]

    output = await llm.ainvoke(messages)
    return _validate_citation_indices(output, citations)
