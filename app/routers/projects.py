from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Artifact, StudyResult
from app.schemas.chat import ChatMessageCreate, ChatMessageResponse, ChatSessionResponse
from app.schemas.export import ChatExportRequest
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
from app.services.export import build_study_markdown, synthesize_chat_export
from app.services.project import (
    business_profile_to_response,
    create_bare_project,
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
def create_project(db: Session = Depends(get_db)) -> ProjectCreateResponse:
    """Creates a bare project with no business profile yet — chat gathers
    the profile conversationally afterward via bootstrap_profile_tool. There
    is no wizard/form-based creation path; this is the only entry point."""
    project = create_bare_project(db)
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


@router.get("/{project_id}/studies/{study_id}/export")
def export_study_markdown_endpoint(
    project_id: str, study_id: str, db: Session = Depends(get_db)
) -> PlainTextResponse:
    """Deterministic markdown export of one study — no LLM call, so this is
    a plain GET (same read-only semantics as get_study_by_id_endpoint)."""
    study = (
        db.query(StudyResult)
        .filter_by(id=study_id, project_id=project_id)
        .filter(StudyResult.deleted_at.is_(None))
        .one_or_none()
    )
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return PlainTextResponse(build_study_markdown([study]), media_type="text/markdown")


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


_ARTIFACT_MIME_BY_FORMAT = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_download_filename(title: str, fmt: str) -> str:
    slug = _UNSAFE_FILENAME_CHARS.sub("_", title).strip() or "artifact"
    return f"{slug}.{fmt}"


@router.get("/{project_id}/chat/artifacts/{artifact_id}/download")
def download_artifact_endpoint(
    project_id: str, artifact_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    """First binary-file endpoint in this codebase — every other file-serving
    route here returns markdown text. Filters by both project_id and
    artifact_id together (same IDOR-prevention pattern as
    get_study_by_id_endpoint) and always derives the on-disk path/filename
    from the Artifact row rather than any caller-supplied value."""
    artifact = (
        db.query(Artifact)
        .filter_by(id=artifact_id, project_id=project_id)
        .filter(Artifact.deleted_at.is_(None))
        .one_or_none()
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    download_name = _safe_download_filename(artifact.title, artifact.format)
    return FileResponse(
        artifact.storage_path,
        media_type=_ARTIFACT_MIME_BY_FORMAT[artifact.format],
        filename=download_name,
    )


@router.post("/{project_id}/chat/sessions/{session_id}/export")
async def export_chat_markdown_endpoint(
    project_id: str,
    session_id: str,
    payload: ChatExportRequest,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """One-shot LLM synthesis of the conversation into markdown — POST (not
    GET) since it takes a body and makes an LLM call, unlike the
    deterministic per-study export above."""
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    studies = None
    if payload.study_ids:
        studies = (
            db.query(StudyResult)
            .filter(StudyResult.id.in_(payload.study_ids), StudyResult.project_id == project_id)
            .filter(StudyResult.deleted_at.is_(None))
            .all()
        )

    settings = get_settings()
    markdown = await synthesize_chat_export(
        session, studies, google_api_key=settings.google_api_key, reasoning_model=settings.reasoning_model
    )
    return PlainTextResponse(markdown, media_type="text/markdown")


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
