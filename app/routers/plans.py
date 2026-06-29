import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.content_plan import ContentPlan
from app.models.enums import PlanStatus
from app.models.post import Post
from app.schemas.plan import PlanCreateRequest, PlanResponse
from app.services import event_bus
from app.services.brand_profile import get_brand_profile, brand_profile_to_dict
from app.services.generation import run_generation
from app.services.workspace import get_workspace

router = APIRouter(prefix="/workspaces", tags=["plans"])


@router.post("/{workspace_id}/plans:generate", response_model=PlanResponse, status_code=202)
async def generate_plan(
    workspace_id: str,
    data: PlanCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    bp = await get_brand_profile(db, workspace_id)
    if not bp:
        raise HTTPException(status_code=422, detail="Brand profile not set — call PUT /brand first")

    plan = ContentPlan(
        workspace_id=workspace_id,
        goal=data.goal,
        status=PlanStatus.generating.value,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    brand_dict = brand_profile_to_dict(bp)

    # Create the event queue before the background task so SSE can connect immediately
    event_bus.create(plan.id)

    background_tasks.add_task(
        run_generation,
        plan_id=plan.id,
        workspace_id=workspace_id,
        brand_profile=brand_dict,
        goal=data.goal,
    )

    return PlanResponse(
        id=plan.id,
        workspace_id=workspace_id,
        goal=plan.goal,
        status=plan.status,
        error=None,
        posts=[],
        created_at=str(plan.created_at),
    )


@router.get("/{workspace_id}/plans", response_model=list[PlanResponse])
async def list_plans(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    result = await db.execute(
        select(ContentPlan)
        .where(ContentPlan.workspace_id == workspace_id)
        .order_by(ContentPlan.created_at.desc())
    )
    plans = result.scalars().all()

    out = []
    for plan in plans:
        posts_result = await db.execute(
            select(Post).where(Post.plan_id == plan.id).order_by(Post.day)
        )
        out.append(PlanResponse(
            id=plan.id,
            workspace_id=plan.workspace_id,
            goal=plan.goal,
            status=plan.status,
            error=plan.error,
            posts=list(posts_result.scalars().all()),
            created_at=str(plan.created_at),
        ))
    return out


@router.get("/{workspace_id}/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    workspace_id: str,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ContentPlan)
        .where(ContentPlan.id == plan_id, ContentPlan.workspace_id == workspace_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    posts_result = await db.execute(
        select(Post)
        .where(Post.plan_id == plan_id)
        .order_by(Post.day)
    )
    posts = posts_result.scalars().all()

    return PlanResponse(
        id=plan.id,
        workspace_id=plan.workspace_id,
        goal=plan.goal,
        status=plan.status,
        error=plan.error,
        posts=list(posts),
        created_at=str(plan.created_at),
    )


@router.get("/{workspace_id}/plans/{plan_id}/stream")
async def stream_plan(
    workspace_id: str,
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream for live generation progress."""
    result = await db.execute(
        select(ContentPlan).where(ContentPlan.id == plan_id, ContentPlan.workspace_id == workspace_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    # If plan already finished, send a single terminal event
    if plan.status in ("ready", "failed"):
        async def immediate():
            event = {"type": "done" if plan.status == "ready" else "error",
                     "message": plan.error or ""}
            yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(immediate(), media_type="text/event-stream")

    async def generator():
        while True:
            event = await event_bus.read(plan_id, timeout=25.0)
            if event is None:
                # Queue closed — generation finished
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
