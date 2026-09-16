"""Public entry point for the feasibility pipeline — dispatches between the
legacy fixed-order implementation and the Deep Agent supervisor based on
`settings.deepagents_enabled`, while keeping this module's external contract
(the `run_feasibility_pipeline` signature, and `PipelineResult`'s shape)
completely stable so callers (app/services/study.py) and existing tests
(tests/test_study_history.py, which monkeypatches this exact function) never
need to change regardless of which implementation runs underneath."""

from __future__ import annotations

from langsmith import traceable

from app.config import get_settings
from app.orchestrator_agent import run_feasibility_pipeline_deep_agent
from app.orchestrator_legacy import PipelineResult, run_feasibility_pipeline_fixed_order
from app.schemas.intake import FeasibilityInput
from app.sse import EventQueue

__all__ = ["PipelineResult", "run_feasibility_pipeline"]


@traceable(name="Feasibility Pipeline", run_type="chain")
async def run_feasibility_pipeline(
    study_id: str,
    feasibility_input: FeasibilityInput,
    queue: EventQueue,
    glossary: dict[str, str] | None = None,
) -> PipelineResult:
    if get_settings().deepagents_enabled:
        return await run_feasibility_pipeline_deep_agent(study_id, feasibility_input, queue, glossary)
    return await run_feasibility_pipeline_fixed_order(study_id, feasibility_input, queue, glossary)
