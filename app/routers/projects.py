from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.agents.intake import IntakeHardBlockError
from app.db import SessionLocal, get_db
from app.models import StudyResult
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse, ChatSessionResponse
from app.schemas.intake import FeasibilityStartRequest
from app.schemas.project import (
    BusinessProfileResponse,
    BusinessProfileUpdate,
    ProjectCreateResponse,
    ProjectDetail,
    ProjectSummary,
)
from app.schemas.study import StudyResultResponse
from app.services.chat import (
    create_chat_session,
    get_active_generation,
    get_chat_message,
    get_chat_session,
    list_chat_messages,
    list_chat_sessions,
)
from app.services.chat_agent import run_chat_turn
from app.services.project import (
    business_profile_to_response,
    create_project_from_questionnaire,
    get_business_profile,
    get_project,
    list_projects,
    update_business_profile,
)
from app.services.study import list_study_results
from app.sse import EventQueue, SSEEvent, make_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    request: FeasibilityStartRequest, db: Session = Depends(get_db)
) -> ProjectCreateResponse:
    try:
        project = await create_project_from_questionnaire(db, request)
    except IntakeHardBlockError as exc:
        raise HTTPException(
            status_code=422, detail={"field": exc.field, "reason": str(exc)}
        ) from exc
    return ProjectCreateResponse(project_id=project.id)


