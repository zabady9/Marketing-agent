from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.agents.intake import IntakeFeasibilityAgent
from app.models import BusinessProfile, Project
from app.schemas.intake import FeasibilityInput, FeasibilityStartRequest, Source
from app.schemas.project import BusinessProfileResponse, BusinessProfileUpdate, SourcedValue
from app.sse import EventQueue

# Maps a directly-PATCHable BusinessProfile column to the *_source column that
# should flip to "user_provided" when that field is edited by hand.
_SOURCE_COLUMN_FOR: dict[str, str] = {
    "business_description": "business_description_source",
    "problem_statement": "problem_statement_source",
    "unique_value_proposition": "unique_value_proposition_source",
    "target_market_description": "target_market_description_source",
    "target_market_geography": "target_market_geography_source",
    "target_market_type": "target_market_type_source",
    "business_model_type": "business_model_type_source",
    "capex_amount": "capex_source",
    "funding_source": "funding_source_source",
    "opex_monthly_amount": "opex_monthly_source",
    "pricing_unit_price": "pricing_source",
    "pricing_model": "pricing_model_source",
    "expected_monthly_sales": "expected_monthly_sales_source",
    "founder_risks": "founder_risks_source",
    "team_size": "team_size_source",
    "key_roles_needed": "key_roles_needed_source",
    "marketing_channels": "marketing_channels_source",
    "study_goal": "study_goal_source",
}

# Maps a column to the *_low_confidence column that should clear to False when
# that field is edited by hand (only fields that track low_confidence at all).
_LOW_CONFIDENCE_COLUMN_FOR: dict[str, str] = {
    "capex_amount": "capex_low_confidence",
    "opex_monthly_amount": "opex_monthly_low_confidence",
    "expected_monthly_sales": "expected_monthly_sales_low_confidence",
}


def _derive_project_name(business_description: str) -> str:
    text = business_description.strip()
    if not text:
        return "Untitled Project"
    return text if len(text) <= 80 else text[:77].rstrip() + "..."


def _business_profile_from_feasibility_input(input_: FeasibilityInput) -> BusinessProfile:
    team_size_value = input_.team_size.value if input_.team_size is not None else None
    team_size_source = (
        input_.team_size.source.value if input_.team_size is not None else None
    )
    return BusinessProfile(
        raw_user_input=input_.raw_user_input,
        detected_language=input_.detected_language,
        output_language=input_.output_language,
        business_description=input_.business_description.value,
        business_description_source=input_.business_description.source.value,
        problem_statement=input_.problem_statement.value,
        problem_statement_source=input_.problem_statement.source.value,
        unique_value_proposition=input_.unique_value_proposition.value,
        unique_value_proposition_source=input_.unique_value_proposition.source.value,
        target_market_description=input_.target_market_description.value,
        target_market_description_source=input_.target_market_description.source.value,
        target_market_geography=input_.target_market_geography.value,
        target_market_geography_source=input_.target_market_geography.source.value,
        target_market_type=input_.target_market_type.value,
        target_market_type_source=input_.target_market_type.source.value,
        business_model_type=input_.business_model_type.value,
        business_model_type_source=input_.business_model_type.source.value,
        capex_amount=input_.capex.value,
        # The LLM's structured extraction sometimes returns "" instead of falling
        # back to its declared "USD" default — guard at the persistence boundary
        # since a silent "" here would corrupt the financial model, not error out.
        capex_currency=input_.capex_currency or "USD",
        capex_source=input_.capex.source.value,
        capex_low_confidence=input_.capex.low_confidence,
        funding_source=input_.funding_source.value,
        funding_source_source=input_.funding_source.source.value,
        opex_monthly_amount=input_.opex_monthly.value,
        opex_monthly_currency=input_.opex_monthly_currency or "USD",
        opex_monthly_source=input_.opex_monthly.source.value,
        opex_monthly_low_confidence=input_.opex_monthly.low_confidence,
        pricing_unit_price=input_.pricing_unit_price.value,
        pricing_currency=input_.pricing_currency,
        pricing_source=input_.pricing_unit_price.source.value,
        pricing_model=input_.pricing_model.value,
        pricing_model_source=input_.pricing_model.source.value,
        expected_monthly_sales=input_.expected_monthly_sales.value,
        expected_monthly_sales_source=input_.expected_monthly_sales.source.value,
        expected_monthly_sales_low_confidence=input_.expected_monthly_sales.low_confidence,
        competitors=input_.competitors,
        founder_risks=input_.founder_risks.value,
        founder_risks_source=input_.founder_risks.source.value,
        team_size=team_size_value,
        team_size_source=team_size_source,
        key_roles_needed=input_.key_roles_needed.value,
        key_roles_needed_source=input_.key_roles_needed.source.value,
        marketing_channels=input_.marketing_channels.value,
        marketing_channels_source=input_.marketing_channels.source.value,
        study_goal=input_.study_goal.value,
        study_goal_source=input_.study_goal.source.value,
        analysis_horizon_years=input_.analysis_horizon_years,
    )


