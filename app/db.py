from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class DatabaseNotMigratedError(RuntimeError):
    pass


def check_database_is_migrated() -> None:
    """Fail fast when the database is behind the code's migrations — otherwise
    the app starts fine and only breaks mid-chat with a raw SQL error (e.g.
    "no column named goal"). Production runs `alembic upgrade head` before
    starting (see Dockerfile), so this only ever trips in local dev."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parent.parent
    heads = set(ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads())
    with engine.connect() as conn:
        current = set(MigrationContext.configure(conn).get_current_heads())
    if current != heads:
        raise DatabaseNotMigratedError(
            f"Database is at migration {sorted(current) or 'none'} but the code expects "
            f"{sorted(heads)}. Run: uv run alembic upgrade head"
        )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
