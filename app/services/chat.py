from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ChatSession, Project

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
        .filter_by(project_id=project.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )


def get_chat_session(db: Session, project: Project, session_id: str) -> ChatSession | None:
    """Scoped to project — prevents one project's routes from reading/writing
    another project's session by guessing an id."""
    return db.query(ChatSession).filter_by(id=session_id, project_id=project.id).one_or_none()


def maybe_set_title(session: ChatSession, first_user_content: str) -> None:
    """Call once, right after persisting a session's first user message. No-op
    if a title is already set, so later turns never overwrite it."""
    if session.title is None:
        session.title = _derive_title(first_user_content)
