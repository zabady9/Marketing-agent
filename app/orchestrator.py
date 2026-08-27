from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from app.agents.competitive import CompetitiveAnalysisAgent
from app.agents.financial import FinancialCalcError, FinancialModelingAgent
from app.agents.intake import IntakeFeasibilityAgent, IntakeHardBlockError
from app.agents.market_sizing import MarketSizingAgent
from app.agents.citation_qc import CitationValidationAgent
from app.agents.risk import RiskAssessmentAgent
from app.agents.synthesis import FeasibilitySynthesisAgent
from app.schemas.intake import FeasibilityInput, FeasibilityStartRequest
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.qc import CitationQCOutput
from app.schemas.report import FinancialModelOutput
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


def _market_overview_data(output: MarketSizingOutput) -> dict:
    return {
        "tam": output.tam.model_dump(),
        "sam": output.sam.model_dump(),
        "som": output.som.model_dump(),
        "growth_rate_cagr": output.growth_rate_cagr,
        "growth_rate_citations": [c.model_dump() for c in output.growth_rate_citations],
        "narrative": output.narrative.model_dump(),
        "key_insights": output.key_insights,
        "citations": [c.model_dump() for c in output.all_citations],
        "search_queries_used": output.search_queries_used,
    }


def _competitive_landscape_data(output: CompetitiveAnalysisOutput) -> dict:
    return {
        "competitors": [c.model_dump() for c in output.competitors],
        "key_differentiators": output.key_differentiators,
        "market_gaps": output.market_gaps,
        "narrative": output.narrative.model_dump(),
        "citations": [c.model_dump() for c in output.all_citations],
        "search_queries_used": output.search_queries_used,
    }


def _financial_feasibility_data(output: FinancialModelOutput) -> dict:
    return {
        "capex": {
            "value": output.capex_value,
            "currency": output.capex_currency,
            "source": output.capex_source,
        },
        "opex_monthly": {
            "value": output.opex_monthly_value,
            "currency": output.opex_monthly_currency,
            "source": output.opex_monthly_source,
        },
        "break_even_months": {
            "value": output.break_even.value["break_even_months"],
            "source": "calculated",
            "input_confidence": output.break_even.input_confidence,
            "calculation_trace": output.break_even.calculation_trace.model_dump(),
        },
        "break_even_units": {
            "value": output.break_even.value["break_even_units"],
            "source": "calculated",
            "input_confidence": output.break_even.input_confidence,
        },
        "roi_year_1": {
            "value": output.roi_year_1.value["roi_percent"],
            "source": "calculated",
            "input_confidence": output.roi_year_1.input_confidence,
            "calculation_trace": output.roi_year_1.calculation_trace.model_dump(),
        },
        f"roi_year_{output.analysis_horizon_years}": {
            "value": output.roi_year_n.value["roi_percent"],
            "source": "calculated",
            "input_confidence": output.roi_year_n.input_confidence,
            "calculation_trace": output.roi_year_n.calculation_trace.model_dump(),
        },
        "npv": {
            "value": output.npv.value["npv"],
            "is_positive": output.npv.value["is_positive"],
            "source": "calculated",
            "input_confidence": output.npv.input_confidence,
            "calculation_trace": output.npv.calculation_trace.model_dump(),
        },
        "sensitivity_analysis": {
            "value": output.sensitivity.value["scenarios"],
            "source": "calculated",
            "input_confidence": output.sensitivity.input_confidence,
            "calculation_trace": output.sensitivity.calculation_trace.model_dump(),
        },
        "cash_flow": {
            "payback_month": output.cash_flow.value["payback_month"],
            "final_position": output.cash_flow.value["final_position"],
            "source": "calculated",
            "input_confidence": output.cash_flow.input_confidence,
            "calculation_trace": output.cash_flow.calculation_trace.model_dump(),
        },
        "narrative": output.narrative.model_dump(),
    }


def _risk_assessment_data(output: RiskAssessmentOutput) -> dict:
    return {
        "risks": [r.model_dump() for r in output.risks],
        "high_critical_count": output.high_critical_count,
        "narrative": output.narrative.model_dump(),
        "citations": [c.model_dump() for c in output.citations],
        "search_queries_used": output.search_queries_used,
    }


