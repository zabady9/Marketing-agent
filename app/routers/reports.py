import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.consulting_analysis import ConsultingAnalysis
from app.schemas.consulting import ConsultingAnalysisRequest, ConsultingAnalysisResponse
from app.agents.eval_agent import run_eval
from app.services import event_bus
from app.services.analysis_subject import analysis_subject_to_dict, get_analysis_subject
from app.services.consulting import run_consulting_analysis
from app.services.workspace import get_workspace

router = APIRouter(tags=["reports"])


@router.post(
    "/{workspace_id}/reports:generate",
    response_model=ConsultingAnalysisResponse,
    status_code=202,
)
async def generate_report(
    workspace_id: str,
    data: ConsultingAnalysisRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    bp = await get_analysis_subject(db, workspace_id)
    if not bp:
        raise HTTPException(status_code=422, detail="Analysis subject not set — call PUT /analysis-subject first")

    analysis = ConsultingAnalysis(
        workspace_id=workspace_id,
        analysis_type=data.analysis_type,
        status="generating",
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    brand_dict = analysis_subject_to_dict(bp)

    event_bus.create(analysis.id)

    background_tasks.add_task(
        run_consulting_analysis,
        analysis_id=analysis.id,
        workspace_id=workspace_id,
        analysis_type=data.analysis_type,
        brand_profile=brand_dict,
        context=data.context,
    )

    return ConsultingAnalysisResponse(
        id=analysis.id,
        workspace_id=workspace_id,
        analysis_type=analysis.analysis_type,
        status=analysis.status,
        results=None,
        error=None,
        created_at=str(analysis.created_at),
    )


@router.get("/{workspace_id}/reports", response_model=list[ConsultingAnalysisResponse])
async def list_reports(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    result = await db.execute(
        select(ConsultingAnalysis)
        .where(ConsultingAnalysis.workspace_id == workspace_id)
        .order_by(ConsultingAnalysis.created_at.desc())
    )
    analyses = result.scalars().all()

    return [
        ConsultingAnalysisResponse(
            id=a.id,
            workspace_id=a.workspace_id,
            analysis_type=a.analysis_type,
            status=a.status,
            results=a.results,
            error=a.error,
            created_at=str(a.created_at),
        )
        for a in analyses
    ]


@router.get("/{workspace_id}/reports/{report_id}", response_model=ConsultingAnalysisResponse)
async def get_report(
    workspace_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConsultingAnalysis).where(
            ConsultingAnalysis.id == report_id,
            ConsultingAnalysis.workspace_id == workspace_id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Report not found")

    return ConsultingAnalysisResponse(
        id=analysis.id,
        workspace_id=analysis.workspace_id,
        analysis_type=analysis.analysis_type,
        status=analysis.status,
        results=analysis.results,
        error=analysis.error,
        created_at=str(analysis.created_at),
    )


@router.get("/{workspace_id}/reports/{report_id}/stream")
async def stream_report(
    workspace_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConsultingAnalysis).where(
            ConsultingAnalysis.id == report_id,
            ConsultingAnalysis.workspace_id == workspace_id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Report not found")

    if analysis.status in ("ready", "failed"):
        async def immediate():
            event = {
                "type": "done" if analysis.status == "ready" else "error",
                "message": analysis.error or "",
            }
            yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(immediate(), media_type="text/event-stream")

    async def generator():
        while True:
            event = await event_bus.read(report_id, timeout=25.0)
            if event is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{workspace_id}/reports/{report_id}:evaluate", response_model=ConsultingAnalysisResponse)
async def evaluate_report(
    workspace_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Re-run eval on a completed report and update results.eval in place."""
    result = await db.execute(
        select(ConsultingAnalysis).where(
            ConsultingAnalysis.id == report_id,
            ConsultingAnalysis.workspace_id == workspace_id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Report not found")
    if analysis.status != "ready":
        raise HTTPException(status_code=422, detail="Report must be in ready status to evaluate")
    if not analysis.results:
        raise HTTPException(status_code=422, detail="Report has no stored results to evaluate")

    stored = analysis.results
    eval_output = await run_eval(
        stored["analysis_type"],
        stored["output"],
        stored.get("citations", []),
    )

    updated_results = {**stored, "eval": eval_output.model_dump()}
    analysis.results = updated_results
    await db.commit()
    await db.refresh(analysis)

    return ConsultingAnalysisResponse(
        id=analysis.id,
        workspace_id=analysis.workspace_id,
        analysis_type=analysis.analysis_type,
        status=analysis.status,
        results=analysis.results,
        error=analysis.error,
        created_at=str(analysis.created_at),
    )
