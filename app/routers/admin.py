import secrets

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.action_log import ActionLog
from app.models.workspace import Workspace

_admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_admin_key(key: str | None = Security(_admin_key_header)) -> None:
    configured = settings.admin_api_key.get_secret_value()
    if not configured:
        raise HTTPException(status_code=503, detail="Admin API key not configured on server")
    if not key or not secrets.compare_digest(key, configured):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key header")


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


# ── Schemas ────────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    workspaces: int
    action_logs: int


class AdminWorkspace(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    autonomy_level: str
    created_at: str


class AdminLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    workspace_id: str
    actor: str
    action: str
    payload: dict
    result: dict | None
    created_at: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    ws_count = (await db.execute(select(func.count()).select_from(Workspace))).scalar_one()
    logs_count = (await db.execute(select(func.count()).select_from(ActionLog))).scalar_one()
    return StatsResponse(workspaces=ws_count, action_logs=logs_count)


@router.get("/workspaces", response_model=list[AdminWorkspace])
async def list_all_workspaces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()))
    return result.scalars().all()


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    await db.execute(delete(ActionLog).where(ActionLog.workspace_id == workspace_id))
    await db.delete(ws)
    await db.commit()


@router.get("/logs", response_model=list[AdminLog])
async def list_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ActionLog)
        .order_by(ActionLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()
