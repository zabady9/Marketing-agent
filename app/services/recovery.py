"""Startup recovery for plans stuck in 'generating' status.

Called once during lifespan startup after the Postgres checkpointer is ready.
Three cases per stuck plan:
  - No checkpoint   → mark failed (generation never ran or checkpoint store was cleared)
  - Checkpoint + posts exist → mark ready (crash between post-insert commit and status commit)
  - Checkpoint + no posts   → re-fire run_generation (resumes from END state instantly)
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import AsyncSessionLocal
from app.models.content_plan import ContentPlan
from app.models.enums import PlanStatus
from app.models.post import Post

logger = logging.getLogger(__name__)

_recovery_tasks: set[asyncio.Task] = set()


async def recover_stuck_plans(
    checkpointer,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> None:
    async with session_factory() as db:
        result = await db.execute(
            select(ContentPlan).where(ContentPlan.status == PlanStatus.generating.value)
        )
        stuck_plans = result.scalars().all()

    if not stuck_plans:
        return

    logger.info("Recovery: found %d plan(s) stuck in generating status", len(stuck_plans))

    for plan in stuck_plans:
        await _recover_plan(plan, checkpointer, session_factory)


async def _recover_plan(plan: ContentPlan, checkpointer, session_factory: async_sessionmaker) -> None:
    checkpoint_tuple = await checkpointer.aget_tuple(
        {"configurable": {"thread_id": plan.id}}
    )

    if checkpoint_tuple is None:
        async with session_factory() as db:
            plan_row = await db.get(ContentPlan, plan.id)
            if plan_row:
                plan_row.status = PlanStatus.failed.value
                plan_row.error = "NoCheckpoint"
                await db.commit()
        logger.warning("Recovery: plan %s has no checkpoint — marked failed", plan.id)
        return

    async with session_factory() as db:
        existing = await db.execute(
            select(Post.id).where(Post.plan_id == plan.id).limit(1)
        )
        if existing.scalar_one_or_none():
            plan_row = await db.get(ContentPlan, plan.id)
            if plan_row:
                plan_row.status = PlanStatus.ready.value
                await db.commit()
            logger.info(
                "Recovery: plan %s had posts but status=generating — marked ready", plan.id
            )
            return

    brand_profile = await _load_brand_profile(plan.workspace_id, session_factory)
    from app.services.generation import run_generation

    task = asyncio.create_task(
        run_generation(plan.id, plan.workspace_id, brand_profile, plan.goal, session_factory)
    )
    _recovery_tasks.add(task)
    task.add_done_callback(_recovery_tasks.discard)
    logger.info("Recovery: plan %s re-fired from checkpoint", plan.id)


async def _load_brand_profile(workspace_id: str, session_factory: async_sessionmaker) -> dict:
    from app.services.brand_profile import brand_profile_to_dict, get_brand_profile

    async with session_factory() as db:
        bp = await get_brand_profile(db, workspace_id)
        return brand_profile_to_dict(bp) if bp else {}
