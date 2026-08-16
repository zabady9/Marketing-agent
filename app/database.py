import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

_pool_kwargs: dict = (
    {"poolclass": NullPool}
    if os.getenv("TESTING") == "true"
    else {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}
)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    **_pool_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
