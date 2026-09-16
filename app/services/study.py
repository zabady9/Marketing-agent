from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Literal

from langsmith import traceable
from sqlalchemy.orm import Session

from app.agents.base import AgentSoftError
from app.agents.competitive import CompetitiveAnalysisAgent
from app.agents.financial import FinancialCalcError, FinancialModelingAgent
from app.agents.market_sizing import MarketSizingAgent
from app.agents.risk import RiskAssessmentAgent
from app.agents.synthesis import FeasibilitySynthesisAgent
from app.config import get_settings
from app.models import BusinessProfile, Project, StudyResult
from app.orchestrator import PipelineResult, run_feasibility_pipeline
from app.schemas.admin import StudyResultAdminCreate, StudyResultAdminUpdate
from app.schemas.intake import FeasibilityInput, FieldWithSource, Source
from app.services.glossary import get_or_create_glossary
from app.services.study_title import generate_study_title
from app.sse import EventQueue, SSEEvent

PipelinePhase = Literal["market_sizing", "competitive", "financial", "risk", "synthesis"]

_PHASE_REPORT_LABELS: dict[str, str] = {
    "market_sizing": "Market Sizing",
    "competitive": "Competitive Analysis",
    "financial": "Financial Analysis",
    "risk": "Risk Analysis",
    "synthesis": "Executive Summary",
}


async def _set_generated_title(
    study_result: StudyResult, feasibility_input: FeasibilityInput, report_label: str
) -> None:
    """Best-effort — a failed/timed-out title generation leaves
    study_result.title as None, and callers (the frontend) already have a
    deterministic fallback title for that case; never let this affect the
    study's own status."""
    settings = get_settings()
    study_result.title = await generate_study_title(
        business_description=feasibility_input.business_description.value or "",
        report_label=report_label,
        sections=study_result.sections,
        output_language=feasibility_input.output_language,
        google_api_key=settings.google_api_key,
        cheap_model=settings.cheap_model,
    )


def feasibility_input_from_business_profile(profile: BusinessProfile) -> FeasibilityInput:
    """Inverse of app.services.project._business_profile_from_feasibility_input —
    reconstructs the pipeline's input shape from a persisted BusinessProfile, so
    the study can be (re-)run without re-extracting from raw text."""
    team_size = (
        FieldWithSource(value=profile.team_size, source=Source(profile.team_size_source))
        if profile.team_size is not None
        else None
    )
    return FeasibilityInput(
        study_id=str(uuid.uuid4()),
        raw_user_input=profile.raw_user_input,
        detected_language=profile.detected_language,
        output_language=profile.output_language,
        business_description=FieldWithSource(
            value=profile.business_description,
            source=Source(profile.business_description_source),
        ),
        problem_statement=FieldWithSource(
            value=profile.problem_statement,
            source=Source(profile.problem_statement_source),
        ),
        unique_value_proposition=FieldWithSource(
            value=profile.unique_value_proposition,
            source=Source(profile.unique_value_proposition_source),
        ),
        target_market_description=FieldWithSource(
            value=profile.target_market_description,
            source=Source(profile.target_market_description_source),
        ),
        target_market_geography=FieldWithSource(
            value=profile.target_market_geography,
            source=Source(profile.target_market_geography_source),
        ),
        target_market_type=FieldWithSource(
            value=profile.target_market_type,
            source=Source(profile.target_market_type_source),
        ),
        business_model_type=FieldWithSource(
            value=profile.business_model_type,
            source=Source(profile.business_model_type_source),
        ),
        capex=FieldWithSource(
            value=profile.capex_amount,
            source=Source(profile.capex_source),
            low_confidence=profile.capex_low_confidence,
        ),
        capex_currency=profile.capex_currency,
        funding_source=FieldWithSource(
            value=profile.funding_source,
            source=Source(profile.funding_source_source),
        ),
        opex_monthly=FieldWithSource(
            value=profile.opex_monthly_amount,
            source=Source(profile.opex_monthly_source),
            low_confidence=profile.opex_monthly_low_confidence,
        ),
        opex_monthly_currency=profile.opex_monthly_currency,
        pricing_unit_price=FieldWithSource(
            value=profile.pricing_unit_price, source=Source(profile.pricing_source)
        ),
        pricing_currency=profile.pricing_currency,
        pricing_model=FieldWithSource(
            value=profile.pricing_model, source=Source(profile.pricing_model_source)
        ),
        expected_monthly_sales=FieldWithSource(
            value=profile.expected_monthly_sales,
            source=Source(profile.expected_monthly_sales_source),
            low_confidence=profile.expected_monthly_sales_low_confidence,
        ),
        competitors=profile.competitors,
        founder_risks=FieldWithSource(
            value=profile.founder_risks,
            source=Source(profile.founder_risks_source),
        ),
        team_size=team_size,
        key_roles_needed=FieldWithSource(
            value=profile.key_roles_needed,
            source=Source(profile.key_roles_needed_source),
        ),
        marketing_channels=FieldWithSource(
            value=profile.marketing_channels,
            source=Source(profile.marketing_channels_source),
        ),
        study_goal=FieldWithSource(
            value=profile.study_goal,
            source=Source(profile.study_goal_source),
        ),
        analysis_horizon_years=profile.analysis_horizon_years,
    )


