from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers.feasibility import router as feasibility_router

settings = get_settings()

app = FastAPI(
    title="Feasibility Study API",
    version="0.1.0",
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(feasibility_router, prefix="/api")


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
