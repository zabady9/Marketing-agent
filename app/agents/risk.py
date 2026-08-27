from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.agents.base import AgentName, AgentSoftError, search_with_sse
from app.config import get_settings
from app.schemas.common import Citation
from app.schemas.intake import FeasibilityInput
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.report import FinancialModelOutput, LocalizedText
from app.schemas.risk import RiskAssessmentOutput, RiskCategory, RiskEntry, RiskLevel
from app.sse import EventQueue, SSEEvent
from app.tools.language import ENGLISH_ONLY_TERMS_NOTE
from app.tools.web_search import SearchResult

logger = logging.getLogger(__name__)

_AGENT = AgentName.RISK


# ── Internal LLM schema ────────────────────────────────────────────────────────

class _RiskLLMEntry(BaseModel):
    risk_description: str
    category: Literal["market", "financial", "operational", "regulatory", "competitive", "technology"]
    probability: Literal["high", "medium", "low"]
    impact: Literal["high", "medium", "low"]
    mitigation: str
    citation_index: int | None = None  # 0-based index into search results, or null


class _RiskLLMOutput(BaseModel):
    risks: list[_RiskLLMEntry]   # 5–8 risks across all categories
    narrative: str               # risk overview text in output_language


def _fmt_market(m: MarketSizingOutput | None) -> str:
    if m is None:
        return "Market sizing: [AGENT FAILED — data unavailable]"
    tam = f"{m.tam.value} {m.tam.unit}" if m.tam.value is not None else "[DATA UNAVAILABLE]"
    sam = f"{m.sam.value} {m.sam.unit}" if m.sam.value is not None else "[DATA UNAVAILABLE]"
    som = f"{m.som.value} {m.som.unit}" if m.som.value is not None else "[DATA UNAVAILABLE]"
    cagr = f"{m.growth_rate_cagr}%" if m.growth_rate_cagr is not None else "[DATA UNAVAILABLE]"
    return (
        f"Market Sizing:\n"
        f"  TAM: {tam}  SAM: {sam}  SOM: {som}  CAGR: {cagr}\n"
        f"  review_recommended: {m.review_recommended}"
    )


def _fmt_competitive(c: CompetitiveAnalysisOutput | None) -> str:
    if c is None:
        return "Competitive landscape: [AGENT FAILED — data unavailable]"
    names = ", ".join(f"{x.name} [{x.market_position}]" for x in c.competitors)
    gaps = "; ".join(c.market_gaps[:3]) or "none identified"
    return (
        f"Competitive Landscape:\n"
        f"  Competitors ({len(c.competitors)}): {names}\n"
        f"  Market gaps: {gaps}"
    )


def _fmt_financial(f: FinancialModelOutput | None) -> str:
    if f is None:
        return "Financial modeling: [AGENT FAILED — data unavailable]"
    be = f.break_even.value
    roi1 = f.roi_year_1.value
    roin = f.roi_year_n.value
    npv = f.npv.value
    cf = f.cash_flow.value
    return (
        f"Financial Modeling:\n"
        f"  Break-even: {be.get('break_even_months')} months / {be.get('break_even_units')} units\n"
        f"  ROI year 1: {roi1.get('roi_percent')}%\n"
        f"  ROI year {f.analysis_horizon_years}: {roin.get('roi_percent')}%\n"
        f"  NPV: {npv.get('npv')} (positive={npv.get('is_positive')})\n"
        f"  Payback month: {cf.get('payback_month')}\n"
        f"  Capex source: {f.capex_source}  Opex source: {f.opex_monthly_source}"
    )


