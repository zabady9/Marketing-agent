from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

from app.agents.competitive import CompetitiveAnalysisAgent
from app.agents.financial import FinancialCalcError, FinancialModelingAgent
from app.agents.intake import IntakeFeasibilityAgent, IntakeHardBlockError
from app.agents.market_sizing import MarketSizingAgent
from app.agents.citation_qc import CitationValidationAgent
from app.agents.risk import RiskAssessmentAgent
from app.agents.synthesis import FeasibilitySynthesisAgent
from app.schemas.intake import FeasibilityStartRequest
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.risk import RiskAssessmentOutput
from app.schemas.synthesis import FeasibilitySynthesisOutput
from app.sse import EventQueue, SSEEvent

# In-memory study registry: study_id → EventQueue
# The queue is created before the background task starts (no race condition).
_studies: dict[str, EventQueue] = {}


def register_study(study_id: str) -> EventQueue:
    """Create and register a queue for a new study. Called from the router before
    the background task starts, ensuring GET /stream never races with task setup."""
    queue = EventQueue()
    _studies[study_id] = queue
    return queue


def study_exists(study_id: str) -> bool:
    return study_id in _studies


def get_study_queue(study_id: str) -> EventQueue:
    return _studies[study_id]


async def run_study(
    study_id: str,
    request: FeasibilityStartRequest,
    queue: EventQueue,
) -> None:
    """Main pipeline coroutine. Runs as an asyncio background task."""
    fatal_agent_failures: list[str] = []

    try:
        await queue.put(
            SSEEvent.STUDY_STARTED,
            {
                "study_id": study_id,
                "output_language": request.output_language or "auto-detect",
                "analysis_horizon_years": request.analysis_horizon_years,
            },
        )

        # ── Phase 1: Intake ────────────────────────────────────────────────────
        try:
            feasibility_input = await IntakeFeasibilityAgent().run(study_id, request, queue)
        except IntakeHardBlockError as exc:
            await queue.put(
                SSEEvent.INTAKE_ERROR,
                {"study_id": study_id, "field": exc.field, "reason": str(exc)},
            )
            await queue.put(
                SSEEvent.STUDY_FAILED,
                {"study_id": study_id, "reason": str(exc)},
            )
            return

        # ── Phase 4: Market Sizing + Competitive Analysis (concurrent) ────────
        market_result, competitive_result = await asyncio.gather(
            MarketSizingAgent().run(feasibility_input, queue),
            CompetitiveAnalysisAgent().run(feasibility_input, queue),
            return_exceptions=True,
        )

        market_output: MarketSizingOutput | None = None
        if isinstance(market_result, Exception):
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {
                    "agent": "market_sizing",
                    "study_id": study_id,
                    "error": str(market_result),
                    "is_fatal": False,
                },
            )
        else:
            market_output = market_result
            await queue.put(
                SSEEvent.SECTION_READY,
                {
                    "section": "market_overview",
                    "language": market_output.output_language,
                    "review_recommended": market_output.review_recommended,
                    "data": {
                        "tam": market_output.tam.model_dump(),
                        "sam": market_output.sam.model_dump(),
                        "som": market_output.som.model_dump(),
                        "growth_rate_cagr": market_output.growth_rate_cagr,
                        "growth_rate_citations": [
                            c.model_dump() for c in market_output.growth_rate_citations
                        ],
                        "narrative": market_output.narrative.model_dump(),
                        "key_insights": market_output.key_insights,
                        "citations": [c.model_dump() for c in market_output.all_citations],
                        "search_queries_used": market_output.search_queries_used,
                    },
                },
            )

        competitive_output: CompetitiveAnalysisOutput | None = None
        if isinstance(competitive_result, Exception):
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {
                    "agent": "competitive",
                    "study_id": study_id,
                    "error": str(competitive_result),
                    "is_fatal": False,
                },
            )
        else:
            competitive_output = competitive_result
            await queue.put(
                SSEEvent.SECTION_READY,
                {
                    "section": "competitive_landscape",
                    "language": competitive_output.output_language,
                    "data": {
                        "competitors": [c.model_dump() for c in competitive_output.competitors],
                        "key_differentiators": competitive_output.key_differentiators,
                        "market_gaps": competitive_output.market_gaps,
                        "narrative": competitive_output.narrative.model_dump(),
                        "citations": [c.model_dump() for c in competitive_output.all_citations],
                        "search_queries_used": competitive_output.search_queries_used,
                    },
                },
            )

        # ── Phase 3: Financial Modeling ────────────────────────────────────────
        try:
            financial_output = await FinancialModelingAgent().run(feasibility_input, queue)
        except FinancialCalcError as exc:
            fatal_agent_failures.append("financial")
            await queue.put(
                SSEEvent.CALC_FAILED,
                {"study_id": study_id, "error": str(exc)},
            )
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {"agent": "financial", "study_id": study_id, "error": str(exc), "is_fatal": True},
            )
            await queue.put(
                SSEEvent.STUDY_FAILED,
                {"study_id": study_id, "reason": str(exc)},
            )
            return

        await queue.put(
            SSEEvent.SECTION_READY,
            {
                "section": "financial_feasibility",
                "language": financial_output.output_language,
                "review_recommended": financial_output.review_recommended,
                "data": {
                    "capex": {
                        "value": financial_output.capex_value,
                        "currency": financial_output.capex_currency,
                        "source": financial_output.capex_source,
                    },
                    "opex_monthly": {
                        "value": financial_output.opex_monthly_value,
                        "currency": financial_output.opex_monthly_currency,
                        "source": financial_output.opex_monthly_source,
                    },
                    "break_even_months": {
                        "value": financial_output.break_even.value["break_even_months"],
                        "source": "calculated",
                        "input_confidence": financial_output.break_even.input_confidence,
                        "calculation_trace": financial_output.break_even.calculation_trace.model_dump(),
                    },
                    "break_even_units": {
                        "value": financial_output.break_even.value["break_even_units"],
                        "source": "calculated",
                        "input_confidence": financial_output.break_even.input_confidence,
                    },
                    "roi_year_1": {
                        "value": financial_output.roi_year_1.value["roi_percent"],
                        "source": "calculated",
                        "input_confidence": financial_output.roi_year_1.input_confidence,
                        "calculation_trace": financial_output.roi_year_1.calculation_trace.model_dump(),
                    },
                    f"roi_year_{financial_output.analysis_horizon_years}": {
                        "value": financial_output.roi_year_n.value["roi_percent"],
                        "source": "calculated",
                        "input_confidence": financial_output.roi_year_n.input_confidence,
                        "calculation_trace": financial_output.roi_year_n.calculation_trace.model_dump(),
                    },
                    "npv": {
                        "value": financial_output.npv.value["npv"],
                        "is_positive": financial_output.npv.value["is_positive"],
                        "source": "calculated",
                        "input_confidence": financial_output.npv.input_confidence,
                        "calculation_trace": financial_output.npv.calculation_trace.model_dump(),
                    },
                    "sensitivity_analysis": {
                        "value": financial_output.sensitivity.value["scenarios"],
                        "source": "calculated",
                        "input_confidence": financial_output.sensitivity.input_confidence,
                        "calculation_trace": financial_output.sensitivity.calculation_trace.model_dump(),
                    },
                    "cash_flow": {
                        "payback_month": financial_output.cash_flow.value["payback_month"],
                        "final_position": financial_output.cash_flow.value["final_position"],
                        "source": "calculated",
                        "input_confidence": financial_output.cash_flow.input_confidence,
                        "calculation_trace": financial_output.cash_flow.calculation_trace.model_dump(),
                    },
                    "narrative": financial_output.narrative.model_dump(),
                },
            },
        )

        # ── Phase 5a: Risk Assessment ──────────────────────────────────────────
        risk_output: RiskAssessmentOutput | None = None
        try:
            risk_output = await RiskAssessmentAgent().run(
                feasibility_input, queue,
                market_output=market_output,
                competitive_output=competitive_output,
                financial_output=financial_output,
            )
            await queue.put(
                SSEEvent.SECTION_READY,
                {
                    "section": "risk_assessment",
                    "language": risk_output.output_language,
                    "data": {
                        "risks": [r.model_dump() for r in risk_output.risks],
                        "high_critical_count": risk_output.high_critical_count,
                        "narrative": risk_output.narrative.model_dump(),
                        "citations": [c.model_dump() for c in risk_output.citations],
                        "search_queries_used": risk_output.search_queries_used,
                    },
                },
            )
        except Exception as exc:
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {
                    "agent": "risk",
                    "study_id": study_id,
                    "error": str(exc),
                    "is_fatal": False,
                },
            )

        # ── Phase 5b: Synthesis ────────────────────────────────────────────────
        synthesis_output: FeasibilitySynthesisOutput | None = None
        try:
            synthesis_output = await FeasibilitySynthesisAgent().run(
                feasibility_input, queue,
                market_output=market_output,
                competitive_output=competitive_output,
                financial_output=financial_output,
                risk_output=risk_output,
                fatal_agent_failures=fatal_agent_failures,
            )
            await queue.put(
                SSEEvent.SECTION_READY,
                {
                    "section": "executive_summary",
                    "language": synthesis_output.output_language,
                    "data": {
                        "verdict": synthesis_output.verdict,
                        "confidence_score": synthesis_output.confidence_score,
                        "confidence_breakdown": synthesis_output.confidence_breakdown,
                        "executive_summary": synthesis_output.executive_summary.model_dump(),
                        "key_opportunities": synthesis_output.key_opportunities,
                        "key_risks": synthesis_output.key_risks,
                        "data_gaps": synthesis_output.data_gaps,
                        "contradictions": synthesis_output.contradictions,
                        "rationale": synthesis_output.rationale.model_dump(),
                    },
                },
            )
        except Exception as exc:
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {
                    "agent": "synthesis",
                    "study_id": study_id,
                    "error": str(exc),
                    "is_fatal": False,
                },
            )

        # ── Phase 6: Citation QC gate (flag-and-continue) ─────────────────────
        qc_output = None
        try:
            qc_output = await CitationValidationAgent().run(
                feasibility_input, queue,
                market_output=market_output,
                competitive_output=competitive_output,
                financial_output=financial_output,
                risk_output=risk_output,
                synthesis_output=synthesis_output,
            )
        except Exception as exc:
            logger.warning("Citation QC failed (non-fatal): %s", exc)
            await queue.put(
                SSEEvent.AGENT_FAILED,
                {"agent": "citation_qc", "study_id": study_id, "error": str(exc), "is_fatal": False},
            )

        # ── Study complete ─────────────────────────────────────────────────────
        await queue.put(
            SSEEvent.STUDY_COMPLETED,
            {
                "study_id": study_id,
                "verdict": synthesis_output.verdict if synthesis_output else "unavailable",
                "confidence_score": synthesis_output.confidence_score if synthesis_output else None,
                "output_language": feasibility_input.output_language,
                "fatal_agent_failures": fatal_agent_failures,
                "qc_summary": {
                    "citation_support_rate": qc_output.citation_support_rate if qc_output else None,
                    "citation_threshold_passed": qc_output.citation_threshold_passed if qc_output else None,
                    # executive_summary_trusted=False → front-end must gate display behind
                    # a hard warning overlay; the section_ready text may contain fabrications.
                    "executive_summary_trusted": qc_output.executive_summary_trusted if qc_output else None,
                    "total_flags": qc_output.total_flags if qc_output else None,
                    "contradictions_in_scope": True,
                    "contradictions_verified": qc_output.contradictions_verified if qc_output else None,
                    "contradictions_faithful": qc_output.contradictions_faithful if qc_output else None,
                    "flagged_sections": qc_output.flagged_sections if qc_output else [],
                } if qc_output else None,
            },
        )

    except Exception as exc:
        await queue.put(
            SSEEvent.STUDY_FAILED,
            {"study_id": study_id, "reason": f"Unexpected error: {exc}"},
        )
    finally:
        await queue.close()
