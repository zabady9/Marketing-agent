"""Migration a3d9f1c47e20: old feasibility study rows are deleted (and chat
messages unlinked from them), old columns are dropped, goal/report are added,
and the glossary cache table is gone. Runs real alembic on a temp SQLite file."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

import app.config

ROOT = Path(__file__).resolve().parent.parent


def _alembic(db_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    app.config._settings = None
    return Config(str(ROOT / "alembic.ini"))


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_upgrade_clears_old_studies_and_reshapes_the_table(tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    cfg = _alembic(db, monkeypatch)
    try:
        command.upgrade(cfg, "7c1e4a9b2d30")

        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO projects (id, name, status) VALUES ('p1', 'P', 'active')")
        conn.execute(
            "INSERT INTO study_results (id, project_id, status, study_type, sections, fatal_agent_failures) "
            "VALUES ('st1', 'p1', 'completed', 'full', '{}', '[]')"
        )
        conn.execute("INSERT INTO chat_sessions (id, project_id) VALUES ('cs1', 'p1')")
        conn.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, status, study_id) "
            "VALUES ('m1', 'cs1', 'tool', 'x', 'complete', 'st1')"
        )
        conn.commit()
        conn.close()

        command.upgrade(cfg, "head")

        conn = sqlite3.connect(db)
        assert conn.execute("SELECT COUNT(*) FROM study_results").fetchone()[0] == 0
        assert conn.execute("SELECT study_id FROM chat_messages WHERE id='m1'").fetchone()[0] is None
        cols = _columns(conn, "study_results")
        assert {"goal", "report"} <= cols
        assert not cols & {"study_type", "requested_phase", "sections", "verdict", "confidence_score",
                           "qc_summary", "fatal_agent_failures"}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "glossary_cache" not in tables
        conn.close()

        command.downgrade(cfg, "7c1e4a9b2d30")
        conn = sqlite3.connect(db)
        assert "verdict" in _columns(conn, "study_results")
        conn.close()
    finally:
        app.config._settings = None
