from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName, AgentSoftError, search_with_sse
from app.config import get_settings
from app.schemas.intake import FeasibilityInput
from app.schemas.market import (
    Citation,
    EstimatedMarketFigure,
    MarketSizingOutput,
)
from app.schemas.report import LocalizedText
from app.sse import EventQueue, SSEEvent
from app.tools.language import ENGLISH_ONLY_TERMS_NOTE
from app.tools.web_search import SearchResult

logger = logging.getLogger(__name__)

_AGENT = AgentName.MARKET_SIZING


# ── Internal LLM schema ────────────────────────────────────────────────────────

class _Figure(BaseModel):
    value: float | None = None           # raw number (e.g., 5000000000 for $5B)
    currency: str = "USD"
    unit: str = "USD"                    # human label: "billion USD", "million USD", etc.
    confidence: Literal["high", "medium", "low"] = "medium"
    citation_index: int | None = None    # 0-based index into the flat results list


class _MarketLLMOutput(BaseModel):
    tam: _Figure
    sam: _Figure
    som: _Figure
    growth_rate_cagr: float | None = None   # percentage (e.g. 12.5 = 12.5%)
    growth_rate_citation_index: int | None = None
    narrative: str   # market overview text in the specified output language
    key_insights: list[str]  # 3-5 bullet points in the specified output language


def _resolve_citation(index: int | None, all_results: list[SearchResult]) -> list[Citation]:
    if index is None or index < 0 or index >= len(all_results):
        return []
    r = all_results[index]
    return [Citation(url=r.url, title=r.title, snippet=r.snippet)]


class MarketSizingAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.reasoning_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )
        self._settings = s

    async def run(self, fi: FeasibilityInput, queue: EventQueue) -> MarketSizingOutput:
        await queue.put(SSEEvent.AGENT_STARTED, {"agent": _AGENT, "study_id": fi.study_id})

        biz = fi.business_description.value
        geo = fi.target_market_geography.value or "global"
        model_type = fi.business_model_type.value or "business"

        queries = [
            f"{biz} total addressable market size {geo} 2024 2025 USD",
            f"{biz} {model_type} serviceable market {geo} SME segment",
            f"{biz} {model_type} market CAGR growth rate {geo} 2025 2030 forecast",
        ]

        # ── Fire searches with SSE events ────────────────────────────────────
        all_results: list[SearchResult] = []
        for query in queries:
            try:
                results = await search_with_sse(
                    queue, fi.study_id, _AGENT, query,
                    self._settings.tavily_api_key, max_results=5,
                )
                all_results.extend(results)
            except Exception as exc:
                logger.warning("Market sizing search failed for %r: %s", query, exc)
                await queue.put(
                    SSEEvent.AGENT_WARNING,
                    {"agent": _AGENT, "study_id": fi.study_id,
                     "warning": f"Search failed: {exc}"},
                )

        if not all_results:
            raise AgentSoftError("All Tavily searches returned empty — cannot size market.")

        # ── Build numbered context for LLM ────────────────────────────────────
        results_context = "\n\n".join(
            f"[{i}] TITLE: {r.title}\n    URL: {r.url}\n    SNIPPET: {r.snippet}"
            for i, r in enumerate(all_results)
        )

        # ── LLM extraction ────────────────────────────────────────────────────
        structured_llm = self._llm.with_structured_output(_MarketLLMOutput)
        try:
            llm_out: _MarketLLMOutput = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a market analyst producing a feasibility study section.\n"
                            "Using the numbered search results provided, estimate TAM, SAM, and SOM "
                            "for the described business. Definitions:\n"
                            "  TAM = total global/regional market for this product category\n"
                            "  SAM = portion of TAM reachable given geography + business model\n"
                            "  SOM = realistically obtainable share in the first 3–5 years\n"
                            "For each figure, choose the best-fit citation_index (0-based index "
                            "from the results list), or null if no result supports it.\n"
                            f"Write narrative and key_insights entirely in language: {fi.output_language}.\n"
                            f"{ENGLISH_ONLY_TERMS_NOTE}\n"
                            "If data is insufficient, set value to null and confidence to 'low'."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Business: {biz}\n"
                            f"Geography: {geo}\n"
                            f"Business model: {model_type}\n"
                            f"Analysis horizon: {fi.analysis_horizon_years} years\n\n"
                            f"Search results ({len(all_results)} total):\n{results_context}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            raise AgentSoftError(f"Market sizing LLM call failed: {exc}") from exc

        # ── Resolve citations ─────────────────────────────────────────────────
        tam_cits = _resolve_citation(llm_out.tam.citation_index, all_results)
        sam_cits = _resolve_citation(llm_out.sam.citation_index, all_results)
        som_cits = _resolve_citation(llm_out.som.citation_index, all_results)
        gr_cits = _resolve_citation(llm_out.growth_rate_citation_index, all_results)

        all_cits: list[Citation] = []
        seen_urls: set[str] = set()
        for c in tam_cits + sam_cits + som_cits + gr_cits:
            if c.url not in seen_urls:
                all_cits.append(c)
                seen_urls.add(c.url)

        output = MarketSizingOutput(
            study_id=fi.study_id,
            output_language=fi.output_language,
            tam=EstimatedMarketFigure(
                value=llm_out.tam.value,
                currency=llm_out.tam.currency,
                unit=llm_out.tam.unit,
                confidence=llm_out.tam.confidence,
                citations=tam_cits,
            ),
            sam=EstimatedMarketFigure(
                value=llm_out.sam.value,
                currency=llm_out.sam.currency,
                unit=llm_out.sam.unit,
                confidence=llm_out.sam.confidence,
                citations=sam_cits,
            ),
            som=EstimatedMarketFigure(
                value=llm_out.som.value,
                currency=llm_out.som.currency,
                unit=llm_out.som.unit,
                confidence=llm_out.som.confidence,
                citations=som_cits,
            ),
            growth_rate_cagr=llm_out.growth_rate_cagr,
            growth_rate_citations=gr_cits,
            narrative=LocalizedText(text=llm_out.narrative, language=fi.output_language),
            key_insights=llm_out.key_insights,
            all_citations=all_cits,
            search_queries_used=queries,
            review_recommended=any(
                f.confidence == "low"
                for f in [llm_out.tam, llm_out.sam, llm_out.som]
            ),
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": _AGENT, "study_id": fi.study_id})
        return output
