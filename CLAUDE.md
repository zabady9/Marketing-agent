# Marketing Agent — Codebase Overview

## Project Summary

Marketing Agent is an AI-powered content planning and publishing platform. LangGraph-based agents (Gemini) generate 7-day social media content plans, write posts, critique for brand fit, and publish via Postiz. Humans approve everything before publishing.

### Tech Stack

**Backend:** FastAPI 0.138.1 · SQLAlchemy 2.0.51 async · asyncpg · PostgreSQL 16 + pgvector · Alembic 1.18.5 · LangGraph 1.2.6 · LangChain Core 1.4.8 · langchain-google-genai · Pydantic 2.13.4 · sentence-transformers (BAAI/bge-base-en-v1.5)

**Frontend:** React 18.3.1 · TypeScript · React Router 6.28 · Vite 6 · Tailwind CSS 3.4.17

**Infra:** Postiz v2.11.3 (Docker) · Redis 7 · Nginx · Docker Compose

**Tests:** pytest 8.3.4 · pytest-asyncio 0.24.0 · pytest-mock 3.15.1 · respx 0.23.1

---

## Directory Layout

```
app/
  main.py              # FastAPI app, router registration
  config.py            # Pydantic Settings
  database.py          # AsyncSessionLocal, get_db(), Base
  routers/             # health, workspaces, brand_profiles, plans, posts,
                       # connections, knowledge, admin
  models/              # workspace, brand_profile, content_plan, post, action_log,
                       # knowledge_document, knowledge_chunk, enums, __init__
  schemas/             # workspace, brand_profile, plan, post, knowledge, action_log
  services/            # generation, regenerate, publishing, post_status, action_log,
                       # brand_profile, workspace, event_bus, embeddings,
                       # knowledge_ingestion, knowledge_search
  agents/              # graph, llm, strategy_agent, content_agent, critic_agent, schemas
  clients/             # postiz

frontend/src/
  App.tsx / api.ts / types.ts / vite-env.d.ts
  pages/  WorkspacesPage, WorkspacePage, PlanPage,
          OnboardingWizard, BrandBrainPage, admin/*

tests/                 # 17 files, 93 tests (Phase 1 baseline)
  conftest.py          # exposes _TestSessionLocal for background task tests

alembic/versions/
  755ee710511d_initial_schema.py
  20260702152447_brand_brain_phase1.py
```

---

## Running

```bash
# Local dev (Postgres at localhost:5432/marketing)
DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/marketing \
  /opt/miniconda3/envs/Marketing-agent/bin/uvicorn app.main:app --reload --port 8000

# Local tests
DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/marketing \
  /opt/miniconda3/envs/Marketing-agent/bin/python -m pytest tests/ -v

# Docker: make dev-build → API at http://localhost:8001
```

---

## Database Tables

| Table | Notable Columns |
|-------|----------------|
| workspaces | id, name, autonomy_level |
| brand_profiles | workspace_id · brand_name, company_name, industry · products/audience_segments/goals (JSON) · tone, voice_guidelines, positioning · avoid (JSON) · onboarding_status (VARCHAR) |
| content_plans | workspace_id, goal, status (VARCHAR: generating/ready/failed) |
| posts | plan_id, workspace_id · day (INT NOT NULL) · theme, format, **angle (Text NOT NULL)** · content · hashtags (JSON) · suggested_time · status (VARCHAR) · postiz_post_id |
| action_logs | workspace_id, actor, action, payload/result (JSON) |
| knowledge_documents | workspace_id, filename, doc_type, storage_path, status (VARCHAR) |
| knowledge_chunks | document_id, workspace_id · content (Text) · **embedding (vector(768))** · metadata (JSON) |

All enum columns: `native_enum=False` → VARCHAR. IVFFlat index on `knowledge_chunks.embedding`.

Alembic chain: `755ee710511d → 20260702152447`

---

## API Reference