@traceable(name="Feasibility Study", run_type="chain")
async def run_feasibility_study(
    db: Session, project: Project, queue: EventQueue | None = None
) -> StudyResult:
    """Runs the feasibility pipeline (phases 2-6) off the project's persisted
    BusinessProfile and persists a new StudyResult row for this run — a project
    accumulates one row per run, none of them overwritten.

    `queue` is optional: pass one (e.g. from the future chat endpoint) to have
    progress events streamed live as the pipeline runs; omit it to just run to
    completion and get the final StudyResult back — no one needs to consume a
    queue that isn't passed in."""
    feasibility_input = feasibility_input_from_business_profile(project.business_profile)

    if queue is None:
        queue = EventQueue()

    study_result = StudyResult(project_id=project.id)
    db.add(study_result)

    study_result.status = "running"
    study_result.started_at = datetime.utcnow()
    study_result.error = None
    db.commit()

    # Emitted before the pipeline runs so live consumers (e.g. the chat UI)
    # know which specific study this run's progress events belong to.
    await queue.put(SSEEvent.STUDY_STARTED, {"study_id": study_result.id})

    glossary = await get_or_create_glossary(db, feasibility_input.output_language)

    pipeline_result = await run_feasibility_pipeline(
        feasibility_input.study_id, feasibility_input, queue, glossary=glossary
    )

    study_result.sections = pipeline_result.to_sections_payload()
    study_result.fatal_agent_failures = pipeline_result.fatal_agent_failures
    study_result.completed_at = datetime.utcnow()

    if pipeline_result.financial_error is not None:
        study_result.status = "failed"
        study_result.error = pipeline_result.financial_error
    elif pipeline_result.orchestrator_error is not None:
        # The Deep Agent planner itself melted down (timeout, call-limit
        # breach, unexpected exception) — treated as fatal-equivalent, same
        # as a financial_error, since we don't reliably know which
        # invariants held partway through a failed planner run.
        study_result.status = "failed"
        study_result.error = pipeline_result.orchestrator_error
    else:
        study_result.status = "completed"
        synthesis_output = pipeline_result.synthesis_output
        study_result.verdict = synthesis_output.verdict if synthesis_output else "unavailable"
        study_result.confidence_score = (
            synthesis_output.confidence_score if synthesis_output else None
        )
        qc_output = pipeline_result.qc_output
        study_result.qc_summary = (
            {
                "citation_support_rate": qc_output.citation_support_rate,
                "citation_threshold_passed": qc_output.citation_threshold_passed,
                "executive_summary_trusted": qc_output.executive_summary_trusted,
                "total_flags": qc_output.total_flags,
                "contradictions_in_scope": True,
                "contradictions_verified": qc_output.contradictions_verified,
                "contradictions_faithful": qc_output.contradictions_faithful,
                "flagged_sections": qc_output.flagged_sections,
            }
            if qc_output is not None
            else None
        )
        await _set_generated_title(study_result, feasibility_input, "Feasibility Study")

    db.commit()
    db.refresh(study_result)
    return study_result


