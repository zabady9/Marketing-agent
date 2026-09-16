"""
Tests for app/services/study.py::run_single_phase_study — the entry point
for "just run market sizing" style chat requests. Bypasses the orchestrator
entirely; asserts the phase-dependency chain is respected (e.g. requesting
"risk" also computes market/competitive/financial, "market_sizing" alone
computes nothing else) and that the resulting StudyResult is persisted with
study_type="single_phase" / requested_phase set.
"""

from unittest.mock import AsyncMock

import pytest

import app.services.study as study_module
from app.schemas.market import CompetitiveAnalysisOutput, MarketSizingOutput
from app.schemas.report import FinancialModelOutput
from app.schemas.risk import RiskAssessmentOutput
from app.schemas.synthesis import FeasibilitySynthesisOutput
from app.sse import EventQueue


@pytest.fixture(autouse=True)
def _no_real_title_generation(monkeypatch):
    # These tests use realistic (non-empty) section fixtures, so
    # generate_study_title's "nothing to summarize" short-circuit doesn't
    # apply here — without this, every test in this file would attempt a
    # real Gemini call using the fake GOOGLE_API_KEY the test env sets.
    monkeypatch.setattr(study_module, "generate_study_title", AsyncMock(return_value=None))


def _patch_agent(monkeypatch, agent_class_name: str, return_value):
    mock_run = AsyncMock(return_value=return_value)
    monkeypatch.setattr(f"app.services.study.{agent_class_name}.run", mock_run)
    return mock_run


class TestGeneratedTitle:
    async def test_successful_title_generation_is_persisted(self, db_session, make_project, monkeypatch):
        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        title_mock = AsyncMock(return_value="Competitive Landscape: No Direct Rivals Found")
        monkeypatch.setattr(study_module, "generate_study_title", title_mock)

        project = make_project()
        result = await study_module.run_single_phase_study(
            db_session, project, "competitive", EventQueue()
        )

        assert result.title == "Competitive Landscape: No Direct Rivals Found"
        title_mock.assert_awaited_once()
        assert title_mock.await_args.kwargs["report_label"] == "Competitive Analysis"

    async def test_failed_title_generation_leaves_title_none_without_failing_the_run(
        self, db_session, make_project, monkeypatch
    ):
        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        monkeypatch.setattr(study_module, "generate_study_title", AsyncMock(return_value=None))

        project = make_project()
        result = await study_module.run_single_phase_study(
            db_session, project, "competitive", EventQueue()
        )

        assert result.status == "completed"
        assert result.title is None


class _CapturingEventQueue(EventQueue):
    def __init__(self):
        super().__init__()
        self.events: list = []

    async def put(self, event, data):
        self.events.append((event, data))
        await super().put(event, data)


class TestSectionReadyEmission:
    """A single-phase run must live-render its result as a chat card — the
    same SECTION_READY event the full pipeline emits — not just leave the
    tool's one-line text summary as the only visible outcome."""

    async def test_competitive_only_emits_exactly_the_competitive_section(
        self, db_session, make_project, monkeypatch
    ):
        from app.sse import SSEEvent

        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        queue = _CapturingEventQueue()
        await study_module.run_single_phase_study(db_session, project, "competitive", queue)

        section_events = [data for event, data in queue.events if event == SSEEvent.SECTION_READY]
        assert len(section_events) == 1
        assert section_events[0]["section"] == "competitive_landscape"
        assert "data" in section_events[0]

    async def test_risk_only_emits_a_card_for_every_computed_section(
        self, db_session, make_project, monkeypatch
    ):
        from app.sse import SSEEvent

        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        queue = _CapturingEventQueue()
        await study_module.run_single_phase_study(db_session, project, "risk", queue)

        sections = {data["section"] for event, data in queue.events if event == SSEEvent.SECTION_READY}
        assert sections == {
            "market_overview", "competitive_landscape", "financial_feasibility", "risk_assessment",
        }