@router.get("", response_model=list[ProjectSummary])
def list_projects_endpoint(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    return list_projects(db)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_endpoint(project_id: str, db: Session = Depends(get_db)) -> ProjectDetail:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/business-profile", response_model=BusinessProfileResponse)
def get_business_profile_endpoint(
    project_id: str, db: Session = Depends(get_db)
) -> BusinessProfileResponse:
    profile = get_business_profile(db, project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Business profile not found")
    return business_profile_to_response(profile)


@router.patch("/{project_id}/business-profile", response_model=BusinessProfileResponse)
def update_business_profile_endpoint(
    project_id: str, patch: BusinessProfileUpdate, db: Session = Depends(get_db)
) -> BusinessProfileResponse:
    profile = get_business_profile(db, project_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Business profile not found")
    profile = update_business_profile(db, profile, patch)
    return business_profile_to_response(profile)


@router.get("/{project_id}/studies", response_model=list[StudyResultResponse])
def list_studies_endpoint(project_id: str, db: Session = Depends(get_db)) -> list[StudyResultResponse]:
    """Read-only. There is deliberately no public POST .../studies route —
    per the plan, the feasibility pipeline is only triggered through the chat
    agent's run_feasibility_study tool (see chat/messages below), not as a
    standalone public flow. Newest-first, via the relationship's order_by."""
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return [StudyResultResponse.model_validate(s) for s in list_study_results(db, project)]


@router.get("/{project_id}/studies/{study_id}", response_model=StudyResultResponse)
def get_study_by_id_endpoint(
    project_id: str, study_id: str, db: Session = Depends(get_db)
) -> StudyResultResponse:
    # Filtering by both id and project_id matters: without the project_id
    # filter, a valid study id from a different project would leak its data
    # through this project's URL.
    study = (
        db.query(StudyResult)
        .filter_by(id=study_id, project_id=project_id)
        .filter(StudyResult.deleted_at.is_(None))
        .one_or_none()
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return StudyResultResponse.model_validate(study)


@router.get("/{project_id}/chat/sessions", response_model=list[ChatSessionResponse])
def list_chat_sessions_endpoint(
    project_id: str, db: Session = Depends(get_db)
) -> list[ChatSessionResponse]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return list_chat_sessions(db, project)


@router.post("/{project_id}/chat/sessions", response_model=ChatSessionResponse, status_code=201)
def create_chat_session_endpoint(
    project_id: str, db: Session = Depends(get_db)
) -> ChatSessionResponse:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return create_chat_session(db, project)


@router.get(
    "/{project_id}/chat/sessions/{session_id}/messages",
    response_model=list[ChatMessageResponse],
)
def list_chat_messages_endpoint(
    project_id: str, session_id: str, db: Session = Depends(get_db)
) -> list[ChatMessageResponse]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return list_chat_messages(db, session)


@router.post("/{project_id}/chat/sessions/{session_id}/messages")
async def post_chat_message_endpoint(
    project_id: str, session_id: str, payload: ChatMessageCreate, db: Session = Depends(get_db)
) -> EventSourceResponse:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    active = get_active_generation(db, session)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A response is already being generated for this session.",
        )

    queue = EventQueue()

    # Runs detached from this request's lifecycle — it must NOT use the
    # request-scoped `db` above, whose `finally: db.close()` (see
    # app.db.get_db) fires as soon as this request's response cycle ends,
    # which happens early if the client disconnects (e.g. a page refresh).
    # Generation continues on its own DB session regardless; run_chat_turn
    # persists progress incrementally so a reconnecting client can resume it
    # via get_chat_message_endpoint / resume_chat_message_stream_endpoint.
    async def _run() -> None:
        task_db = SessionLocal()
        try:
            task_project = get_project(task_db, project_id)
            task_session = (
                get_chat_session(task_db, task_project, session_id) if task_project else None
            )
            if task_project is None or task_session is None:
                await queue.put(
                    SSEEvent.CHAT_TOOL_ERROR,
                    {"tool_name": "chat_turn", "error": "Project or chat session no longer exists."},
                )
                await queue.put(
                    SSEEvent.CHAT_MESSAGE_COMPLETED,
                    {
                        "message_id": None,
                        "role": "assistant",
                        "content": "Something went wrong handling that message.",
                    },
                )
                return
            await run_chat_turn(task_db, task_project, task_session, payload.content, queue)
        except Exception:
            # run_chat_turn persists its own errors onto the assistant row it
            # created — this is only a last-resort net for failures before
            # that row exists (e.g. the project/session lookups above).
            logger.exception("Chat turn failed for project %s", project_id)
        finally:
            await queue.close()
            task_db.close()

    asyncio.create_task(_run())

    async def _generator():
        async for event in queue:
            yield event

    return EventSourceResponse(_generator())


@router.get(
    "/{project_id}/chat/sessions/{session_id}/messages/{message_id}",
    response_model=ChatMessageResponse,
)
def get_chat_message_endpoint(
    project_id: str, session_id: str, message_id: str, db: Session = Depends(get_db)
) -> ChatMessageResponse:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    message = get_chat_message(db, session.id, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


# Ceiling on how long a client will poll a resumed generation before giving
# up — well past any real turn duration, and a backstop independent of the
# periodic sweep in app.main that reconciles rows orphaned by a server
# restart (see that sweep's docstring for why both exist).
_RESUME_STREAM_MAX_SECONDS = 600
_RESUME_STREAM_POLL_INTERVAL = 1.0


@router.get("/{project_id}/chat/sessions/{session_id}/messages/{message_id}/stream")
async def resume_chat_message_stream_endpoint(
    project_id: str, session_id: str, message_id: str, after: int = 0, db: Session = Depends(get_db)
) -> EventSourceResponse:
    """Lets a client that reconnected after a refresh catch up on (and keep
    watching) a generation that's still in flight on the backend. This is a
    DB-polling loop dressed as SSE, not a resumable pub/sub broadcaster — it
    re-emits the same chat_message_delta/chat_message_completed event shapes
    the POST endpoint emits, at ~1s granularity, so it works correctly
    regardless of which worker process is handling this request (state lives
    in Postgres, not the in-memory EventQueue the original generation used).

    `after` is the character count of content the client already has (e.g.
    from the message it just fetched via GET .../messages) — the first delta
    only carries what's beyond that, so a client that already rendered the
    partial content doesn't see it duplicated when the stream reconnects."""
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    message = get_chat_message(db, session.id, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    async def _generator():
        sent_len = max(0, after)
        current = message
        elapsed = 0.0
        while elapsed < _RESUME_STREAM_MAX_SECONDS:
            poll_db = SessionLocal()
            try:
                current = get_chat_message(poll_db, session_id, message_id)
            finally:
                poll_db.close()
            if current is None:
                break
            if len(current.content) > sent_len:
                delta = current.content[sent_len:]
                sent_len = len(current.content)
                yield make_event(SSEEvent.CHAT_MESSAGE_DELTA, {"content": delta})
            if current.status in ("complete", "error"):
                yield make_event(
                    SSEEvent.CHAT_MESSAGE_COMPLETED,
                    {"message_id": current.id, "role": "assistant", "content": current.content},
                )
                return
            await asyncio.sleep(_RESUME_STREAM_POLL_INTERVAL)
            elapsed += _RESUME_STREAM_POLL_INTERVAL
        yield make_event(
            SSEEvent.CHAT_MESSAGE_COMPLETED,
            {"message_id": message_id, "role": "assistant", "content": current.content if current else ""},
        )

    return EventSourceResponse(_generator())
