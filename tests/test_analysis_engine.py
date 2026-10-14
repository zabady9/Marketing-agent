"""
The one analysis engine (app/analysis/engine.py) with a fake LLM and fake
search: method research happens before planning, steps follow depends_on
(independent ones overlap), calculator figures are kept as "calculated",
failures are contained, the report is saved as it goes, every event carries
study_id, and concurrent runs don't share a DB session.
"""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

from app.analysis import engine as engine_module
from app.analysis.engine import _Answer, _Approach, _Plan, _PlannedStep, _Synthesis, run_analysis
from app.models import StudyResult
from app.sse import EventQueue, SSEEvent
from app.tools.web_search import SearchResult

STEPS = [
    _PlannedStep(id="s1", title="Market", objective="size it", research_queries=["market q"]),
    _PlannedStep(id="s2", title="Competitors", objective="map them", research_queries=["competitor q"]),
    _PlannedStep(id="s3", title="Economics", objective="unit economics", depends_on=["s1", "s2"],
                 needs_calculation=True),
    # Dependency on a LATER/unknown step is dropped (no cycles possible).
    _PlannedStep(id="s4", title="Conclusion", objective="pull together", depends_on=["s3", "s9"]),
]


class FakeLLM:
    def __init__(self, *, fail_step: str | None = None, step_delay: float = 0.02) -> None:
        self.calls = 0
        self.log: list[str] = []
        self.fail_step = fail_step
        self.step_delay = step_delay
        self.running = 0
        self.max_running = 0
        self._tool_rounds = 0

    async def structured(self, schema, system, human, *, cheap=False):
        self.calls += 1
        self.log.append(schema.__name__)
        if schema is _Approach:
            return _Approach(title="Can you compete?", rationale="Forces decide it.",
                             frameworks=["Porter's Five Forces"], key_questions=["Can I compete?"],
                             method_queries=["how to do porter five forces"])
        if schema is _Plan:
            assert "METHOD-SOURCE" in human  # method research reached the planner
            return _Plan(steps=STEPS)
        if schema is _Synthesis:
            return _Synthesis(answer=_Answer(headline="Yes, in a niche", body="...", confidence="medium"),
                              findings=["f1"], recommendations=["r1"])
        raise AssertionError(schema)

    async def json(self, system, human, *, cheap=False):
        self.calls += 1
        title = human.split("THIS STEP: ", 1)[1].split("\n", 1)[0]
        self.log.append(f"step:{title}")
        self.step_inputs = getattr(self, "step_inputs", {})
        self.step_inputs[title] = human
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        await asyncio.sleep(self.step_delay)
        self.running -= 1
        if title == self.fail_step:
            raise RuntimeError("model exploded")
        return {
            "summary": f"{title} summary",
            "blocks": [
                {"type": "stats", "citation_indices": [0],
                 "items": [{"label": "Break-even", "value": "8", "unit": "months", "basis": "calculated"},
                           {"label": "Market", "value": "5M", "basis": "sourced"}]},
                {"type": "chart", "chart_type": "combo", "categories": ["a", "b"],
                 "series": [{"name": "s", "data": [1, 2, 3]}]},
            ],
        }

    async def tool_round(self, messages, tools):
        self.calls += 1
        self._tool_rounds += 1
        if self._tool_rounds == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "calculate_break_even", "id": "t1",
                "args": {"fixed_costs": 1000, "unit_price": 10, "monthly_unit_sales": 50},
            }])
        return AIMessage(content="Used capex 1000, price 10, 50 units/month.")


@pytest.fixture
def fake_search(monkeypatch):
    queries: list[str] = []

    async def _search(query, api_key, max_results=5, include_raw_content=False, **_):
        queries.append(query)
        title = "METHOD-SOURCE" if "how to" in query else "data"
        return [SearchResult(url=f"https://ex.com/{len(queries)}", title=title, snippet="s", raw_content="raw")]

    monkeypatch.setattr("app.tools.web_search.search", _search)
    return queries