def _executive_summary_data(output: FeasibilitySynthesisOutput) -> dict:
    return {
        "verdict": output.verdict,
        "confidence_score": output.confidence_score,
        "confidence_breakdown": output.confidence_breakdown,
        "executive_summary": output.executive_summary.model_dump(),
        "key_opportunities": output.key_opportunities,
        "key_risks": output.key_risks,
        "data_gaps": output.data_gaps,
        "contradictions": output.contradictions,
        "rationale": output.rationale.model_dump(),
    }


@dataclass
class PipelineResult:
    """Everything phases 2-6 produce. `financial_error` set means the pipeline
    hit the same fatal condition run_study always treated as STUDY_FAILED —
    callers must check it before treating the result as usable."""

    market_output: MarketSizingOutput | None = None
    competitive_output: CompetitiveAnalysisOutput | None = None
    financial_output: FinancialModelOutput | None = None
    financial_error: str | None = None
    risk_output: RiskAssessmentOutput | None = None
    synthesis_output: FeasibilitySynthesisOutput | None = None
    qc_output: CitationQCOutput | None = None
    fatal_agent_failures: list[str] = field(default_factory=list)

    def to_sections_payload(self) -> dict[str, dict]:
        """Same envelope shape ({language, review_recommended?, data}) as the
        SECTION_READY SSE events, keyed by section name — reusable both by a
        live SSE stream and by a StudyResult persisted for later viewing.
        Only sections that actually completed are included."""
        sections: dict[str, dict] = {}
        if self.market_output is not None:
            sections["market_overview"] = {
                "language": self.market_output.output_language,
                "review_recommended": self.market_output.review_recommended,
                "data": _market_overview_data(self.market_output),
            }
        if self.competitive_output is not None:
            sections["competitive_landscape"] = {
                "language": self.competitive_output.output_language,
                "data": _competitive_landscape_data(self.competitive_output),
            }
        if self.financial_output is not None:
            sections["financial_feasibility"] = {
                "language": self.financial_output.output_language,
                "review_recommended": self.financial_output.review_recommended,
                "data": _financial_feasibility_data(self.financial_output),
            }
        if self.risk_output is not None:
            sections["risk_assessment"] = {
                "language": self.risk_output.output_language,
                "data": _risk_assessment_data(self.risk_output),
            }
        if self.synthesis_output is not None:
            sections["executive_summary"] = {
                "language": self.synthesis_output.output_language,
                "data": _executive_summary_data(self.synthesis_output),
            }
        return sections


