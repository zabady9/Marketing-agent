"""
Tests for the chat-driven project lifecycle in app/services/project.py:
create_bare_project (the sole project-creation entrypoint now that the
wizard is gone), populate_business_profile (the chat-tool-driven equivalent
of what the old wizard did atomically at creation time), and
update_business_profile's source-override + additional_context-append
semantics added for chat's profile-gap-filling behavior.
"""

from __future__ import annotations

import pytest

from app.agents.intake import IntakeHardBlockError
from app.schemas.intake import FeasibilityInput, FeasibilityStartRequest, FieldWithSource, Source
from app.schemas.project import BusinessProfileUpdate
from app.services.project import create_bare_project, populate_business_profile, update_business_profile
from app.sse import EventQueue


def _feasibility_input(**overrides) -> FeasibilityInput:
    field = lambda v: FieldWithSource(value=v)  # noqa: E731
    defaults = dict(
        study_id="study-1",
        raw_user_input="A test business idea, described in enough detail.",
        detected_language="en",
        output_language="en",
        business_description=field("A test business"),
        problem_statement=field("A real problem"),
        unique_value_proposition=field("A real differentiator"),
        target_market_description=field("A target market"),
        target_market_geography=field("A geography"),
        target_market_type=field("B2C"),
        business_model_type=field("SaaS"),
        capex=field(1000.0),
        capex_currency="USD",
        funding_source=field("self-funded"),
        opex_monthly=field(100.0),
        opex_monthly_currency="USD",
        pricing_unit_price=field(10.0),
        pricing_currency="USD",
        pricing_model=field("subscription"),
        expected_monthly_sales=field(50.0),
        competitors=[],
        founder_risks=field("None stated"),
        team_size=field(1),
        key_roles_needed=field([]),
        marketing_channels=field([]),
        study_goal=field("validate idea"),
        analysis_horizon_years=3,
    )
    defaults.update(overrides)
    return FeasibilityInput(**defaults)


class _FakeIntakeAgent:
    """Stands in for IntakeFeasibilityAgent — either raises the hard block
    (simulating "no price given") or returns a canned FeasibilityInput,
    without touching an LLM or Tavily."""

    def __init__(self, result: FeasibilityInput | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def run(self, study_id, request, queue):
        if self._error is not None:
            raise self._error
        return self._result


class TestCreateBareProject:
    def test_creates_project_with_no_business_profile(self, db_session):
        project = create_bare_project(db_session)

        assert project.id is not None
        assert project.name == "Untitled Project"
        assert project.business_profile is None


class TestPopulateBusinessProfile:
    async def test_hard_blocks_on_missing_price_and_leaves_project_untouched(
        self, db_session, monkeypatch
    ):
        project = create_bare_project(db_session)
        monkeypatch.setattr(
            "app.services.project.IntakeFeasibilityAgent",
            lambda: _FakeIntakeAgent(
                error=IntakeHardBlockError(field="pricing_unit_price", reason="need a price")
            ),
        )

        request = FeasibilityStartRequest(business_description="A business with no price yet.")
        with pytest.raises(IntakeHardBlockError):
            await populate_business_profile(db_session, project, request)

        db_session.refresh(project)
        assert project.business_profile is None
        assert project.name == "Untitled Project"

    async def test_succeeds_once_extraction_has_everything(self, db_session, monkeypatch):
        project = create_bare_project(db_session)
        monkeypatch.setattr(
            "app.services.project.IntakeFeasibilityAgent",
            lambda: _FakeIntakeAgent(result=_feasibility_input()),
        )

        request = FeasibilityStartRequest(
            business_description="A test business idea, described in enough detail.",
            pricing_unit_price=10.0,
        )
        updated = await populate_business_profile(db_session, project, request)

        assert updated.business_profile is not None
        assert updated.business_profile.business_description == "A test business"
        assert updated.name != "Untitled Project"


class TestUpdateBusinessProfileSource:
    def test_defaults_to_user_provided(self, db_session, make_project):
        project = make_project()
        profile = update_business_profile(
            db_session, project.business_profile, BusinessProfileUpdate(founder_risks="New risk")
        )
        assert profile.founder_risks_source == Source.USER_PROVIDED.value

    def test_explicit_estimated_source_persists(self, db_session, make_project):
        project = make_project()
        profile = update_business_profile(
            db_session,
            project.business_profile,
            BusinessProfileUpdate(founder_risks="Researched risk"),
            source=Source.ESTIMATED,
        )
        assert profile.founder_risks_source == Source.ESTIMATED.value


class TestAdditionalContextAppends:
    def test_two_patches_append_rather_than_overwrite(self, db_session, make_project):
        project = make_project()
        profile = update_business_profile(
            db_session,
            project.business_profile,
            BusinessProfileUpdate(additional_context="First note."),
        )
        assert profile.additional_context == "First note."

        profile = update_business_profile(
            db_session,
            project.business_profile,
            BusinessProfileUpdate(additional_context="Second note."),
        )
        assert profile.additional_context == "First note.\nSecond note."