async def _drain(queue: EventQueue) -> list[tuple[str, dict]]:
    await queue.close()
    return [(e.event, json.loads(e.data)) async for e in queue]


def _row(db_session, study_id) -> StudyResult:
    db_session.expire_all()
    return db_session.get(StudyResult, study_id)


class TestRunAnalysis:
    async def test_overloaded_model_errors_are_shown_as_a_readable_message(
        self, db_session, make_project, fake_search
    ):
        class _Overloaded(FakeLLM):
            async def json(self, system, human, *, cheap=False):
                raise RuntimeError("503 UNAVAILABLE {'error': {'code': 503}}")

        project = make_project()
        run = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=_Overloaded())

        steps = _row(db_session, run.study_id).report["steps"]
        assert all("temporarily overloaded" in s["error"] for s in steps)
        assert "{" not in run.error

    async def test_full_run_produces_a_saved_step_report(self, db_session, make_project, fake_search):
        llm = FakeLLM()
        queue = EventQueue()
        project = make_project()

        run = await run_analysis(db_session, project.id, "Can I compete?", None, queue, llm=llm)

        assert run.status == "completed"
        assert run.answer == "Yes, in a niche"
        # Method search before the plan; the plan before any step.
        assert fake_search[0] == "how to do porter five forces"
        assert llm.log[:2] == ["_Approach", "_Plan"]
        assert llm.log[-1] == "_Synthesis"

        row = _row(db_session, run.study_id)
        assert row.status == "completed"
        assert row.title == "Can you compete?"
        assert row.goal == "Can I compete?"
        report = row.report
        assert [s["id"] for s in report["steps"]] == ["s1", "s2", "s3", "s4"]
        assert report["steps"][3]["depends_on"] == ["s3"]
        assert all(s["status"] == "completed" for s in report["steps"])
        assert report["answer"]["headline"] == "Yes, in a niche"
        assert report["method_sources"][0]["title"] == "METHOD-SOURCE"
        assert report["sources"], "citations are collected into report.sources"

    async def test_calculated_basis_survives_only_where_the_calculator_ran(
        self, db_session, make_project, fake_search
    ):
        project = make_project()
        run = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=FakeLLM())

        steps = {s["id"]: s for s in _row(db_session, run.study_id).report["steps"]}
        calc_items = steps["s3"]["blocks"][0]["items"]
        plain_items = steps["s1"]["blocks"][0]["items"]
        assert calc_items[0]["basis"] == "calculated"
        assert plain_items[0]["basis"] == "estimate"  # claimed calculated, no calculator ran
        assert plain_items[1]["basis"] == "sourced"   # block has a resolved citation
        # The repaired chart: unknown type -> bar, series trimmed to categories.
        chart = steps["s1"]["blocks"][1]
        assert chart["chart_type"] == "bar"
        assert chart["series"][0]["data"] == [1, 2]

    async def test_dependent_steps_receive_earlier_figures_not_just_summaries(
        self, db_session, make_project, fake_search
    ):
        llm = FakeLLM()
        project = make_project()
        await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=llm)

        economics_input = llm.step_inputs["Economics"]
        # s3 depends on s1/s2: it sees their summaries AND their actual figures.
        assert "Market summary" in economics_input
        assert "- Market: 5M  [sourced]" in economics_input or "- Market: 5M [sourced]" in economics_input
        assert "Chart " in economics_input
        # ...and the sources behind those figures, so it can cite them.
        assert "Sources behind the earlier steps' figures" in economics_input
        assert "https://ex.com/" in economics_input.split("Sources behind", 1)[1]
        # An independent step does not get unrelated earlier results.
        assert "Market summary" not in llm.step_inputs["Competitors"]

    async def test_independent_steps_overlap_and_dependents_wait(self, db_session, make_project, fake_search):
        llm = FakeLLM()
        project = make_project()
        await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=llm)

        order = [x for x in llm.log if x.startswith("step:")]
        assert llm.max_running == 2  # s1 and s2 together
        assert order.index("step:Economics") > max(order.index("step:Market"), order.index("step:Competitors"))
        assert order[-1] == "step:Conclusion"

    async def test_a_failed_step_is_marked_and_the_report_still_completes(
        self, db_session, make_project, fake_search
    ):
        project = make_project()
        run = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=FakeLLM(fail_step="Competitors"))

        assert run.status == "completed"
        steps = {s["id"]: s for s in _row(db_session, run.study_id).report["steps"]}
        assert steps["s2"]["status"] == "failed"
        assert steps["s2"]["error"] == "Something went wrong while working on this part of the analysis."
        assert steps["s3"]["status"] == "completed"  # its dependent still ran

    async def test_planning_failure_marks_the_run_failed_without_raising(
        self, db_session, make_project, fake_search
    ):
        class _BrokenPlanner(FakeLLM):
            async def structured(self, schema, system, human, *, cheap=False):
                if schema is _Plan:
                    raise RuntimeError("no plan")
                return await super().structured(schema, system, human, cheap=cheap)

        project = make_project()
        run = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=_BrokenPlanner())

        assert run.status == "failed"
        assert "503" not in run.error and run.error
        assert _row(db_session, run.study_id).status == "failed"

    async def test_every_event_carries_the_study_id(self, db_session, make_project, fake_search):
        queue = EventQueue()
        project = make_project()
        run = await run_analysis(db_session, project.id, "g", None, queue, llm=FakeLLM())

        events = await _drain(queue)
        names = [e for e, _ in events]
        assert names[0] == SSEEvent.STUDY_STARTED
        assert SSEEvent.ANALYSIS_PLAN_READY in names
        assert names.count(SSEEvent.ANALYSIS_STEP_COMPLETED) == 4
        assert names[-1] == SSEEvent.STUDY_COMPLETED
        assert all(d["study_id"] == run.study_id for _, d in events)

    async def test_report_is_saved_while_steps_run(self, db_session, make_project, fake_search, monkeypatch):
        snapshots: list[list[str]] = []
        original_save = engine_module._Run.save

        def _spy(self):
            original_save(self)
            snapshots.append([s["status"] for s in self.report.get("steps", [])])

        monkeypatch.setattr(engine_module._Run, "save", _spy)
        project = make_project()
        await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=FakeLLM())

        assert ["pending"] * 4 in snapshots              # right after planning
        assert any("running" in s for s in snapshots)    # mid-run
        assert snapshots[-1] == ["completed"] * 4

    async def test_two_concurrent_runs_use_separate_sessions(self, db_session, make_project, fake_search):
        project = make_project()
        a, b = await asyncio.gather(
            run_analysis(db_session, project.id, "goal A", None, EventQueue(), llm=FakeLLM()),
            run_analysis(db_session, project.id, "goal B", None, EventQueue(), llm=FakeLLM()),
        )

        assert a.study_id != b.study_id
        assert _row(db_session, a.study_id).goal == "goal A"
        assert _row(db_session, b.study_id).goal == "goal B"
        assert _row(db_session, a.study_id).status == _row(db_session, b.study_id).status == "completed"

    async def test_comprehensive_allows_a_longer_plan(self, db_session, make_project, fake_search):
        many = [_PlannedStep(id=f"s{i}", title=f"T{i}", objective="o") for i in range(1, 21)]

        class _BigPlanner(FakeLLM):
            async def structured(self, schema, system, human, *, cheap=False):
                if schema is _Plan:
                    self.calls += 1
                    return _Plan(steps=many)
                return await super().structured(schema, system, human, cheap=cheap)

        project = make_project()
        normal = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=_BigPlanner(step_delay=0))
        full = await run_analysis(db_session, project.id, "g", None, EventQueue(), llm=_BigPlanner(step_delay=0),
                                  comprehensive=True)

        assert len(_row(db_session, normal.study_id).report["steps"]) == 12
        assert len(_row(db_session, full.study_id).report["steps"]) == 16
