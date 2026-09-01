from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.config


@pytest.fixture
def db_session(monkeypatch):
    """Fresh in-memory SQLite DB per test. These tests exercise row-persistence
    and routing logic, not real LLM/search calls, so they shouldn't depend on a
    developer's real .env — set dummy settings before anything imports
    app.main (which builds/validates Settings at import time) and reset the
    module-level singleton so a real cached Settings from another test doesn't
    leak in."""
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    app.config._settings = None

    from app.db import Base
    from app import models  # noqa: F401 — registers all models on Base.metadata

    # StaticPool: TestClient dispatches sync route handlers onto worker
    # threads, and SQLAlchemy's default SingletonThreadPool for ":memory:"
    # SQLite hands each distinct thread its own private, schema-less
    # connection (a plain in-memory DB isn't shared across connections) — a
    # request landing on a thread that never ran create_all() would 500 with
    # "no such table". StaticPool makes every thread share the one connection.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    from app.db import get_db
    from app.main import app as fastapi_app

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def make_project(db_session):
    """Factory fixture creating a minimal Project + BusinessProfile pair
    directly via the ORM, bypassing the questionnaire/intake flow — these
    tests only need a project to hang a study off of. output_language="en" so
    get_or_create_glossary short-circuits without an LLM call."""
    from app.models import BusinessProfile, Project

    def _make(name: str = "Test Project") -> Project:
        project = Project(id=str(uuid.uuid4()), name=name)
        db_session.add(project)
        db_session.flush()

        profile = BusinessProfile(
            project_id=project.id,
            raw_user_input="A test business idea.",
            detected_language="en",
            output_language="en",
            business_description="A test business.",
            business_description_source="user_provided",
            problem_statement_source="user_provided",
            unique_value_proposition_source="user_provided",
            target_market_description_source="user_provided",
            target_market_geography_source="user_provided",
            target_market_type_source="user_provided",
            business_model_type_source="user_provided",
            capex_amount=1000.0,
            capex_currency="USD",
            capex_source="user_provided",
            funding_source_source="user_provided",
            opex_monthly_amount=100.0,
            opex_monthly_currency="USD",
            opex_monthly_source="user_provided",
            pricing_unit_price=10.0,
            pricing_currency="USD",
            pricing_source="user_provided",
            pricing_model_source="user_provided",
            expected_monthly_sales_source="user_provided",
            founder_risks_source="user_provided",
            key_roles_needed_source="user_provided",
            marketing_channels_source="user_provided",
            study_goal_source="user_provided",
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(project)
        return project

    return _make
