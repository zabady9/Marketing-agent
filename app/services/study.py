from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import BusinessProfile, Project, StudyResult
from app.orchestrator import run_feasibility_pipeline
from app.schemas.intake import FeasibilityInput, FieldWithSource, Source
from app.sse import EventQueue


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
        target_market_description=FieldWithSource(
            value=profile.target_market_description,
            source=Source(profile.target_market_description_source),
        ),
        target_market_geography=FieldWithSource(
            value=profile.target_market_geography,
            source=Source(profile.target_market_geography_source),
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
        team_size=team_size,
        analysis_horizon_years=profile.analysis_horizon_years,
    )


async def run_feasibility_study(
    db: Session, project: Project, queue: EventQueue | None = None
) -> StudyResult:
    """Runs the feasibility pipeline (phases 2-6) off the project's persisted
    BusinessProfile and stores the result on the project, overwriting any
    previous run in place (see StudyResult's documented V1 no-history limitation).

    `queue` is optional: pass one (e.g. from the future chat endpoint) to have
    progress events streamed live as the pipeline runs; omit it to just run to
    completion and get the final StudyResult back — no one needs to consume a
    queue that isn't passed in."""
    feasibility_input = feasibility_input_from_business_profile(project.business_profile)

    study_result = project.study_result
    if study_result is None:
        study_result = StudyResult(project_id=project.id)
        db.add(study_result)

    study_result.status = "running"
    study_result.started_at = datetime.utcnow()
    study_result.error = None
    db.commit()

    if queue is None:
        queue = EventQueue()

    pipeline_result = await run_feasibility_pipeline(
        feasibility_input.study_id, feasibility_input, queue
    )

    study_result.sections = pipeline_result.to_sections_payload()
    study_result.fatal_agent_failures = pipeline_result.fatal_agent_failures
    study_result.completed_at = datetime.utcnow()

    if pipeline_result.financial_error is not None:
        study_result.status = "failed"
        study_result.error = pipeline_result.financial_error
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

    db.commit()
    db.refresh(study_result)
    return study_result