class RiskAssessmentAgent:
    def __init__(self) -> None:
        s = get_settings()
        self._llm = ChatGoogleGenerativeAI(
            model=s.reasoning_model,
            google_api_key=s.google_api_key,
            temperature=0,
        )
        self._settings = s

    async def run(
        self,
        fi: FeasibilityInput,
        queue: EventQueue,
        *,
        market_output: MarketSizingOutput | None,
        competitive_output: CompetitiveAnalysisOutput | None,
        financial_output: FinancialModelOutput | None,
    ) -> RiskAssessmentOutput:
        await queue.put(SSEEvent.AGENT_STARTED, {"agent": _AGENT, "study_id": fi.study_id})

        geo = fi.target_market_geography.value or "global"
        biz = fi.business_description.value
        model_type = fi.business_model_type.value or "business"
        founder_risks = fi.founder_risks.value or "none stated"

        # ── 1 regulatory/sector risk search ──────────────────────────────────
        reg_query = f"{model_type} startup regulatory compliance risks {geo} 2024 2025"
        all_results: list[SearchResult] = []
        search_queries: list[str] = [reg_query]

        try:
            results = await search_with_sse(
                queue, fi.study_id, _AGENT, reg_query,
                self._settings.tavily_api_key, max_results=5,
            )
            all_results.extend(results)
        except Exception as exc:
            logger.warning("Risk search failed: %s", exc)
            await queue.put(
                SSEEvent.AGENT_WARNING,
                {"agent": _AGENT, "study_id": fi.study_id,
                 "warning": f"Regulatory search failed — proceeding without web data: {exc}"},
            )

        results_context = (
            "\n\n".join(
                f"[{i}] TITLE: {r.title}\n    URL: {r.url}\n    SNIPPET: {r.snippet}"
                for i, r in enumerate(all_results)
            )
            or "No web data available — reason from business context only."
        )

        # ── 2 Compose prior-agent context ─────────────────────────────────────
        prior_context = "\n\n".join([
            _fmt_market(market_output),
            _fmt_competitive(competitive_output),
            _fmt_financial(financial_output),
        ])

        # ── 3 LLM risk identification ─────────────────────────────────────────
        structured_llm = self._llm.with_structured_output(_RiskLLMOutput)
        try:
            llm_out: _RiskLLMOutput = await structured_llm.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "You are a risk analyst producing a feasibility study section.\n"
                            "Identify 5–8 concrete risks across all categories "
                            "(market, financial, operational, regulatory, competitive, technology). "
                            "For each risk, assign probability and impact (high/medium/low), "
                            "and write a specific, actionable mitigation step.\n"
                            "Use citation_index (0-based) to reference search results "
                            "where they support a specific risk finding; null if not applicable.\n"
                            f"Write ALL text in language: {fi.output_language}.\n"
                            f"{ENGLISH_ONLY_TERMS_NOTE}\n"
                            "Consider: null SAM/SOM = market size uncertainty is itself a risk.\n"
                            "Consider: negative ROI year 1 = financial runway risk.\n"
                            "Consider: reflect credible founder-stated risks/concerns as their "
                            "own risk entries rather than ignoring them."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Business: {biz}\n"
                            f"Geography: {geo}  |  Model: {model_type}\n"
                            f"Analysis horizon: {fi.analysis_horizon_years} years\n"
                            f"Founder-stated risks/concerns: {founder_risks}\n\n"
                            f"=== Prior Analysis ===\n{prior_context}\n\n"
                            f"=== Regulatory Search Results ===\n{results_context}"
                        )
                    ),
                ]
            )
        except Exception as exc:
            raise AgentSoftError(f"Risk assessment LLM call failed: {exc}") from exc

        # ── 4 Resolve citations ────────────────────────────────────────────────
        seen_urls: set[str] = set()
        citations: list[Citation] = []
        for entry in llm_out.risks:
            idx = entry.citation_index
            if idx is not None and 0 <= idx < len(all_results):
                r = all_results[idx]
                if r.url not in seen_urls:
                    citations.append(Citation(url=r.url, title=r.title, snippet=r.snippet))
                    seen_urls.add(r.url)

        # ── 5 Assemble output ──────────────────────────────────────────────────
        risk_entries = [
            RiskEntry(
                risk_description=e.risk_description,
                category=RiskCategory(e.category),
                probability=RiskLevel(e.probability),
                impact=RiskLevel(e.impact),
                mitigation=e.mitigation,
            )
            for e in llm_out.risks
        ]
        high_critical = sum(
            1 for r in risk_entries
            if r.probability == RiskLevel.HIGH and r.impact == RiskLevel.HIGH
        )

        output = RiskAssessmentOutput(
            study_id=fi.study_id,
            output_language=fi.output_language,
            risks=risk_entries,
            high_critical_count=high_critical,
            narrative=LocalizedText(text=llm_out.narrative, language=fi.output_language),
            search_queries_used=search_queries,
            citations=citations,
        )

        await queue.put(SSEEvent.AGENT_COMPLETED, {"agent": _AGENT, "study_id": fi.study_id})
        return output
