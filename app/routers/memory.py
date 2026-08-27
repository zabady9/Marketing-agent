from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.memory import MemoryEntryCreate, MemoryEntryResponse
from app.services.memory import add_memory_entry, delete_memory_entry, list_memory_entries

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("", response_model=list[MemoryEntryResponse])
def list_memory_endpoint(db: Session = Depends(get_db)) -> list[MemoryEntryResponse]:
    return list_memory_entries(db)


@router.post("", response_model=MemoryEntryResponse, status_code=201)
def create_memory_endpoint(
    payload: MemoryEntryCreate, db: Session = Depends(get_db)
) -> MemoryEntryResponse:
    return add_memory_entry(db, payload.content, source="user_added")


@router.delete("/{memory_id}", status_code=204)
def delete_memory_endpoint(memory_id: str, db: Session = Depends(get_db)) -> None:
    if not delete_memory_entry(db, memory_id):
        raise HTTPException(status_code=404, detail="Memory entry not found")