class TestSinglePhaseDependencyChain:
    async def test_market_sizing_alone_does_not_run_anything_else(
        self, db_session, make_project, monkeypatch
    ):
        market_mock = _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        competitive_mock = _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        financial_mock = _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        risk_mock = _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        synthesis_mock = _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        result = await study_module.run_single_phase_study(
            db_session, project, "market_sizing", EventQueue()
        )

        assert market_mock.call_count == 1
        # Competitive analysis is NOT a prerequisite of market sizing (its
        # .run() signature takes no market_output) — a bare market_sizing
        # request must not run it too.
        assert competitive_mock.call_count == 0
        assert financial_mock.call_count == 0
        assert risk_mock.call_count == 0
        assert synthesis_mock.call_count == 0

        assert result.status == "completed"
        assert result.study_type == "single_phase"
        assert result.requested_phase == "market_sizing"
        assert "market_overview" in result.sections

    async def test_competitive_alone_does_not_run_market_sizing(
        self, db_session, make_project, monkeypatch
    ):
        market_mock = _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        competitive_mock = _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        financial_mock = _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        risk_mock = _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        synthesis_mock = _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        result = await study_module.run_single_phase_study(
            db_session, project, "competitive", EventQueue()
        )

        # The symmetric bug: market sizing is NOT a prerequisite of
        # competitive analysis either — a bare competitive request must not
        # run market sizing too.
        assert market_mock.call_count == 0
        assert competitive_mock.call_count == 1
        assert financial_mock.call_count == 0
        assert risk_mock.call_count == 0
        assert synthesis_mock.call_count == 0

        assert result.status == "completed"
        assert result.requested_phase == "competitive"
        assert "competitive_landscape" in result.sections
        assert "market_overview" not in result.sections

    async def test_risk_requires_market_competitive_and_financial_first(
        self, db_session, make_project, monkeypatch
    ):
        market_mock = _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        competitive_mock = _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        financial_mock = _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        risk_mock = _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        synthesis_mock = _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        result = await study_module.run_single_phase_study(db_session, project, "risk", EventQueue())

        assert market_mock.call_count == 1
        assert competitive_mock.call_count == 1
        assert financial_mock.call_count == 1
        assert risk_mock.call_count == 1
        assert synthesis_mock.call_count == 0  # synthesis was NOT requested — must not run

        assert result.status == "completed"
        assert result.requested_phase == "risk"
        assert "risk_assessment" in result.sections
        # Prerequisite sections are expected to be present too, not a bug.
        assert "financial_feasibility" in result.sections

    async def test_synthesis_runs_the_full_prerequisite_chain(
        self, db_session, make_project, monkeypatch
    ):
        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        _patch_agent(monkeypatch, "FinancialModelingAgent", _financial_output())
        _patch_agent(monkeypatch, "RiskAssessmentAgent", _risk_output())
        synthesis_mock = _patch_agent(monkeypatch, "FeasibilitySynthesisAgent", _synthesis_output())

        project = make_project()
        result = await study_module.run_single_phase_study(db_session, project, "synthesis", EventQueue())

        assert synthesis_mock.call_count == 1
        assert result.status == "completed"
        assert result.verdict == "proceed"
        assert result.confidence_score == 0.8

    async def test_financial_fatal_error_marks_the_study_failed(
        self, db_session, make_project, monkeypatch
    ):
        from app.agents.financial import FinancialCalcError

        _patch_agent(monkeypatch, "MarketSizingAgent", _market_output())
        _patch_agent(monkeypatch, "CompetitiveAnalysisAgent", _competitive_output())
        mock_run = AsyncMock(side_effect=FinancialCalcError("boom"))
        monkeypatch.setattr("app.services.study.FinancialModelingAgent.run", mock_run)

        project = make_project()
        result = await study_module.run_single_phase_study(db_session, project, "financial", EventQueue())

        assert result.status == "failed"
        assert "boom" in result.error


def _market_output() -> MarketSizingOutput:
    from app.schemas.common import ClaimType
    from app.schemas.market import EstimatedMarketFigure
    from app.schemas.report import LocalizedText

    figure = EstimatedMarketFigure(
        value=None, currency="USD", unit="USD", confidence="low",
        citations=[], claim_type=ClaimType.UNAVAILABLE, methodology="n/a",
    )
    return MarketSizingOutput(
        study_id="s1", output_language="en", tam=figure, sam=figure, som=figure,
        narrative=LocalizedText(text="n/a", language="en"), key_insights=[],
        all_citations=[], search_queries_used=[],
    )


def _competitive_output() -> CompetitiveAnalysisOutput:
    from app.schemas.report import LocalizedText

    return CompetitiveAnalysisOutput(
        study_id="s1", output_language="en", competitors=[], key_differentiators=[],
        market_gaps=[], narrative=LocalizedText(text="n/a", language="en"),
        all_citations=[], search_queries_used=[],
    )


def _financial_output() -> FinancialModelOutput:
    from app.schemas.common import ClaimType
    from app.schemas.report import CalcTrace, CalculatedFigure, LocalizedText

    def figure(value: dict) -> CalculatedFigure:
        trace = CalcTrace(fn="calculate_break_even", inputs={}, output=value)
        return CalculatedFigure(
            value=value, input_confidence="high", calculation_trace=trace,
            claim_type=ClaimType.CALCULATED_ESTIMATE,
        )

    return FinancialModelOutput(
        study_id="s1", output_language="en",
        capex_value=1000.0, capex_currency="USD", capex_source="user_provided",
        opex_monthly_value=100.0, opex_monthly_currency="USD", opex_monthly_source="user_provided",
        unit_price=10.0, pricing_currency="USD",
        expected_monthly_sales=100.0, expected_monthly_sales_source="user_provided",
        analysis_horizon_years=3,
        break_even=figure({"break_even_months": 6, "break_even_units": 100}),
        roi_year_1=figure({"roi_percent": 10.0}),
        roi_year_n=figure({"roi_percent": 30.0}),
        npv=figure({"npv": 5000.0, "is_positive": True}),
        sensitivity=figure({"scenarios": []}),
        cash_flow=figure({"payback_month": 6, "final_position": 5000.0}),
        cost_structure=figure({"fixed": 100.0, "variable": 50.0}),
        narrative=LocalizedText(text="n/a", language="en"),
    )


def _risk_output() -> RiskAssessmentOutput:
    from app.schemas.report import LocalizedText

    return RiskAssessmentOutput(
        study_id="s1", output_language="en", risks=[], high_critical_count=0,
        narrative=LocalizedText(text="n/a", language="en"), search_queries_used=[], citations=[],
    )


def _synthesis_output() -> FeasibilitySynthesisOutput:
    from app.schemas.report import LocalizedText

    return FeasibilitySynthesisOutput(
        study_id="s1", output_language="en", verdict="proceed", confidence_score=0.8,
        confidence_breakdown={}, executive_summary=LocalizedText(text="n/a", language="en"),
        key_opportunities=[], key_risks=[], data_gaps=[], contradictions=[],
        rationale=LocalizedText(text="n/a", language="en"),
    )