```
GET  /api/health
POST/GET /api/workspaces, /api/workspaces/{id}

PUT/GET /api/workspaces/{id}/brand-profile     ← canonical (Phase 1)
PUT/GET /api/workspaces/{id}/brand             ← deprecated alias

POST /api/workspaces/{id}/plans:generate
GET  /api/workspaces/{id}/plans / /{plan_id} / /{plan_id}/stream   ← SSE

POST /api/posts/{id}:approve | :reject | :regenerate | :schedule
PATCH /api/posts/{id}
POST /api/posts/{id}:submit                    ← Phase 2: draft → pending_approval

POST/GET /api/workspaces/{id}/knowledge/documents
DELETE   /api/workspaces/{id}/knowledge/documents/{doc_id}
GET      /api/workspaces/{id}/knowledge/search?q=

GET  /api/workspaces/{id}/connections
GET  /api/admin/*   (X-Admin-Key header)
```

---

## LangGraph Content Generation

**GraphState** (`app/agents/graph.py`):
```
brand_profile, goal, ideas, current_idx, revision_count,
current_content, finished_posts, action_logs, workspace_id, plan_id
```

`workspace_id` chain: router → `run_generation(workspace_id)` → `initial_state["workspace_id"]` → `strategy_node` → `search_knowledge(query, workspace_id, db)`

`get_llm("reasoning")` = gemini-2.5-pro · `get_llm("cheap")` = gemini-2.5-flash

`with_structured_output(..., method="json_schema")` is used by content agents — **disables token streaming, never use on chat LLM**.

---

## Post Status Machine

```
draft → pending_approval → approved → scheduled → published
                        ↘ rejected
```
`transition()` in `app/services/post_status.py`. `draft → pending_approval` is already a valid transition.

---

## Event Bus (SSE)

`app/services/event_bus.py` — `asyncio.Queue` per string key:

| Function | Purpose |
|----------|---------|
| `create(key)` | Open queue before background task |
| `emit(key, dict)` | Push event |
| `read(key, timeout=30)` | Pop; returns `{"type":"ping"}` on timeout |
| `close(key)` | None sentinel + remove |
| `exists(key)` | Guard against double-create |

Keys: `plan_id` for generation · `session_id` for Phase 2 chat

Event types: `token` · `tool_start` · `tool_end` · `done` · `error` · `ping`

SSE generator pattern — copy from `app/routers/plans.py` ~L162-180:
```python
return StreamingResponse(generator(), media_type="text/event-stream")
```

---

## Embeddings

`app/services/embeddings.py` — BAAI/bge-base-en-v1.5, lazy singleton, `asyncio.to_thread()`:
- `embed_text(query)` → BGE query prefix → `list[float]` (768-dim)
- `embed_many(texts)` → no prefix → `list[list[float]]`
- `search_knowledge(query, workspace_id, db, k=5)` → `list[KnowledgeChunk]`

---

## Critical Design Rules

1. **Background task sessions.** Never pass the request `AsyncSession` to a background task. Open `async with AsyncSessionLocal() as db:` inside the task.
2. **`native_enum=False` everywhere.** Both model AND migration must declare `sa.Enum(..., native_enum=False)`.
3. **`with_structured_output` disables streaming.** Only for content agents. Never on chat LLM.
4. **`asyncio.create_task()` inside background tasks.** Safe. Used by Phase 2 `trigger_plan_generation`.
5. **`event_bus.exists(key)` guard.** Always check before `event_bus.create(key)`.
6. **`metadata_` column.** `KnowledgeChunk` uses `mapped_column("metadata")` with Python attribute `metadata_`.

---

## Testing Conventions

- `AsyncMock` + `unittest.mock.patch()` for async mocking
- Direct `db.add()` in helpers for DB seeding
- `_TestSessionLocal` from `conftest.py` for background task function tests
- `tempfile.TemporaryDirectory()` + `patch(...)` for file system ops

---

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://postgres:changeme@db:5432/marketing
GOOGLE_API_KEY=<key>
REASONING_MODEL=gemini-2.5-pro  CHEAP_MODEL=gemini-2.5-flash  MAX_TOKENS=8192
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5  EMBEDDING_DIMENSION=768
UPLOADS_DIR=/app/uploads
POSTIZ_API_URL=http://postiz:5000  POSTIZ_API_KEY=<key>
ADMIN_API_KEY=<key>  ALLOWED_ORIGINS=["http://localhost:3000"]
```