async def create_project_from_questionnaire(
    db: Session, request: FeasibilityStartRequest
) -> Project:
    """Runs intake extraction; on success, persists Project + BusinessProfile in
    one transaction. Raises IntakeHardBlockError (e.g. missing price) before
    anything is written — no draft/orphan project rows on hard failure."""
    queue = EventQueue()  # progress events go here; unused for this sync creation path
    study_id = str(uuid.uuid4())
    feasibility_input = await IntakeFeasibilityAgent().run(study_id, request, queue)

    project = Project(name=_derive_project_name(feasibility_input.business_description.value))
    project.business_profile = _business_profile_from_feasibility_input(feasibility_input)

    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[Project]:
    return (
        db.query(Project)
        .filter(Project.deleted_at.is_(None))
        .order_by(Project.created_at.desc())
        .all()
    )


def get_project(db: Session, project_id: str) -> Project | None:
    return (
        db.query(Project)
        .filter(Project.id == project_id, Project.deleted_at.is_(None))
        .one_or_none()
    )


def get_business_profile(db: Session, project_id: str) -> BusinessProfile | None:
    return (
        db.query(BusinessProfile)
        .filter(BusinessProfile.project_id == project_id, BusinessProfile.deleted_at.is_(None))
        .one_or_none()
    )


def business_profile_to_response(profile: BusinessProfile) -> BusinessProfileResponse:
    team_size = (
        SourcedValue(value=profile.team_size, source=profile.team_size_source)
        if profile.team_size_source is not None
        else None
    )
    return BusinessProfileResponse(
        project_id=profile.project_id,
        raw_user_input=profile.raw_user_input,
        detected_language=profile.detected_language,
        output_language=profile.output_language,
        business_description=SourcedValue(
            value=profile.business_description, source=profile.business_description_source
        ),
        problem_statement=SourcedValue(
            value=profile.problem_statement, source=profile.problem_statement_source
        ),
        unique_value_proposition=SourcedValue(
            value=profile.unique_value_proposition,
            source=profile.unique_value_proposition_source,
        ),
        target_market_description=SourcedValue(
            value=profile.target_market_description,
            source=profile.target_market_description_source,
        ),
        target_market_geography=SourcedValue(
            value=profile.target_market_geography,
            source=profile.target_market_geography_source,
        ),
        target_market_type=SourcedValue(
            value=profile.target_market_type, source=profile.target_market_type_source
        ),
        business_model_type=SourcedValue(
            value=profile.business_model_type, source=profile.business_model_type_source
        ),
        capex=SourcedValue(
            value=profile.capex_amount,
            source=profile.capex_source,
            low_confidence=profile.capex_low_confidence,
        ),
        capex_currency=profile.capex_currency,
        funding_source=SourcedValue(
            value=profile.funding_source, source=profile.funding_source_source
        ),
        opex_monthly=SourcedValue(
            value=profile.opex_monthly_amount,
            source=profile.opex_monthly_source,
            low_confidence=profile.opex_monthly_low_confidence,
        ),
        opex_monthly_currency=profile.opex_monthly_currency,
        pricing_unit_price=SourcedValue(
            value=profile.pricing_unit_price, source=profile.pricing_source
        ),
        pricing_currency=profile.pricing_currency,
        pricing_model=SourcedValue(
            value=profile.pricing_model, source=profile.pricing_model_source
        ),
        expected_monthly_sales=SourcedValue(
            value=profile.expected_monthly_sales,
            source=profile.expected_monthly_sales_source,
            low_confidence=profile.expected_monthly_sales_low_confidence,
        ),
        competitors=profile.competitors,
        founder_risks=SourcedValue(
            value=profile.founder_risks, source=profile.founder_risks_source
        ),
        team_size=team_size,
        key_roles_needed=SourcedValue(
            value=profile.key_roles_needed, source=profile.key_roles_needed_source
        ),
        marketing_channels=SourcedValue(
            value=profile.marketing_channels, source=profile.marketing_channels_source
        ),
        study_goal=SourcedValue(
            value=profile.study_goal, source=profile.study_goal_source
        ),
        analysis_horizon_years=profile.analysis_horizon_years,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def update_business_profile(
    db: Session, profile: BusinessProfile, patch: BusinessProfileUpdate
) -> BusinessProfile:
    data = patch.model_dump(exclude_unset=True)

    if "competitors" in data:
        data["competitors"] = [
            {"name": name, "source": Source.USER_PROVIDED.value} for name in data["competitors"]
        ]

    for field, value in data.items():
        setattr(profile, field, value)
        source_column = _SOURCE_COLUMN_FOR.get(field)
        if source_column:
            setattr(profile, source_column, Source.USER_PROVIDED.value)
        low_confidence_column = _LOW_CONFIDENCE_COLUMN_FOR.get(field)
        if low_confidence_column:
            setattr(profile, low_confidence_column, False)

    db.commit()
    db.refresh(profile)
    return profile
