from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import MemoryEntry


def list_memory_entries(db: Session) -> list[MemoryEntry]:
    return (
        db.query(MemoryEntry)
        .filter(MemoryEntry.deleted_at.is_(None))
        .order_by(MemoryEntry.created_at.desc())
        .all()
    )


def add_memory_entry(db: Session, content: str, source: str) -> MemoryEntry:
    entry = MemoryEntry(content=content.strip(), source=source)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def delete_memory_entry(db: Session, memory_id: str) -> bool:
    """Soft delete — reversible via the admin restore endpoint. Returns False
    (surfaced as a 404) if the entry doesn't exist or is already deleted."""
    entry = db.query(MemoryEntry).filter_by(id=memory_id).one_or_none()
    if entry is None or entry.deleted_at is not None:
        return False
    entry.deleted_at = datetime.utcnow()
    db.commit()
    return True