@traceable(name="Single Phase Study", run_type="chain")
async def run_single_phase_study(
    db: Session, project: Project, phase: PipelinePhase, queue: EventQueue | None = None
) -> StudyResult:
    """Runs just one pipeline phase (plus whatever prerequisite phases it
    needs) directly, bypassing the orchestrator/Deep Agent supervisor
    entirely — used for "just run market sizing" style requests from chat.
    Deliberately does NOT go through app.orchestrator: the phase-dependency
    chain is small and static (see PipelinePhase), so adding orchestrator-
    interface complexity (e.g. a stop_after_phase parameter) purely to serve
    single-phase requests isn't worth it. Persists as its own StudyResult row
    with study_type="single_phase" so callers can tell it apart from a full
    study — a partial run's `sections` dict will also contain whichever
    prerequisite sections were computed along the way (e.g. requesting
    "risk" also populates market_overview/competitive_landscape/
    financial_feasibility), which is expected, not a bug."""
    feasibility_input = feasibility_input_from_business_profile(project.business_profile)

    if queue is None:
        queue = EventQueue()

    study_result = StudyResult(project_id=project.id, study_type="single_phase", requested_phase=phase)
    db.add(study_result)
    study_result.status = "running"
    study_result.started_at = datetime.utcnow()
    study_result.error = None
    db.commit()

    await queue.put(
        SSEEvent.STUDY_STARTED,
        {"study_id": study_result.id, "study_type": "single_phase", "phase": phase},
    )

    result = PipelineResult()

    async def _run_market_only() -> None:
        try:
            result.market_output = await MarketSizingAgent().run(feasibility_input, queue)
        except AgentSoftError as exc:
            await queue.put(
                SSEEvent.AGENT_WARNING,
                {"agent": "market_sizing", "warning": f"Market sizing failed (non-fatal): {exc}"},
            )

    async def _run_competitive_only() -> None:
        try:
            result.competitive_output = await CompetitiveAnalysisAgent().run(feasibility_input, queue)
        except AgentSoftError as exc:
            await queue.put(
                SSEEvent.AGENT_WARNING,
                {"agent": "competitive", "warning": f"Competitive analysis failed (non-fatal): {exc}"},
            )

    async def _run_market_and_competitive() -> None:
        # Only called for phases where BOTH are genuine prerequisites (risk,
        # synthesis) — run concurrently purely as a latency optimization,
        # same as the full pipeline. Must NOT be used for a bare
        # "market_sizing" or "competitive" request: neither agent actually
        # depends on the other's output (see their .run() signatures), so
        # running both for a single-capability request would silently run
        # an agent the user never asked for.
        market_result, competitive_result = await asyncio.gather(
            MarketSizingAgent().run(feasibility_input, queue),
            CompetitiveAnalysisAgent().run(feasibility_input, queue),
            return_exceptions=True,
        )
        if isinstance(market_result, AgentSoftError):
            logger_warn = f"Market sizing failed (non-fatal): {market_result}"
            await queue.put(SSEEvent.AGENT_WARNING, {"agent": "market_sizing", "warning": logger_warn})
        elif not isinstance(market_result, Exception):
            result.market_output = market_result
        if isinstance(competitive_result, AgentSoftError):
            logger_warn = f"Competitive analysis failed (non-fatal): {competitive_result}"
            await queue.put(SSEEvent.AGENT_WARNING, {"agent": "competitive", "warning": logger_warn})
        elif not isinstance(competitive_result, Exception):
            result.competitive_output = competitive_result

    try:
        if phase == "market_sizing":
            await _run_market_only()
        elif phase == "competitive":
            await _run_competitive_only()
        elif phase in ("risk", "synthesis"):
            await _run_market_and_competitive()

        if phase in ("financial", "risk", "synthesis"):
            result.financial_output = await FinancialModelingAgent().run(feasibility_input, queue)

        if phase in ("risk", "synthesis"):
            result.risk_output = await RiskAssessmentAgent().run(
                feasibility_input, queue,
                market_output=result.market_output,
                competitive_output=result.competitive_output,
                financial_output=result.financial_output,
            )

        if phase == "synthesis":
            result.synthesis_output = await FeasibilitySynthesisAgent().run(
                feasibility_input, queue,
                market_output=result.market_output,
                competitive_output=result.competitive_output,
                financial_output=result.financial_output,
                risk_output=result.risk_output,
                fatal_agent_failures=result.fatal_agent_failures,
            )

        if phase == "market_sizing" and result.market_output is None:
            # The one single-phase-only request (no prerequisites) whose own
            # agent call failed — nothing else was computed to fall back on.
            raise AgentSoftError("Market sizing failed and produced no output.")
        if phase == "competitive" and result.competitive_output is None:
            raise AgentSoftError("Competitive analysis failed and produced no output.")
    except FinancialCalcError as exc:
        study_result.status = "failed"
        study_result.error = str(exc)
        study_result.sections = result.to_sections_payload()
        study_result.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(study_result)
        await _emit_section_ready_events(queue, study_result.sections)
        return study_result
    except AgentSoftError as exc:
        study_result.status = "failed"
        study_result.error = str(exc)
        study_result.sections = result.to_sections_payload()
        study_result.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(study_result)
        await _emit_section_ready_events(queue, study_result.sections)
        return study_result

    study_result.sections = result.to_sections_payload()
    study_result.completed_at = datetime.utcnow()
    study_result.status = "completed"
    if phase == "synthesis" and result.synthesis_output is not None:
        study_result.verdict = result.synthesis_output.verdict
        study_result.confidence_score = result.synthesis_output.confidence_score
    await _set_generated_title(study_result, feasibility_input, _PHASE_REPORT_LABELS[phase])
    db.commit()
    db.refresh(study_result)
    # Live-render whatever section(s) this run actually produced as a chat
    # card, the same way the full pipeline's SECTION_READY events do — a
    # single-phase run otherwise has no visual result at all beyond the
    # tool's one-line text summary.
    await _emit_section_ready_events(queue, study_result.sections)
    return study_result


