from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.admin import router as admin_router
from app.routers.memory import router as memory_router
from app.routers.projects import router as projects_router

settings = get_settings()

app = FastAPI(
    title="Feasibility Study API",
    version="0.1.0",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
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
