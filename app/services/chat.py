from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ChatSession, Project


def get_or_create_chat_session(db: Session, project: Project) -> ChatSession:
    """V1 gives each project a single implicit chat session — there is no
    multi-session UI yet, so callers never choose which session to post to."""
    if project.chat_sessions:
        return project.chat_sessions[0]

    session = ChatSession(project_id=project.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
