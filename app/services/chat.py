from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, Project
from app.schemas.admin import ChatMessageAdminUpdate, ChatSessionAdminUpdate

_TITLE_MAX_LEN = 60


def _derive_title(first_user_content: str) -> str:
    text = first_user_content.strip()
    if not text:
        return "New chat"
    return text if len(text) <= _TITLE_MAX_LEN else text[: _TITLE_MAX_LEN - 3].rstrip() + "..."


def create_chat_session(db: Session, project: Project) -> ChatSession:
    session = ChatSession(project_id=project.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_chat_sessions(db: Session, project: Project) -> list[ChatSession]:
    return (
        db.query(ChatSession)
        .filter(ChatSession.project_id == project.id, ChatSession.deleted_at.is_(None))
        .order_by(ChatSession.updated_at.desc())
        .all()
    )


def get_chat_session(db: Session, project: Project, session_id: str) -> ChatSession | None:
    """Scoped to project — prevents one project's routes from reading/writing
    another project's session by guessing an id."""
    return (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.project_id == project.id,
            ChatSession.deleted_at.is_(None),
        )
        .one_or_none()
    )


def list_chat_messages(db: Session, session: ChatSession) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.deleted_at.is_(None))
        .order_by(ChatMessage.created_at)
        .all()
    )


def maybe_set_title(session: ChatSession, first_user_content: str) -> None:
    """Call once, right after persisting a session's first user message. No-op
    if a title is already set, so later turns never overwrite it."""
    if session.title is None:
        session.title = _derive_title(first_user_content)


# ── Admin ──────────────────────────────────────────────────────────────────


def list_chat_sessions_admin(
    db: Session,
    *,
    limit: int,
    offset: int,
    include_deleted: bool,
    project_id: str | None = None,
) -> tuple[list[ChatSession], int]:
    query = db.query(ChatSession)
    if not include_deleted:
        query = query.filter(ChatSession.deleted_at.is_(None))
    if project_id is not None:
        query = query.filter(ChatSession.project_id == project_id)
    total = query.count()
    items = query.order_by(ChatSession.updated_at.desc()).offset(offset).limit(limit).all()
    return items, total


def get_chat_session_admin(db: Session, session_id: str) -> ChatSession | None:
    return db.query(ChatSession).filter_by(id=session_id).one_or_none()


def update_chat_session_title(
    db: Session, session: ChatSession, patch: ChatSessionAdminUpdate
) -> ChatSession:
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    return session


def soft_delete_chat_session(db: Session, session: ChatSession) -> ChatSession:
    now = datetime.utcnow()
    session.deleted_at = now
    for message in session.messages:
        if message.deleted_at is None:
            message.deleted_at = now
    db.commit()
    db.refresh(session)
    return session


def restore_chat_session(db: Session, session: ChatSession) -> ChatSession:
    previous = session.deleted_at
    session.deleted_at = None
    for message in session.messages:
        if message.deleted_at == previous:
            message.deleted_at = None
    db.commit()
    db.refresh(session)
    return session


def list_chat_messages_admin(
    db: Session,
    *,
    limit: int,
    offset: int,
    include_deleted: bool,
    session_id: str | None = None,
    role: str | None = None,
) -> tuple[list[ChatMessage], int]:
    query = db.query(ChatMessage)
    if not include_deleted:
        query = query.filter(ChatMessage.deleted_at.is_(None))
    if session_id is not None:
        query = query.filter(ChatMessage.session_id == session_id)
    if role is not None:
        query = query.filter(ChatMessage.role == role)
    total = query.count()
    items = query.order_by(ChatMessage.created_at).offset(offset).limit(limit).all()
    return items, total


def get_chat_message_admin(db: Session, message_id: str) -> ChatMessage | None:
    return db.query(ChatMessage).filter_by(id=message_id).one_or_none()


def update_chat_message(
    db: Session, message: ChatMessage, patch: ChatMessageAdminUpdate
) -> ChatMessage:
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(message, field, value)
    db.commit()
    db.refresh(message)
    return message


def soft_delete_chat_message(db: Session, message: ChatMessage) -> ChatMessage:
    message.deleted_at = datetime.utcnow()
    db.commit()
    db.refresh(message)
    return message


def restore_chat_message(db: Session, message: ChatMessage) -> ChatMessage:
    message.deleted_at = None
    db.commit()
    db.refresh(message)
    return message