async def _emit_section_ready_events(queue: EventQueue, sections: dict) -> None:
    for section_name, envelope in (sections or {}).items():
        if not isinstance(envelope, dict) or "data" not in envelope:
            continue
        await queue.put(SSEEvent.SECTION_READY, {"section": section_name, **envelope})


def list_study_results(db: Session, project: Project) -> list[StudyResult]:
    return (
        db.query(StudyResult)
        .filter(StudyResult.project_id == project.id, StudyResult.deleted_at.is_(None))
        .order_by(StudyResult.created_at.desc())
        .all()
    )


# ── Admin ──────────────────────────────────────────────────────────────────


def list_study_results_admin(
    db: Session,
    *,
    limit: int,
    offset: int,
    include_deleted: bool,
    project_id: str | None = None,
    status: str | None = None,
    verdict: str | None = None,
) -> tuple[list[StudyResult], int]:
    query = db.query(StudyResult)
    if not include_deleted:
        query = query.filter(StudyResult.deleted_at.is_(None))
    if project_id is not None:
        query = query.filter(StudyResult.project_id == project_id)
    if status is not None:
        query = query.filter(StudyResult.status == status)
    if verdict is not None:
        query = query.filter(StudyResult.verdict == verdict)
    total = query.count()
    items = query.order_by(StudyResult.created_at.desc()).offset(offset).limit(limit).all()
    return items, total


def get_study_result_admin(db: Session, study_id: str) -> StudyResult | None:
    return db.query(StudyResult).filter_by(id=study_id).one_or_none()


def create_study_result_admin(db: Session, payload: StudyResultAdminCreate) -> StudyResult:
    study = StudyResult(
        project_id=payload.project_id,
        status=payload.status,
        sections=payload.sections,
        verdict=payload.verdict,
        confidence_score=payload.confidence_score,
        qc_summary=payload.qc_summary,
        fatal_agent_failures=payload.fatal_agent_failures,
        error=payload.error,
        started_at=payload.started_at,
        completed_at=payload.completed_at,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def update_study_result(
    db: Session, study: StudyResult, patch: StudyResultAdminUpdate
) -> StudyResult:
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(study, field, value)
    db.commit()
    db.refresh(study)
    return study


def soft_delete_study_result(db: Session, study: StudyResult) -> StudyResult:
    study.deleted_at = datetime.utcnow()
    db.commit()
    db.refresh(study)
    return study


def restore_study_result(db: Session, study: StudyResult) -> StudyResult:
    study.deleted_at = None
    db.commit()
    db.refresh(study)
    return study
