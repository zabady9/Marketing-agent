from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.postiz import PostizClient, PostizError
from app.database import get_db
from app.services.workspace import get_workspace

router = APIRouter(prefix="/workspaces", tags=["connections"])


@router.get("/{workspace_id}/connections")
async def list_connections(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    async with PostizClient() as client:
        try:
            integrations = await client.list_integrations()
        except PostizError as exc:
            raise HTTPException(status_code=502, detail=f"Postiz error: {exc}")

    return {"workspace_id": workspace_id, "connections": integrations}
