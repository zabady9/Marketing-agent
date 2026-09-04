import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal
from app.models import ChatMessage
from app.routers.admin import router as admin_router
from app.routers.memory import router as memory_router
from app.routers.projects import router as projects_router

settings = get_settings()
logger = logging.getLogger(__name__)

# Generous on purpose: a single tool call within a chat turn (e.g. the full
# feasibility-study pipeline) can legitimately run for several minutes, and
# ChatMessage.updated_at is heartbeated throughout (see chat_agent.py). This
# sweep only exists to reconcile rows orphaned by a server crash/restart mid-
# generation — not as a tight liveness check — so a wide margin is cheap and
# avoids false positives on real, still-running turns.
_STUCK_GENERATION_GRACE_SECONDS = 30 * 60
_SWEEP_INTERVAL_SECONDS = 60


async def _sweep_stuck_generations() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(seconds=_STUCK_GENERATION_GRACE_SECONDS)
        stuck = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.role == "assistant",
                ChatMessage.status.in_(["pending", "streaming"]),
                ChatMessage.updated_at < cutoff,
            )
            .all()
        )
        if not stuck:
            return
        note = "\n\n[Generation was interrupted (server restart). Please try again.]"
        for message in stuck:
            message.content = (message.content + note) if message.content else note.strip()
            message.status = "error"
        db.commit()
        logger.warning("Marked %d orphaned chat generation(s) as errored", len(stuck))
    finally:
        db.close()


async def _sweep_loop() -> None:
    while True:
        try:
            await _sweep_stuck_generations()
        except Exception:
            logger.exception("Stuck-generation sweep failed")
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(
    title="Feasibility Study API",
    version="0.1.0",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "models": {
            "reasoning": settings.reasoning_model,
            "cheap": settings.cheap_model,
        },
        "search": "tavily",
        "tracing": settings.langsmith_tracing,
        "env": settings.app_env,
    }
