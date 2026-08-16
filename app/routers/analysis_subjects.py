from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.analysis_subject import AnalysisSubjectUpsert, AnalysisSubjectResponse
from app.services.analysis_subject import get_analysis_subject, upsert_analysis_subject
from app.services.workspace import get_workspace

router = APIRouter(prefix="/workspaces", tags=["analysis-subject"])


@router.put("/{workspace_id}/analysis-subject", response_model=AnalysisSubjectResponse)
async def upsert_analysis_subject_endpoint(
    workspace_id: str,
    data: AnalysisSubjectUpsert,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return await upsert_analysis_subject(db, workspace_id, data)


@router.get("/{workspace_id}/analysis-subject", response_model=AnalysisSubjectResponse)
async def get_analysis_subject_endpoint(
    workspace_id: str, db: AsyncSession = Depends(get_db)
):
    subject = await get_analysis_subject(db, workspace_id)
    if not subject:
        raise HTTPException(status_code=404, detail="Analysis subject not set")
    return subject
