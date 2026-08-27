from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.agents.intake import IntakeHardBlockError
from app.db import get_db
from app.models import ChatMessage
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
from app.services.chat import create_chat_session, get_chat_session, list_chat_sessions
from app.services.chat_agent import run_chat_turn
from app.services.project import (
    business_profile_to_response,
    create_project_from_questionnaire,
    get_business_profile,
    get_project,
    list_projects,
    update_business_profile,
)
from app.sse import EventQueue, SSEEvent

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


@router.get("/{project_id}/study", response_model=StudyResultResponse)
def get_study_endpoint(project_id: str, db: Session = Depends(get_db)) -> StudyResultResponse:
    """Read-only. There is deliberately no public POST .../study/run route —
    per the plan, the feasibility pipeline is only triggered through the chat
    agent's run_feasibility_study tool (see chat/messages below), not as a
    standalone public flow."""
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.study_result is None:
        raise HTTPException(status_code=404, detail="No study result yet")
    return StudyResultResponse.model_validate(project.study_result)


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
    return list(session.messages)


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
    queue = EventQueue()

    async def _run() -> None:
        try:
            await run_chat_turn(db, project, session, payload.content, queue)
        except Exception as exc:
            logger.exception("Chat turn failed for project %s", project_id)
            # A mid-commit failure (e.g. a bad DB write) leaves the session in a
            # pending-rollback state — clear it before writing the error message,
            # or the write below would itself raise PendingRollbackError.
            db.rollback()
            error_text = f"Something went wrong handling that message: {exc}"
            message_id = None
            try:
                error_message = ChatMessage(role="assistant", content=error_text)
                session.messages.append(error_message)
                db.commit()
                message_id = error_message.id
            except Exception:
                logger.exception(
                    "Failed to persist chat error message for project %s", project_id
                )
                db.rollback()
            await queue.put(SSEEvent.CHAT_TOOL_ERROR, {"tool_name": "chat_turn", "error": str(exc)})
            await queue.put(
                SSEEvent.CHAT_MESSAGE_COMPLETED,
                {"message_id": message_id, "role": "assistant", "content": error_text},
            )
        finally:
            await queue.close()

    asyncio.create_task(_run())

    async def _generator():
        async for event in queue:
            yield event

    return EventSourceResponse(_generator())
