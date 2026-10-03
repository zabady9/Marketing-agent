"""Chat attachment upload lifecycle: create (returns where to PUT the bytes),
upload (direct to GCS in production; through PUT .../content locally),
complete (verifies the upload and starts processing), poll, delete.

Every lookup filters by project_id *and* session_id together, the same
IDOR-prevention pattern as download_artifact_endpoint."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import ChatAttachment
from app.schemas.attachment import AttachmentCreate, AttachmentCreateResponse, AttachmentSummary
from app.services import upload_storage
from app.services.attachment_processing import process_attachment
from app.services.chat import get_chat_session
from app.services.project import get_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["attachments"])

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_LOCAL_WRITE_CHUNK = 1024 * 1024


def safe_filename(name: str) -> str:
    """Strips any directory part and filesystem-unsafe characters, keeping
    the extension (processing sniffs the type from it)."""
    base = Path(name.replace("\\", "/")).name
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip().lstrip(".")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > 200:
        stem, ext = os.path.splitext(cleaned)
        cleaned = stem[: 200 - len(ext[:20])] + ext[:20]
    return cleaned


def _require_session(db: Session, project_id: str, session_id: str):
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    session = get_chat_session(db, project, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return project, session


def _get_attachment(db: Session, project_id: str, session_id: str, attachment_id: str) -> ChatAttachment:
    attachment = (
        db.query(ChatAttachment)
        .filter_by(id=attachment_id, project_id=project_id, session_id=session_id)
        .filter(ChatAttachment.deleted_at.is_(None))
        .one_or_none()
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


async def _process_in_background(attachment_id: str) -> None:
    """Runs detached from the request, on its own DB session, for the same
    reason as post_chat_message_endpoint's _run: the request-scoped session
    closes as soon as the response is sent."""
    db = SessionLocal()
    try:
        attachment = db.query(ChatAttachment).filter_by(id=attachment_id).one_or_none()
        if attachment is not None:
            await process_attachment(db, attachment)
    except Exception:
        logger.exception("Background processing for attachment %s failed", attachment_id)
    finally:
        db.close()


def start_processing(attachment_id: str) -> None:
    """Separate from _process_in_background so tests can replace it with an
    inline call on their own DB session."""
    asyncio.create_task(_process_in_background(attachment_id))


@router.post(
    "/{project_id}/chat/sessions/{session_id}/attachments",
    response_model=AttachmentCreateResponse,
    status_code=201,
)
def create_attachment_endpoint(
    project_id: str,
    session_id: str,
    payload: AttachmentCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> AttachmentCreateResponse:
    settings = get_settings()
    _require_session(db, project_id, session_id)
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large (limit {settings.max_upload_bytes // (1024**2):,} MB).",
        )

    attachment_id = str(uuid.uuid4())
    filename = safe_filename(payload.filename)
    content_type = payload.content_type or "application/octet-stream"
    attachment = ChatAttachment(
        id=attachment_id,
        project_id=project_id,
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        size_bytes=payload.size_bytes,
        storage_path=upload_storage.object_path(project_id, attachment_id, filename),
        status="pending_upload",
    )
    db.add(attachment)
    db.commit()

    local_url = str(
        request.url_for(
            "upload_attachment_content_endpoint",
            project_id=project_id, session_id=session_id, attachment_id=attachment_id,
        )
    )
    target = upload_storage.create_upload_target(attachment.storage_path, content_type, local_url)
    return AttachmentCreateResponse(
        attachment=AttachmentSummary.model_validate(attachment), upload=target
    )


@router.put("/{project_id}/chat/sessions/{session_id}/attachments/{attachment_id}/content")
async def upload_attachment_content_endpoint(
    project_id: str,
    session_id: str,
    attachment_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Local-storage mode only: receives the raw file bytes as the request
    body (no multipart) and streams them to disk. In GCS mode the browser
    uploads to the signed URL instead, and this route doesn't exist."""
    settings = get_settings()
    if settings.upload_storage == "gcs":
        raise HTTPException(status_code=404, detail="Not found")
    attachment = _get_attachment(db, project_id, session_id, attachment_id)
    if attachment.status != "pending_upload":
        raise HTTPException(status_code=409, detail="This attachment was already uploaded.")

    path = Path(attachment.storage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(path, "wb") as out:
            async for chunk in request.stream():
                written += len(chunk)
                if written > attachment.size_bytes or written > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Upload is larger than declared.")
                out.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    return {"size_bytes": written}


@router.post(
    "/{project_id}/chat/sessions/{session_id}/attachments/{attachment_id}/complete",
    response_model=AttachmentSummary,
)
async def complete_attachment_endpoint(
    project_id: str, session_id: str, attachment_id: str, db: Session = Depends(get_db)
) -> AttachmentSummary:
    """async (unlike its neighbours) because start_processing needs the
    running event loop to schedule the background task."""
    attachment = _get_attachment(db, project_id, session_id, attachment_id)
    if attachment.status != "pending_upload":
        return AttachmentSummary.model_validate(attachment)
    stored_size = upload_storage.stat(attachment.storage_path)
    if stored_size is None:
        raise HTTPException(status_code=409, detail="No uploaded file found for this attachment yet.")
    if stored_size != attachment.size_bytes:
        raise HTTPException(
            status_code=409,
            detail=f"Uploaded {stored_size} bytes but {attachment.size_bytes} were declared.",
        )
    attachment.status = "processing"
    db.commit()
    start_processing(attachment.id)
    db.refresh(attachment)
    return AttachmentSummary.model_validate(attachment)


@router.get(
    "/{project_id}/chat/sessions/{session_id}/attachments/{attachment_id}",
    response_model=AttachmentSummary,
)
def get_attachment_endpoint(
    project_id: str, session_id: str, attachment_id: str, db: Session = Depends(get_db)
) -> AttachmentSummary:
    return AttachmentSummary.model_validate(_get_attachment(db, project_id, session_id, attachment_id))


@router.delete(
    "/{project_id}/chat/sessions/{session_id}/attachments/{attachment_id}", status_code=204
)
def delete_attachment_endpoint(
    project_id: str, session_id: str, attachment_id: str, db: Session = Depends(get_db)
) -> None:
    """Only unsent attachments can be removed. Once sent, a file is part of
    the conversation history that later turns replay."""
    attachment = _get_attachment(db, project_id, session_id, attachment_id)
    if attachment.message_id is not None:
        raise HTTPException(status_code=409, detail="This attachment was already sent.")
    try:
        upload_storage.delete(attachment.storage_path)
    except Exception:
        logger.exception("Deleting stored file for attachment %s failed", attachment_id)
    attachment.deleted_at = datetime.utcnow()
    db.commit()
