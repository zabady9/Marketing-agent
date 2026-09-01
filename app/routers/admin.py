from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import BusinessProfile
from app.schemas.admin import (
    ChatMessageAdminUpdate,
    ChatSessionAdminUpdate,
    GlossaryCacheAdminUpdate,
    GlossaryCacheResponse,
    MemoryEntryAdminUpdate,
    Page,
    ProjectAdminResponse,
    ProjectAdminUpdate,
    StudyResultAdminCreate,
    StudyResultAdminUpdate,
)
from app.schemas.chat import ChatMessageResponse, ChatSessionResponse
from app.schemas.memory import MemoryEntryResponse
from app.schemas.project import BusinessProfileResponse, BusinessProfileUpdate
from app.schemas.study import StudyResultResponse
from app.services.chat import (
    get_chat_message_admin,
    get_chat_session_admin,
    list_chat_messages_admin,
    list_chat_sessions_admin,
    restore_chat_message,
    restore_chat_session,
    soft_delete_chat_message,
    soft_delete_chat_session,
    update_chat_message,
    update_chat_session_title,
)
from app.services.glossary import (
    get_glossary_cache_admin,
    list_glossary_cache_admin,
    restore_glossary_cache,
    soft_delete_glossary_cache,
    update_glossary_terms,
)
from app.services.memory import (
    get_memory_entry_admin,
    list_memory_entries_admin,
    restore_memory_entry,
    soft_delete_memory_entry,
    update_memory_entry,
)
from app.services.project import (
    business_profile_to_response,
    get_project_admin,
    list_projects_admin,
    project_to_admin_response,
    restore_project,
    soft_delete_project,
    update_business_profile,
    update_project,
)
from app.services.study import (
    create_study_result_admin,
    get_study_result_admin,
    list_study_results_admin,
    restore_study_result,
    soft_delete_study_result,
    update_study_result,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_Limit = Query(default=50, ge=1, le=200)
_Offset = Query(default=0, ge=0)


# ── Projects ─────────────────────────────────────────────────────────────


@router.get("/projects", response_model=Page[ProjectAdminResponse])
def list_projects_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> Page[ProjectAdminResponse]:
    items, total = list_projects_admin(
        db, limit=limit, offset=offset, include_deleted=include_deleted, status=status
    )
    return Page(
        items=[project_to_admin_response(p) for p in items], total=total, limit=limit, offset=offset
    )


@router.get("/projects/{project_id}", response_model=ProjectAdminResponse)
def get_project_endpoint(project_id: str, db: Session = Depends(get_db)) -> ProjectAdminResponse:
    project = get_project_admin(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_to_admin_response(project)


@router.patch("/projects/{project_id}", response_model=ProjectAdminResponse)
def update_project_endpoint(
    project_id: str, patch: ProjectAdminUpdate, db: Session = Depends(get_db)
) -> ProjectAdminResponse:
    project = get_project_admin(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = update_project(db, project, patch)
    return project_to_admin_response(project)


@router.delete("/projects/{project_id}", response_model=ProjectAdminResponse)
def delete_project_endpoint(project_id: str, db: Session = Depends(get_db)) -> ProjectAdminResponse:
    project = get_project_admin(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = soft_delete_project(db, project)
    return project_to_admin_response(project)


@router.post("/projects/{project_id}/restore", response_model=ProjectAdminResponse)
def restore_project_endpoint(project_id: str, db: Session = Depends(get_db)) -> ProjectAdminResponse:
    project = get_project_admin(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = restore_project(db, project)
    return project_to_admin_response(project)


# ── BusinessProfile (nested under Project) ──────────────────────────────


@router.get(
    "/projects/{project_id}/business-profile", response_model=BusinessProfileResponse
)
def get_business_profile_endpoint(
    project_id: str, db: Session = Depends(get_db)
) -> BusinessProfileResponse:
    profile = db.query(BusinessProfile).filter_by(project_id=project_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Business profile not found")
    return business_profile_to_response(profile)


@router.patch(
    "/projects/{project_id}/business-profile", response_model=BusinessProfileResponse
)
def update_business_profile_endpoint(
    project_id: str, patch: BusinessProfileUpdate, db: Session = Depends(get_db)
) -> BusinessProfileResponse:
    profile = db.query(BusinessProfile).filter_by(project_id=project_id).one_or_none()
    if profile is None:
        raise HTTPException(status_code=404, detail="Business profile not found")
    profile = update_business_profile(db, profile, patch)
    return business_profile_to_response(profile)


# ── StudyResult ──────────────────────────────────────────────────────────


@router.get("/studies", response_model=Page[StudyResultResponse])
def list_studies_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    project_id: str | None = None,
    status: str | None = None,
    verdict: str | None = None,
    db: Session = Depends(get_db),
) -> Page[StudyResultResponse]:
    items, total = list_study_results_admin(
        db,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        project_id=project_id,
        status=status,
        verdict=verdict,
    )
    return Page(
        items=[StudyResultResponse.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/studies/{study_id}", response_model=StudyResultResponse)
def get_study_endpoint(study_id: str, db: Session = Depends(get_db)) -> StudyResultResponse:
    study = get_study_result_admin(db, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


@router.post("/studies", response_model=StudyResultResponse, status_code=201)
def create_study_endpoint(
    payload: StudyResultAdminCreate, db: Session = Depends(get_db)
) -> StudyResultResponse:
    return create_study_result_admin(db, payload)


@router.patch("/studies/{study_id}", response_model=StudyResultResponse)
def update_study_endpoint(
    study_id: str, patch: StudyResultAdminUpdate, db: Session = Depends(get_db)
) -> StudyResultResponse:
    study = get_study_result_admin(db, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return update_study_result(db, study, patch)


@router.delete("/studies/{study_id}", response_model=StudyResultResponse)
def delete_study_endpoint(study_id: str, db: Session = Depends(get_db)) -> StudyResultResponse:
    study = get_study_result_admin(db, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return soft_delete_study_result(db, study)


@router.post("/studies/{study_id}/restore", response_model=StudyResultResponse)
def restore_study_endpoint(study_id: str, db: Session = Depends(get_db)) -> StudyResultResponse:
    study = get_study_result_admin(db, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    return restore_study_result(db, study)


# ── ChatSession ──────────────────────────────────────────────────────────


@router.get("/chat-sessions", response_model=Page[ChatSessionResponse])
def list_chat_sessions_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    project_id: str | None = None,
    db: Session = Depends(get_db),
) -> Page[ChatSessionResponse]:
    items, total = list_chat_sessions_admin(
        db, limit=limit, offset=offset, include_deleted=include_deleted, project_id=project_id
    )
    return Page(
        items=[ChatSessionResponse.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/chat-sessions/{session_id}", response_model=ChatSessionResponse)
def get_chat_session_endpoint(session_id: str, db: Session = Depends(get_db)) -> ChatSessionResponse:
    session = get_chat_session_admin(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.patch("/chat-sessions/{session_id}", response_model=ChatSessionResponse)
def update_chat_session_endpoint(
    session_id: str, patch: ChatSessionAdminUpdate, db: Session = Depends(get_db)
) -> ChatSessionResponse:
    session = get_chat_session_admin(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return update_chat_session_title(db, session, patch)


@router.delete("/chat-sessions/{session_id}", response_model=ChatSessionResponse)
def delete_chat_session_endpoint(
    session_id: str, db: Session = Depends(get_db)
) -> ChatSessionResponse:
    session = get_chat_session_admin(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return soft_delete_chat_session(db, session)


@router.post("/chat-sessions/{session_id}/restore", response_model=ChatSessionResponse)
def restore_chat_session_endpoint(
    session_id: str, db: Session = Depends(get_db)
) -> ChatSessionResponse:
    session = get_chat_session_admin(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return restore_chat_session(db, session)


# ── ChatMessage ──────────────────────────────────────────────────────────


@router.get("/chat-messages", response_model=Page[ChatMessageResponse])
def list_chat_messages_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    session_id: str | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
) -> Page[ChatMessageResponse]:
    items, total = list_chat_messages_admin(
        db,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        session_id=session_id,
        role=role,
    )
    return Page(
        items=[ChatMessageResponse.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/chat-messages/{message_id}", response_model=ChatMessageResponse)
def get_chat_message_endpoint(message_id: str, db: Session = Depends(get_db)) -> ChatMessageResponse:
    message = get_chat_message_admin(db, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    return message


@router.patch("/chat-messages/{message_id}", response_model=ChatMessageResponse)
def update_chat_message_endpoint(
    message_id: str, patch: ChatMessageAdminUpdate, db: Session = Depends(get_db)
) -> ChatMessageResponse:
    message = get_chat_message_admin(db, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    return update_chat_message(db, message, patch)


@router.delete("/chat-messages/{message_id}", response_model=ChatMessageResponse)
def delete_chat_message_endpoint(
    message_id: str, db: Session = Depends(get_db)
) -> ChatMessageResponse:
    message = get_chat_message_admin(db, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    return soft_delete_chat_message(db, message)


@router.post("/chat-messages/{message_id}/restore", response_model=ChatMessageResponse)
def restore_chat_message_endpoint(
    message_id: str, db: Session = Depends(get_db)
) -> ChatMessageResponse:
    message = get_chat_message_admin(db, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Chat message not found")
    return restore_chat_message(db, message)


# ── MemoryEntry ──────────────────────────────────────────────────────────


@router.get("/memory", response_model=Page[MemoryEntryResponse])
def list_memory_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
) -> Page[MemoryEntryResponse]:
    items, total = list_memory_entries_admin(
        db, limit=limit, offset=offset, include_deleted=include_deleted
    )
    return Page(
        items=[MemoryEntryResponse.model_validate(m) for m in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/memory/{memory_id}", response_model=MemoryEntryResponse)
def get_memory_endpoint(memory_id: str, db: Session = Depends(get_db)) -> MemoryEntryResponse:
    entry = get_memory_entry_admin(db, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return entry


@router.patch("/memory/{memory_id}", response_model=MemoryEntryResponse)
def update_memory_endpoint(
    memory_id: str, patch: MemoryEntryAdminUpdate, db: Session = Depends(get_db)
) -> MemoryEntryResponse:
    entry = get_memory_entry_admin(db, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return update_memory_entry(db, entry, patch)


@router.delete("/memory/{memory_id}", response_model=MemoryEntryResponse)
def delete_memory_endpoint(memory_id: str, db: Session = Depends(get_db)) -> MemoryEntryResponse:
    entry = get_memory_entry_admin(db, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return soft_delete_memory_entry(db, entry)


@router.post("/memory/{memory_id}/restore", response_model=MemoryEntryResponse)
def restore_memory_endpoint(memory_id: str, db: Session = Depends(get_db)) -> MemoryEntryResponse:
    entry = get_memory_entry_admin(db, memory_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return restore_memory_entry(db, entry)


# ── GlossaryCache ────────────────────────────────────────────────────────


@router.get("/glossary", response_model=Page[GlossaryCacheResponse])
def list_glossary_endpoint(
    limit: int = _Limit,
    offset: int = _Offset,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
) -> Page[GlossaryCacheResponse]:
    items, total = list_glossary_cache_admin(
        db, limit=limit, offset=offset, include_deleted=include_deleted
    )
    return Page(
        items=[GlossaryCacheResponse.model_validate(g) for g in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/glossary/{language}", response_model=GlossaryCacheResponse)
def get_glossary_endpoint(language: str, db: Session = Depends(get_db)) -> GlossaryCacheResponse:
    cache = get_glossary_cache_admin(db, language)
    if cache is None:
        raise HTTPException(status_code=404, detail="Glossary cache entry not found")
    return cache


@router.patch("/glossary/{language}", response_model=GlossaryCacheResponse)
def update_glossary_endpoint(
    language: str, patch: GlossaryCacheAdminUpdate, db: Session = Depends(get_db)
) -> GlossaryCacheResponse:
    cache = get_glossary_cache_admin(db, language)
    if cache is None:
        raise HTTPException(status_code=404, detail="Glossary cache entry not found")
    return update_glossary_terms(db, cache, patch)


@router.delete("/glossary/{language}", response_model=GlossaryCacheResponse)
def delete_glossary_endpoint(language: str, db: Session = Depends(get_db)) -> GlossaryCacheResponse:
    cache = get_glossary_cache_admin(db, language)
    if cache is None:
        raise HTTPException(status_code=404, detail="Glossary cache entry not found")
    return soft_delete_glossary_cache(db, cache)


@router.post("/glossary/{language}/restore", response_model=GlossaryCacheResponse)
def restore_glossary_endpoint(language: str, db: Session = Depends(get_db)) -> GlossaryCacheResponse:
    cache = get_glossary_cache_admin(db, language)
    if cache is None:
        raise HTTPException(status_code=404, detail="Glossary cache entry not found")
    return restore_glossary_cache(db, cache)
