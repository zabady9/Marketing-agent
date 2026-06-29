import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        logger.error("Health check DB failure: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "db": "unavailable"},
        )
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
        "db": db_status,
    }
