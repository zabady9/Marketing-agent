from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName, AgentSoftError, gather_searches_with_sse
from app.config import get_settings
from app.schemas.common import ClaimType
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
    # <=25 words. Must name what the cited result specifically says (not just
    # "see source [i]") so a human reviewer can check the citation actually
    # supports this number — or explain why it's null.
    methodology: str


class _MarketLLMOutput(BaseModel):
    tam: _Figure
    sam: _Figure
    som: _Figure
    growth_rate_cagr: float | None = None   # percentage (e.g. 12.5 = 12.5%)
    growth_rate_citation_index: int | None = None
    growth_rate_methodology: str
    narrative: str   # market overview text in the specified output language
    key_insights: list[str]  # 3-5 bullet points in the specified output language


def _resolve_citation(index: int | None, all_results: list[SearchResult]) -> list[Citation]:
    if index is None or index < 0 or index >= len(all_results):
        return []
    r = all_results[index]
    return [Citation(url=r.url, title=r.title, snippet=r.snippet)]


def _guard(value: float | None, citations: list[Citation]) -> float | None:
    """Never let a value survive without a resolved citation, regardless of
    what the LLM claimed — enforces the prompt's HARD RULE in code too."""
    if value is not None and not citations:
        logger.warning("Market figure had a value but no resolved citation — nulling it out.")
        return None
    return value


def _classify_figure(value: float | None, citations: list[Citation]) -> ClaimType:
    if value is None:
        return ClaimType.UNAVAILABLE
    return ClaimType.VERIFIED_FACT if citations else ClaimType.ASSUMPTION


_GUARDED_METHODOLOGY = (
    "Value withheld — the model did not provide a resolvable citation for this figure."
)


def _final_methodology(original_value: float | None, guarded_value: float | None, llm_methodology: str) -> str:
    """If _guard() nulled out a value the LLM claimed, its methodology text may
    no longer describe reality (e.g. it may still claim a source) — override
    with a fixed, accurate explanation instead of trusting stale LLM text."""
    if original_value is not None and guarded_value is None:
        return _GUARDED_METHODOLOGY
    return llm_methodology


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
            # Bias toward authoritative market-research publishers, which are
            # more likely to state a concrete, citable market-size figure.
            f"{biz} {model_type} market size {geo} industry report statista OR "
            f"grandviewresearch OR mordorintelligence OR ibisworld",
            # Broader regional fallback for when the business-specific phrasing
            # above yields nothing.
            f"{model_type} market size {geo} 2025 industry analysis billion USD",
        ]

        # ── Fire all searches concurrently (semaphore(2) still throttles the
        # actual Tavily request rate; this only removes artificial staggering
        # between independent queries) ────────────────────────────────────────
        all_results: list[SearchResult] = await gather_searches_with_sse(
            queue, fi.study_id, _AGENT, queries, self._settings.tavily_api_key, max_results=5,
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
                            "For EACH figure (tam, sam, som) and for growth_rate_cagr, also write a "
                            "`methodology` sentence (<=25 words) naming WHAT the cited result "
                            "specifically states that supports this number — e.g. "
                            "'Cited result [i] states the market was valued at $X in 2024' — not a "
                            "vague 'see source [i]'. A reviewer must be able to check the citation "
                            "actually says this. If citation_index is null, methodology must say so "
                            "plainly, e.g. 'No result specifically sizes this market; value withheld.'\n"
                            f"Write narrative and key_insights entirely in language: {fi.output_language}.\n"
                            f"{ENGLISH_ONLY_TERMS_NOTE}\n"
                            "If data is insufficient, set value to null and confidence to 'low'.\n"
                            "HARD RULE — value requires a citation: set value to null (and confidence "
                            "to 'low') whenever citation_index is null. A number MUST NEVER appear "
                            "without a resolved citation backing it. Never invent a number to fill a "
                            "gap; '[DATA UNAVAILABLE]' is always an acceptable answer."
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

        # ── Enforce "no value without a citation" regardless of LLM output ────
        tam_value = _guard(llm_out.tam.value, tam_cits)
        sam_value = _guard(llm_out.sam.value, sam_cits)
        som_value = _guard(llm_out.som.value, som_cits)
        gr_value = _guard(llm_out.growth_rate_cagr, gr_cits)

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
                value=tam_value,
                currency=llm_out.tam.currency,
                unit=llm_out.tam.unit,
                confidence=llm_out.tam.confidence if tam_value is not None else "low",
                citations=tam_cits,
                claim_type=_classify_figure(tam_value, tam_cits),
                methodology=_final_methodology(llm_out.tam.value, tam_value, llm_out.tam.methodology),
            ),
            sam=EstimatedMarketFigure(
                value=sam_value,
                currency=llm_out.sam.currency,
                unit=llm_out.sam.unit,
                confidence=llm_out.sam.confidence if sam_value is not None else "low",
                citations=sam_cits,
                claim_type=_classify_figure(sam_value, sam_cits),
                methodology=_final_methodology(llm_out.sam.value, sam_value, llm_out.sam.methodology),
            ),
            som=EstimatedMarketFigure(
                value=som_value,
                currency=llm_out.som.currency,
                unit=llm_out.som.unit,
                confidence=llm_out.som.confidence if som_value is not None else "low",
                citations=som_cits,
                claim_type=_classify_figure(som_value, som_cits),
                methodology=_final_methodology(llm_out.som.value, som_value, llm_out.som.methodology),
            ),
            growth_rate_cagr=gr_value,
            growth_rate_citations=gr_cits,
            growth_rate_claim_type=(
                ClaimType.FORECAST if gr_value is not None else ClaimType.UNAVAILABLE
            ),
            growth_rate_methodology=_final_methodology(
                llm_out.growth_rate_cagr, gr_value, llm_out.growth_rate_methodology
            ),
            narrative=LocalizedText(text=llm_out.narrative, language=fi.output_language),
            key_insights=llm_out.key_insights,
            all_citations=all_cits,
            search_queries_used=queries,
            review_recommended=any(
                value is None or llm_figure.confidence == "low"
                for value, llm_figure in [
                    (tam_value, llm_out.tam),
                    (sam_value, llm_out.sam),
                    (som_value, llm_out.som),
                ]
            ),
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": _AGENT, "study_id": fi.study_id})
        return output
