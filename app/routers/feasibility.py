from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.orchestrator import get_study_queue, register_study, run_study, study_exists
from app.schemas.intake import FeasibilityStartRequest, FeasibilityStartResponse, StudyStatus

router = APIRouter(prefix="/feasibility", tags=["feasibility"])


@router.post("/start", response_model=FeasibilityStartResponse, status_code=202)
async def start_study(request: FeasibilityStartRequest) -> FeasibilityStartResponse:
    study_id = str(uuid.uuid4())
    # Register the queue *before* spawning the task — eliminates the GET race condition.
    queue = register_study(study_id)
    asyncio.create_task(run_study(study_id, request, queue))
    return FeasibilityStartResponse(study_id=study_id, status=StudyStatus.PENDING)


@router.get("/{study_id}/stream")
async def stream_study(study_id: str) -> EventSourceResponse:
    if not study_exists(study_id):
        raise HTTPException(status_code=404, detail=f"Study '{study_id}' not found.")

    queue = get_study_queue(study_id)

    async def _generator():
        async for event in queue:
            # sse-starlette 3.x accepts ServerSentEvent objects directly
            yield event

    return EventSourceResponse(_generator())