async def run_feasibility_pipeline(
    study_id: str,
    feasibility_input: FeasibilityInput,
    queue: EventQueue,
) -> PipelineResult:
    """Phases 2-6 of the pipeline: market sizing + competitive analysis (run
    concurrently), financial modeling, risk assessment, synthesis, and the
    citation QC gate. Emits the same SSE events run_study always emitted for
    these phases. Does NOT run intake (phase 1) — the caller supplies an
    already-built FeasibilityInput, whether freshly extracted from raw text
    (see run_study) or reconstructed from a persisted BusinessProfile."""
    result = PipelineResult()

    # ── Phase 4: Market Sizing + Competitive Analysis (concurrent) ────────
    market_result, competitive_result = await asyncio.gather(
        MarketSizingAgent().run(feasibility_input, queue),
        CompetitiveAnalysisAgent().run(feasibility_input, queue),
        return_exceptions=True,
    )

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
        result.market_output = market_result
        await queue.put(
            SSEEvent.SECTION_READY,
            {
                "section": "market_overview",
                "language": result.market_output.output_language,
                "review_recommended": result.market_output.review_recommended,
                "data": _market_overview_data(result.market_output),
            },
        )

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
        result.competitive_output = competitive_result
        await queue.put(
            SSEEvent.SECTION_READY,
            {
                "section": "competitive_landscape",
                "language": result.competitive_output.output_language,
                "data": _competitive_landscape_data(result.competitive_output),
            },
        )

    # ── Phase 3: Financial Modeling ────────────────────────────────────────
    try:
        result.financial_output = await FinancialModelingAgent().run(feasibility_input, queue)
    except FinancialCalcError as exc:
        result.fatal_agent_failures.append("financial")
        result.financial_error = str(exc)
        await queue.put(
            SSEEvent.CALC_FAILED,
            {"study_id": study_id, "error": str(exc)},
        )
        await queue.put(
            SSEEvent.AGENT_FAILED,
            {"agent": "financial", "study_id": study_id, "error": str(exc), "is_fatal": True},
        )
        return result

    financial_output = result.financial_output
    await queue.put(
        SSEEvent.SECTION_READY,
        {
            "section": "financial_feasibility",
            "language": financial_output.output_language,
            "review_recommended": financial_output.review_recommended,
            "data": _financial_feasibility_data(financial_output),
        },
    )

    # ── Phase 5a: Risk Assessment ──────────────────────────────────────────
    try:
        result.risk_output = await RiskAssessmentAgent().run(
            feasibility_input, queue,
            market_output=result.market_output,
            competitive_output=result.competitive_output,
            financial_output=result.financial_output,
        )
        await queue.put(
            SSEEvent.SECTION_READY,
            {
                "section": "risk_assessment",
                "language": result.risk_output.output_language,
                "data": _risk_assessment_data(result.risk_output),
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
    try:
        result.synthesis_output = await FeasibilitySynthesisAgent().run(
            feasibility_input, queue,
            market_output=result.market_output,
            competitive_output=result.competitive_output,
            financial_output=result.financial_output,
            risk_output=result.risk_output,
            fatal_agent_failures=result.fatal_agent_failures,
        )
        await queue.put(
            SSEEvent.SECTION_READY,
            {
                "section": "executive_summary",
                "language": result.synthesis_output.output_language,
                "data": _executive_summary_data(result.synthesis_output),
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
    try:
        result.qc_output = await CitationValidationAgent().run(
            feasibility_input, queue,
            market_output=result.market_output,
            competitive_output=result.competitive_output,
            financial_output=result.financial_output,
            risk_output=result.risk_output,
            synthesis_output=result.synthesis_output,
        )
    except Exception as exc:
        logger.warning("Citation QC failed (non-fatal): %s", exc)
        await queue.put(
            SSEEvent.AGENT_FAILED,
            {"agent": "citation_qc", "study_id": study_id, "error": str(exc), "is_fatal": False},
        )

    return result


def build_study_completed_payload(
    study_id: str,
    feasibility_input: FeasibilityInput,
    result: PipelineResult,
) -> dict:
    """Same STUDY_COMPLETED payload shape run_study always emitted, factored out
    so project-scoped runs (app/services/study.py) can build an identical
    summary without duplicating this shape."""
    qc_output = result.qc_output
    synthesis_output = result.synthesis_output
    return {
        "study_id": study_id,
        "verdict": synthesis_output.verdict if synthesis_output else "unavailable",
        "confidence_score": synthesis_output.confidence_score if synthesis_output else None,
        "output_language": feasibility_input.output_language,
        "fatal_agent_failures": result.fatal_agent_failures,
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
    }


async def run_study(
    study_id: str,
    request: FeasibilityStartRequest,
    queue: EventQueue,
) -> None:
    """Entry point for the standalone /api/feasibility/start flow (stateless,
    no persistence): runs intake (phase 1) then the shared pipeline."""
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

        result = await run_feasibility_pipeline(study_id, feasibility_input, queue)

        if result.financial_error is not None:
            await queue.put(
                SSEEvent.STUDY_FAILED,
                {"study_id": study_id, "reason": result.financial_error},
            )
            return

        # ── Study complete ─────────────────────────────────────────────────────
        await queue.put(
            SSEEvent.STUDY_COMPLETED,
            build_study_completed_payload(study_id, feasibility_input, result),
        )

    except Exception as exc:
        await queue.put(
            SSEEvent.STUDY_FAILED,
            {"study_id": study_id, "reason": f"Unexpected error: {exc}"},
        )
    finally:
        await queue.close()
