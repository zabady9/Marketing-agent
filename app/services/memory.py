from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import MemoryEntry


def list_memory_entries(db: Session) -> list[MemoryEntry]:
    return db.query(MemoryEntry).order_by(MemoryEntry.created_at.desc()).all()


def add_memory_entry(db: Session, content: str, source: str) -> MemoryEntry:
    entry = MemoryEntry(content=content.strip(), source=source)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def delete_memory_entry(db: Session, memory_id: str) -> bool:
    entry = db.query(MemoryEntry).filter_by(id=memory_id).one_or_none()
    if entry is None:
        return False
    db.delete(entry)
    db.commit()
    return True
