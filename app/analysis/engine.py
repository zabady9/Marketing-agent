"""
The one analysis engine. Every analysis — a feasibility study, a SWOT, a
persona study, or a plain question like "can I compete with the big
players?" — runs through the same five phases:

  1. understand   choose the approach, title and key questions for the goal
  2. learn method search the web for how this kind of analysis is done
  3. plan         turn the method into concrete steps for this business
  4. execute      run the steps (independent ones in parallel); each step
                  researches, optionally calculates, and returns typed blocks
  5. synthesize   a direct answer, key findings and recommendations

The report (app.models.StudyResult.report) is saved after the plan and after
every step, so a run in progress can be viewed, and every streamed event
carries the run's study_id.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from langsmith import traceable
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from app.analysis import prompts
from app.analysis.llm import AnalysisLLM, is_transient
from app.analysis.research import Research, RunCounters
from app.analysis.steps import execute_step
from app.config import get_settings
from app.models import Project, StudyResult
from app.schemas.blocks import Citation
from app.sse import EventQueue, SSEEvent

logger = logging.getLogger(__name__)

# Shared by every run in this process: bounds how many steps (across all
# concurrent analyses) are executing at once. Created lazily for its size.
_step_semaphore: asyncio.Semaphore | None = None


def _get_step_semaphore() -> asyncio.Semaphore:
    global _step_semaphore
    if _step_semaphore is None:
        _step_semaphore = asyncio.Semaphore(max(1, get_settings().analysis_step_concurrency))
    return _step_semaphore


# ── LLM output schemas ────────────────────────────────────────────────────────

class _Approach(BaseModel):
    title: str
    rationale: str
    frameworks: list[str] = []
    key_questions: list[str]
    method_queries: list[str]


class _PlannedStep(BaseModel):
    id: str
    title: str
    objective: str
    research_queries: list[str] = []
    depends_on: list[str] = []
    needs_calculation: bool = False
    suggested_blocks: list[str] = []


class _Plan(BaseModel):
    steps: list[_PlannedStep]


class _Answer(BaseModel):
    headline: str
    body: str
    confidence: Literal["high", "medium", "low"] = "medium"


class _Synthesis(BaseModel):
    answer: _Answer
    findings: list[str]
    recommendations: list[str]


@dataclass
class AnalysisRun:
    """Plain values for the caller — the run used its own DB session."""

    study_id: str
    status: str
    title: str | None
    answer: str | None
    error: str | None


class AnalysisFailed(Exception):
    pass


# ── Plan helpers ──────────────────────────────────────────────────────────────

def _normalize_plan(steps: list[_PlannedStep], max_steps: int) -> list[dict]:
    """Unique ids; dependencies only on EARLIER steps (no cycles, no unknowns)."""
    out: list[dict] = []
    seen: set[str] = set()
    for i, s in enumerate(steps[:max_steps]):
        sid = s.id.strip() or f"s{i + 1}"
        if sid in seen:
            sid = f"{sid}_{i + 1}"
        out.append(
            {
                "id": sid,
                "title": s.title,
                "objective": s.objective,
                "research_queries": s.research_queries[:4],
                "depends_on": [d for d in s.depends_on if d in seen],
                "needs_calculation": s.needs_calculation,
                "suggested_blocks": s.suggested_blocks,
                "status": "pending",
                "summary": "",
                "blocks": [],
                "error": None,
            }
        )
        seen.add(sid)
    return out


def _reader_error(exc: Exception) -> str:
    """What the report shows for a failure — never a raw API payload."""
    if is_transient(exc):
        return "The AI model was temporarily overloaded. Run the analysis again to fill this in."
    if isinstance(exc, AnalysisFailed):
        return str(exc)
    return "Something went wrong while working on this part of the analysis."


def _step_sources(steps: list[dict], limit: int = 15) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for s in steps:
        for b in s.get("blocks", []):
            for c in b.get("citations", []):
                if c["url"] not in seen and len(out) < limit:
                    seen.add(c["url"])
                    out.append(c)
    return out


def _step_digest(step: dict, max_rows: int = 8) -> str:
    """What a later step (or the synthesis) sees of an earlier one: its summary
    plus the actual figures it produced — stats, table rows and chart data —
    so numbers carry forward instead of being re-guessed."""
    lines = [f"## {step['title']} ({step['status']})", step.get("summary", "")]
    for b in step.get("blocks", []):
        t, title = b.get("type"), b.get("title") or ""
        if t == "stats":
            lines += [
                f"- {i['label']}: {i['value']} {i.get('unit', '')} [{i.get('basis')}]".rstrip()
                for i in b.get("items", [])
            ]
        elif t == "table":
            lines.append(f"Table {title}: " + " | ".join(b.get("columns", [])))
            lines += ["  " + " | ".join(r) for r in b.get("rows", [])[:max_rows]]
        elif t == "chart":
            for s in b.get("series", []):
                pairs = ", ".join(f"{c}={v}" for c, v in zip(b.get("categories", []), s.get("data", [])))
                lines.append(f"Chart {title} / {s.get('name')}: {pairs} {b.get('unit', '')}".rstrip())
    return "\n".join(line for line in lines if line)


def _plan_overview(steps: list[dict]) -> str:
    return "\n".join(f"{i + 1}. [{s['id']}] {s['title']}: {s['objective']}" for i, s in enumerate(steps))


def _collect_sources(report: dict) -> list[dict]:
    seen: set[str] = set()
    sources: list[dict] = []
    for step in report.get("steps", []):
        for block in step.get("blocks", []):
            for c in block.get("citations", []):
                if c["url"] not in seen:
                    seen.add(c["url"])
                    sources.append(c)
    return sources


# ── The run ───────────────────────────────────────────────────────────────────

class _Run:
    def __init__(self, db: Session, study: StudyResult, queue: EventQueue, llm: AnalysisLLM) -> None:
        self.db = db
        self.study = study
        self.queue = queue
        self.llm = llm
        self.settings = get_settings()
        self.counters = RunCounters()
        self.report: dict = {}

    def save(self) -> None:
        # Re-assign a fresh dict so SQLAlchemy sees the JSON column change.
        # No await between mutation and commit, so concurrent step tasks of
        # this run never interleave inside one save.
        self.study.report = {**self.report, "steps": [dict(s) for s in self.report.get("steps", [])]}
        self.db.commit()

    async def emit(self, event: SSEEvent, data: dict) -> None:
        await self.queue.put(event, {"study_id": self.study.id, **data})

    def research(self) -> Research:
        return Research(self.settings.tavily_api_key, self.counters)


async def _understand(run: _Run, goal: str, analysis_name: str | None, business: str, language: str) -> _Approach:
    human = (
        f"User goal: {goal}\n"
        + (f"Requested analysis: {analysis_name}\n" if analysis_name else "")
        + f"\nBusiness profile:\n{business}"
    )
    return await run.llm.structured(
        _Approach, prompts.approach_system(language, analysis_name), human, cheap=True
    )


async def _plan(
    run: _Run, goal: str, approach: _Approach, method_text: str, business: str, language: str, max_steps: int
) -> list[dict]:
    human = (
        f"User goal: {goal}\nAnalysis: {approach.title}\n"
        f"Frameworks/methods: {', '.join(approach.frameworks) or 'custom'}\n"
        "Key questions:\n" + "\n".join(f"- {q}" for q in approach.key_questions)
        + f"\n\nBusiness profile:\n{business}\n\n"
        f"How this analysis is done (methodology sources):\n{method_text or '(none found — use best practice)'}"
    )
    plan = await run.llm.structured(_Plan, prompts.plan_system(language, max_steps), human)
    steps = _normalize_plan(plan.steps, max_steps)
    if not steps:
        raise AnalysisFailed("The plan came back with no steps.")
    return steps


async def _execute_all(run: _Run, goal: str, business: str, language: str) -> None:
    steps = run.report["steps"]
    by_id = {s["id"]: s for s in steps}
    done: dict[str, asyncio.Event] = {s["id"]: asyncio.Event() for s in steps}
    overview = _plan_overview(steps)

    async def _one(step: dict) -> None:
        try:
            for dep in step["depends_on"]:
                await done[dep].wait()
            deps_text = "\n\n".join(_step_digest(by_id[d]) for d in step["depends_on"])
            async with _get_step_semaphore():
                step["status"] = "running"
                run.save()
                await run.emit(SSEEvent.ANALYSIS_STEP_STARTED, {"step_id": step["id"], "title": step["title"]})
                try:
                    outcome = await execute_step(
                        run.llm,
                        run.research(),
                        step=step,
                        plan_overview=overview,
                        goal=goal,
                        business=business,
                        dependency_summaries=deps_text,
                        language=language,
                        tool_rounds=run.settings.analysis_step_tool_rounds,
                        inherited_sources=_step_sources([by_id[d] for d in step["depends_on"]]),
                    )
                    step["summary"] = outcome.summary
                    step["blocks"] = outcome.blocks
                    step["status"] = "completed" if outcome.blocks else "failed"
                    if not outcome.blocks:
                        step["error"] = "The step produced no content."
                except Exception as exc:
                    logger.warning("Analysis %s step %s failed: %s", run.study.id, step["id"], exc, exc_info=True)
                    step["status"] = "failed"
                    step["error"] = _reader_error(exc)
                run.save()
                await run.emit(
                    SSEEvent.ANALYSIS_STEP_COMPLETED,
                    {"step_id": step["id"], "title": step["title"], "status": step["status"]},
                )
        finally:
            done[step["id"]].set()

    await asyncio.gather(*(_one(s) for s in steps))


async def _synthesize(run: _Run, goal: str, business: str, language: str) -> _Synthesis:
    parts = [_step_digest(s) for s in run.report["steps"] if s["status"] == "completed"]
    human = (
        f"User goal: {goal}\nAnalysis: {run.report['title']}\n"
        "Key questions:\n" + "\n".join(f"- {q}" for q in run.report["key_questions"])
        + f"\n\nBusiness profile:\n{business}\n\nStep results:\n" + "\n\n".join(parts)
    )
    return await run.llm.structured(_Synthesis, prompts.synthesis_system(language), human)


@traceable(name="Analysis", run_type="chain")
async def run_analysis(
    db: Session,
    project_id: str,
    goal: str,
    analysis_name: str | None = None,
    queue: EventQueue | None = None,
    *,
    comprehensive: bool = False,
    llm: AnalysisLLM | None = None,
    on_started: Callable[[str], None] | None = None,
) -> AnalysisRun:
    """Runs one analysis and persists it as a StudyResult row.

    Opens its OWN session on `db`'s engine: the chat agent may run several
    analyses as parallel tool calls in one turn, and interleaving commits on
    one shared synchronous Session is unsafe. Never raises for an analysis
    failure — the row is marked failed and the caller gets status="failed".

    `on_started(study_id)` is called once the row exists, before any slow
    work — the chat uses it to link the run to the conversation right away."""
    queue = queue or EventQueue()
    llm = llm or AnalysisLLM()
    settings = get_settings()
    run_db = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)()
    started = time.monotonic()
    try:
        project = run_db.get(Project, project_id)
        if project is None or project.business_profile is None:
            raise ValueError(f"Project {project_id} has no business profile.")
        profile = project.business_profile
        language = profile.output_language or "en"
        business = prompts.business_context(profile)
        max_steps = (
            settings.analysis_max_steps_comprehensive if comprehensive else settings.analysis_max_steps
        )

        study = StudyResult(
            project_id=project_id, goal=goal, status="running",
            started_at=datetime.utcnow(), report={"language": language, "goal": goal, "steps": []},
        )
        run_db.add(study)
        run_db.commit()
        run = _Run(run_db, study, queue, llm)
        run.report = dict(study.report)
        if on_started is not None:
            on_started(study.id)
        await run.emit(SSEEvent.STUDY_STARTED, {"goal": goal})

        try:
            approach = await _understand(run, goal, analysis_name, business, language)
            method_research = run.research()
            method_results = await method_research.search(approach.method_queries[:4])
            steps = await _plan(
                run, goal, approach, method_research.format(method_results, with_raw=True),
                business, language, max_steps,
            )
            run.report.update(
                title=approach.title,
                rationale=approach.rationale,
                frameworks=approach.frameworks,
                key_questions=approach.key_questions,
                method_sources=[
                    Citation(url=r.url, title=r.title, snippet=r.snippet[:300]).model_dump()
                    for _, r in method_results
                ],
                steps=steps,
            )
            study.title = approach.title[:160]
            run.save()
            await run.emit(
                SSEEvent.ANALYSIS_PLAN_READY,
                {"title": approach.title, "steps": [{"id": s["id"], "title": s["title"]} for s in steps]},
            )

            await _execute_all(run, goal, business, language)
            completed = [s for s in run.report["steps"] if s["status"] == "completed"]
            if not completed:
                raise AnalysisFailed("Every step of the analysis failed.")

            synthesis = await _synthesize(run, goal, business, language)
            run.report.update(
                answer=synthesis.answer.model_dump(),
                findings=synthesis.findings,
                recommendations=synthesis.recommendations,
            )
            study.status = "completed"
        except Exception as exc:
            logger.warning("Analysis %s failed: %s", study.id, exc, exc_info=True)
            study.status = "failed"
            study.error = _reader_error(exc)

        run.report["sources"] = _collect_sources(run.report)
        study.completed_at = datetime.utcnow()
        run.save()
        logger.info(
            "analysis %s (%s): %d steps, %d searches, %d LLM calls, %.1fs",
            study.id, study.status, len(run.report.get("steps", [])), run.counters.searches,
            llm.calls, time.monotonic() - started,
        )
        await run.emit(SSEEvent.STUDY_COMPLETED, {"status": study.status, "title": study.title})
        answer = (run.report.get("answer") or {}).get("headline")
        return AnalysisRun(
            study_id=study.id, status=study.status, title=study.title, answer=answer, error=study.error
        )
    finally:
        run_db.close()
