# Marketing Agent — Complete Project Reference

> A comprehensive guide for any agent or engineer joining this project cold. Covers business goals, architecture, user flows, roles, UX behavior, APIs, data models, AI workflows, and implementation decisions.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Business Goals & Guiding Principles](#2-business-goals--guiding-principles)
3. [Tech Stack](#3-tech-stack)
4. [Directory Structure](#4-directory-structure)
5. [User Roles & Permissions](#5-user-roles--permissions)
6. [User Flows](#6-user-flows)
7. [UX / UI Behavior](#7-ux--ui-behavior)
8. [Data Models](#8-data-models)
9. [Post Status State Machine](#9-post-status-state-machine)
10. [AI Agent Workflow (LangGraph)](#10-ai-agent-workflow-langgraph)
11. [Backend API Reference](#11-backend-api-reference)
12. [Frontend Pages & Components](#12-frontend-pages--components)
13. [Service Layer](#13-service-layer)
14. [Postiz Integration](#14-postiz-integration)
15. [Real-time Streaming (SSE + Event Bus)](#15-real-time-streaming-sse--event-bus)
16. [Authentication & Authorization](#16-authentication--authorization)
17. [Environment Variables](#17-environment-variables)
18. [Database & Migrations](#18-database--migrations)
19. [Testing](#19-testing)
20. [Deployment](#20-deployment)
21. [Key Design Decisions](#21-key-design-decisions)
22. [Known Limitations & Future Work](#22-known-limitations--future-work)

---

## 1. Project Summary

**Marketing Agent** is an AI-powered social media content planning and publishing platform. Given a workspace's brand profile and a weekly goal, the system autonomously drafts a 7-day social media content plan, writes each post, critiques it for brand safety, and presents everything to a human for review before anything is published.

**The one non-negotiable constraint: humans approve everything before publishing. The system never posts autonomously.**

The platform bridges three systems:
- **Google Gemini** (via LangChain) — the intelligence layer that generates and critiques content
- **PostgreSQL** — persistent store for workspaces, brand profiles, plans, posts, and audit logs
- **Postiz** — a self-hosted social media scheduler that handles the actual publishing to LinkedIn, X, etc.

---

## 2. Business Goals & Guiding Principles

| Goal | Implementation |
|------|---------------|
| Reduce content creation time | 7-day plan generated in one request, fully AI-written |
| Maintain brand consistency | Brand profile (tone, audience, avoid list) injected into every agent call |
| Human oversight always | Every post goes through `pending_approval` before it can be scheduled |
| Auditability | Every action (approve, reject, edit, regenerate, schedule) is logged to `action_logs` |
| Multi-tenant | Each workspace is isolated — its own brand profile, plans, and posts |
| Human oversight is a permanent constraint | `supervised` is the only intended operating mode. `AutonomyLevel` enum exists for schema compatibility. Autonomous auto-approval — publishing without human review — is out of scope by design. |

---

## 3. Tech Stack

### Backend
| Layer | Choice | Version |
|-------|--------|---------|
| Web framework | FastAPI | 0.138.1 |
| ASGI server | Uvicorn | — |
| ORM | SQLAlchemy (async) | 2.0.51 |
| DB driver | asyncpg | — |
| Migrations | Alembic | 1.18.5 |
| Validation | Pydantic | 2.13.4 |
| AI orchestration | LangGraph | 1.2.6 |
| LLM SDK | LangChain Core + langchain-google-genai | 1.4.8 |
| LLM model | Google Gemini 2.5 Pro / Flash | — |
| Tracing (optional) | LangSmith | — |
| HTTP client | httpx (async) | — |

### Frontend
| Layer | Choice | Version |
|-------|--------|---------|
| UI library | React | 18.3.1 |
| Language | TypeScript | — |
| Bundler | Vite | 6 |
| Routing | React Router | 6.28 |
| Styling | Tailwind CSS | 3.4.17 |

### Infrastructure
| Service | Purpose |
|---------|---------|
| PostgreSQL 16 | App database |
| Postiz v2.11.3 | Social scheduler (self-hosted Docker) |
| Redis 7 | Postiz cache (required by Postiz) |
| Nginx | Reverse proxy + SSL termination (GCP) |
| Docker + Compose | Full-stack local and production orchestration |

### Service Ports

| Service | Container Port | Host Port |
|---------|---------------|-----------|
| FastAPI | 8000 | 8001 |
| PostgreSQL (app) | 5432 | 5432 |
| Postiz | 5000 | 5174 |
| React dev server | 5173 | 3000 |

> Port 8001 (not 8000) is used on the host because port 8000 was already occupied on this dev machine. Port 5174 (not 5000) is used because macOS AirPlay occupies 5000.

---

## 4. Directory Structure

```
Marketing-agent/
├── app/                           # FastAPI application
│   ├── main.py                    # App factory, router registration, CORS, lifespan
│   ├── config.py                  # Pydantic Settings (all env vars)
│   ├── database.py                # SQLAlchemy engine, async session factory, Base
│   ├── routers/
│   │   ├── health.py              # GET /api/health
│   │   ├── workspaces.py          # Workspace CRUD
│   │   ├── brand_profiles.py      # Brand profile upsert/get (canonical: /brand-profile)
│   │   ├── plans.py               # Plan generation + SSE stream
│   │   ├── posts.py               # Post lifecycle (approve/reject/edit/regenerate/schedule/submit)
│   │   ├── connections.py         # Postiz social integrations list
│   │   ├── knowledge.py           # Knowledge document upload + semantic search
│   │   ├── chat.py                # Chat sessions + message send + SSE stream
│   │   └── admin.py               # Admin-only endpoints (key-protected)
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── workspace.py
│   │   ├── brand_profile.py
│   │   ├── content_plan.py
│   │   ├── post.py
│   │   ├── action_log.py
│   │   ├── knowledge_document.py
│   │   ├── knowledge_chunk.py
│   │   ├── chat.py                # ChatSession, ChatMessage, MessageRole
│   │   └── enums.py               # PostStatus, PlanStatus, AutonomyLevel, OnboardingStatus, DocumentStatus
│   ├── schemas/                   # Pydantic request/response DTOs
│   │   ├── workspace.py
│   │   ├── brand_profile.py
│   │   ├── plan.py
│   │   ├── post.py
│   │   ├── action_log.py
│   │   ├── knowledge.py
│   │   └── chat.py
│   ├── services/
│   │   ├── generation.py          # run_generation() background task
│   │   ├── regenerate.py          # regenerate_post() background task
│   │   ├── publishing.py          # schedule_post() → Postiz
│   │   ├── post_status.py         # transition() state machine
│   │   ├── brand_profile.py       # brand_profile_to_dict() helper
│   │   ├── workspace.py           # create_workspace(), get_workspace()
│   │   ├── action_log.py          # log_action() audit trail
│   │   ├── event_bus.py           # asyncio.Queue keyed by plan_id or session_id
│   │   ├── embeddings.py          # BAAI/bge-base-en-v1.5 singleton; embed_text/embed_many
│   │   ├── knowledge_ingestion.py # ingest_document() — chunk, embed, store
│   │   ├── knowledge_search.py    # search_knowledge() — pgvector cosine search
│   │   └── chat.py                # Session CRUD, save_message, get_or_create_chat_draft_plan
│   ├── agents/
│   │   ├── graph.py               # LangGraph StateGraph definition
│   │   ├── llm.py                 # get_llm(tier) factory
│   │   ├── strategy_agent.py      # StrategyAgent — generates 7 ideas
│   │   ├── content_agent.py       # ContentAgent — writes post copy
│   │   ├── critic_agent.py        # CriticAgent — reviews brand safety
│   │   ├── schemas.py             # Pydantic schemas for structured LLM outputs
│   │   ├── chat_agent.py          # Manual agentic loop (langchain-core only)
│   │   └── chat_tools.py          # search_brand_knowledge, create_draft_post, trigger_plan_generation
│   └── clients/
│       └── postiz.py              # PostizClient — async httpx wrapper
├── frontend/
│   └── src/
│       ├── App.tsx                # Router + layout
│       ├── api.ts                 # All API calls (typed)
│       ├── types.ts               # TypeScript interfaces mirroring backend
│       ├── pages/
│       │   ├── WorkspacesPage.tsx
│       │   ├── WorkspacePage.tsx
│       │   ├── PlanPage.tsx
│       │   ├── OnboardingWizard.tsx  # Multi-step brand profile setup
│       │   ├── BrandBrainPage.tsx    # Brand profile view + knowledge document management
│       │   ├── ChatPage.tsx          # Conversational AI assistant
│       │   └── admin/             # 5 admin pages
│       └── components/
│           ├── PostCard.tsx
│           └── ScheduleModal.tsx
├── tests/                         # pytest test suite (17 files, ~107 tests)
├── alembic/
│   └── versions/
│       ├── 755ee710511d_initial_schema.py          # base — 5 tables
│       ├── 20260702152447_brand_brain_phase1.py    # brand_profiles revised; knowledge tables + pgvector
│       └── 20260702200000_chat_phase2.py           # chat_sessions, chat_messages
├── nginx/                         # Nginx config templates
├── docker-compose.yml
├── docker-compose.nginx.yml
├── Dockerfile
├── Makefile
└── requirements.txt
```

---

## 5. User Roles & Permissions

The system has two roles. There is no login/session system — role distinction is purely by API key for admin endpoints.

### Regular User (no authentication required)
Can do everything related to their workspace content:
- Create and view workspaces
- Set/update brand profile
- Trigger content plan generation
- Stream generation progress via SSE
- View generated posts
- Approve, reject, edit posts
- Regenerate posts with AI
- Schedule approved posts to social media
- View connected social accounts

### Admin (requires `X-Admin-Key` header matching `ADMIN_API_KEY`)
Full system-wide read and delete access:
- View all workspaces across the system
- View all content plans
- View all posts (filterable by status)
- View full audit log with pagination
- Delete any workspace, plan, or post
- View system-wide aggregate statistics

**Important:** Admins cannot generate content or schedule posts — those are workspace-user operations.

---

## 6. User Flows

### Flow 1: First-Time Workspace Setup

```
1. Navigate to "/" (WorkspacesPage)
2. Click "New Workspace" → enter name
3. POST /api/workspaces → workspace created
4. Click workspace card → WorkspacePage
5. Fill brand profile form:
   - Brand name, target audience, tone of voice
   - Language (e.g., "English")
   - Words/topics to avoid (comma-separated)
6. PUT /api/workspaces/{wsId}/brand → profile saved
```

### Flow 2: Generate a Content Plan

```
1. On WorkspacePage, enter weekly goal (optional)
   Example: "Promote our summer sale with 20% off"
2. Click "Generate Plan"
3. POST /api/workspaces/{wsId}/plans:generate → 202 Accepted
   (returns plan_id immediately, generation runs in background)
4. Frontend navigates to /workspaces/{wsId}/plans/{planId}
5. PlanPage opens SSE stream → live terminal appears
6. Watch real-time events as each post is written and reviewed
7. When done → 7 post cards appear below the terminal
```

### Flow 3: Review and Approve Posts

```
1. On PlanPage, review each PostCard
2. Read the content, theme, format, hashtags, suggested time
3. Options:
   a. Click "Approve" → post moves to 'approved'
   b. Click "Reject" (with optional reason) → post moves to 'rejected'
   c. Click "Edit" → inline textarea opens, edit content/hashtags/time
      → Save → if post was approved, it resets to 'pending_approval'
   d. Click "Regenerate" → optional note for the AI, triggers background rewrite
      → post returns to 'pending_approval' when done
4. Approved posts show "Schedule" button
```

### Flow 4: Schedule a Post

```
1. Click "Schedule" on an approved post
2. ScheduleModal opens:
   - Lists connected social accounts (from Postiz)
   - Select one (LinkedIn, X, etc.)
   - Pick date and time (defaults to tomorrow 9 AM)
3. Click "Schedule"
4. POST /api/posts/{postId}:schedule
5. Backend calls Postiz API → post queued for publishing
6. Post status → 'scheduled' (postiz_post_id stored)
7. Postiz handles the actual publishing; status → 'published' when done
```

### Flow 5: Admin Monitoring

```
1. Navigate to /admin (requires VITE_ADMIN_API_KEY env var set)
2. AdminDashboardPage: aggregate stats (workspaces, plans, posts by status)
3. AdminWorkspacesPage: all workspaces, delete capability
4. AdminPlansPage: all plans across all workspaces
5. AdminPostsPage: all posts, filterable by status
6. AdminLogsPage: paginated action audit trail
```

---

## 7. UX / UI Behavior

### WorkspacesPage
- Card grid of workspaces
- Inline create form (no modal)
- Each card shows: name, autonomy level badge, creation date
- Click anywhere on card navigates to workspace

### WorkspacePage
- Two sections stacked vertically:
  1. **Brand Profile** — form with save button. Shows current values. Marks unsaved changes.
  2. **Content Plans** — "Generate Plan" input + button at top, then list of past plans below
- Plan list items show: status badge (color-coded), goal preview, post count, date
- Status colors: `generating` = yellow, `ready` = green, `failed` = red

### PlanPage
- **Top section: Live Terminal**
  - Dark background, monospace font, macOS-style chrome
  - Scrolls to bottom as new events arrive
  - Color-coded event lines:
    - Gray: status messages
    - Blue: strategy complete
    - Yellow: writing a post
    - White: post content preview (truncated to ~100 chars)
    - Orange: critic revision needed + issues list
    - Green: post approved
    - Bright green: all done
    - Red: error
  - Terminal hides when plan is in `ready` or `failed` state (stays visible while `generating`)
- **Bottom section: Post Cards**
  - Rendered once plan is `ready`
  - One card per day (Day 1–7)

### PostCard
- Collapsed by default: shows day, format with emoji, time, status badge
- Expand: shows theme, angle, full content, hashtags
- **Edit mode:** textarea replaces content display, comma-separated hashtags field, time field
- **Action buttons** are context-sensitive:
  - `pending_approval`: "Approve" (green), "Edit", "Regenerate", "Reject"
  - `approved`: "Schedule" (blue), "Edit", "Regenerate", "Reject"
  - `scheduled` / `published`: no edit buttons (terminal state)
  - `rejected`: no action buttons
- Inline rejection form: text input for reason
- Inline regeneration form: text input for note to AI
- Errors display inline below the relevant button

### ScheduleModal
- Full-screen backdrop with centered modal
- Shows loading spinner while fetching connections
- Radio list of social accounts (picture + name + handle)
- Grays out / hides disabled connections
- Date + time inputs (browser native)
- Close on backdrop click or "Cancel"

### Admin Pages
- Separate layout with nav sidebar
- Tables with pagination for logs
- Delete buttons with confirmation

---

## 8. Data Models

### Workspace
```
id            UUID, PK
name          TEXT, NOT NULL
autonomy_level  ENUM (supervised|assisted|autonomous), default: supervised
created_at    TIMESTAMP
updated_at    TIMESTAMP
```

### BrandProfile
```
id                UUID, PK
workspace_id      UUID, FK → workspaces (CASCADE), indexed
brand_name        TEXT, nullable
company_name      TEXT, nullable
industry          TEXT, nullable
products          JSON, NOT NULL, default=[]   # list of product/service descriptions
audience_segments JSON, NOT NULL, default=[]   # list of target audience descriptions
goals             JSON, NOT NULL, default=[]   # list of marketing goals
tone              TEXT, nullable               # e.g. "professional, friendly"
voice_guidelines  TEXT, nullable
positioning       TEXT, nullable
avoid             JSON, NOT NULL, default=[]   # list of words/topics to avoid
extra             JSON, NOT NULL, default={}   # arbitrary extra guidelines
onboarding_status VARCHAR, NOT NULL            # 'in_progress' | 'pending_review' | 'active'
                                               # server_default='in_progress'
created_at        TEXT   # string, server_default=now() — codebase-wide convention
updated_at        TEXT
```

### ContentPlan
```
id            UUID, PK
workspace_id  UUID, FK → workspaces (CASCADE)
goal          TEXT, nullable   # user-specified weekly goal
status        ENUM (generating|ready|failed)
error         TEXT, nullable   # failure reason if status=failed
created_at    TIMESTAMP
updated_at    TIMESTAMP
```

### Post
```
id              UUID, PK
plan_id         UUID, FK → content_plans (CASCADE)
workspace_id    UUID, FK → workspaces (CASCADE)
day             INT           # 1–7
theme           TEXT          # content theme for this day
format          TEXT          # e.g. "carousel", "reel", "text"
angle           TEXT          # creative angle
content         TEXT          # the post body
hashtags        JSON[]        # list of hashtag strings
suggested_time  TEXT          # ISO-8601 datetime suggestion from AI
status          ENUM (draft|pending_approval|approved|scheduled|published|rejected)
postiz_post_id  TEXT, nullable  # ID returned by Postiz on scheduling
created_at      TIMESTAMP
updated_at      TIMESTAMP
```

### ActionLog
```
id          UUID, PK
workspace_id  UUID, nullable
plan_id       UUID, nullable
post_id       UUID, nullable
actor         TEXT    # "user" or "agent"
action        TEXT    # e.g. "approve", "reject", "generate_ideas"
payload       JSON    # input data
result        JSON    # outcome data
created_at    TIMESTAMP
```

### KnowledgeDocument
```
id           UUID, PK
workspace_id UUID, FK → workspaces (CASCADE), indexed
filename     TEXT, NOT NULL
doc_type     TEXT, NOT NULL, default='other'
storage_path TEXT, NOT NULL
status       VARCHAR, NOT NULL   # 'processing' | 'indexed' | 'failed'; server_default='processing'
uploaded_at  TEXT                # string, server_default=now()
```

### KnowledgeChunk
```
id           UUID, PK
document_id  UUID, FK → knowledge_documents (CASCADE)
workspace_id UUID, FK → workspaces (CASCADE), indexed
content      TEXT, NOT NULL
embedding    vector(768)         # pgvector; IVFFlat index for cosine search
metadata_    JSON                # Python attr name; DB column name is "metadata"
created_at   TEXT
```

### ChatSession
```
id           UUID, PK
workspace_id UUID, FK → workspaces (CASCADE), indexed
title        TEXT, nullable      # auto-set from first user message (truncated to ~60 chars)
created_at   TEXT
updated_at   TEXT
```

### ChatMessage
```
id           UUID, PK
session_id   UUID, FK → chat_sessions (CASCADE), indexed
workspace_id UUID, FK → workspaces (CASCADE), indexed
role         VARCHAR, NOT NULL   # 'user' | 'assistant'; native_enum=False
content      TEXT, NOT NULL
metadata_    JSON                # Python attr name; DB column name is "metadata"
                                 # e.g. {"draft_post_id": "..."} when a post was created
created_at   TEXT
```

---

## 9. Post Status State Machine

```
                      GENERATION
                          │
                          ▼
                   pending_approval  ◄──── edit / regenerate ──┐
                          │                                     │
              ┌───────────┴───────────┐                        │
              ▼                       ▼                        │
           approved               rejected                     │
              │                                                │
   ┌──────────┼──────────────────────────────────────────────►─┘
   │          │
   │          ▼
   │       scheduled
   │          │
   │          ▼
   │       published
   │
   └──► rejected (from approved)
```

**Enforced by `transition()` in `app/services/post_status.py`:**

| From | To | Trigger |
|------|-----|---------|
| `draft` | `pending_approval` | User clicks "Send for Approval" on a chat-created draft post (`:submit` endpoint) |
| `pending_approval` | `approved` | User clicks Approve |
| `pending_approval` | `rejected` | User clicks Reject |
| `approved` | `pending_approval` | User edits or regenerates |
| `approved` | `scheduled` | User schedules via Postiz |
| `approved` | `rejected` | User clicks Reject |
| `scheduled` | `published` | Postiz publishes the post |

Any other transition raises `InvalidTransition`. The state machine is the single source of truth — routers call `transition()` and never mutate `status` directly.

---

## 10. AI Agent Workflow (LangGraph)

### Overview

Content generation is a **LangGraph StateGraph** with four node types: `strategy`, `content`, `critic`, and `advance`. The graph runs as an async background task.

### Graph State

```python
class GraphState(TypedDict):
    brand_profile: dict          # Brand guidelines passed to every agent
    goal: str | None             # User's weekly goal
    ideas: list[ContentIdea]     # 7 ideas from StrategyAgent
    current_idx: int             # Which idea we're working on (0–6)
    current_content: ContentOutput | None   # Content being reviewed
    revision_count: int          # 0 or 1 (max 1 revision per post)
    finished_posts: list[dict]   # Completed posts, appended after critic approves
```

### Node: `strategy_node`

- **Model:** Gemini 2.5 Pro (`reasoning` tier)
- **Input:** brand_profile, goal
- **Output:** Exactly 7 `ContentIdea` objects `{day, theme, format, angle}`
- **Behavior:** Uses `with_structured_output(StrategyOutput, method="json_schema")`. If fewer/more than 7 ideas returned, truncates or raises. Emits `strategy_done` SSE event.

### Node: `content_node`

- **Model:** Gemini 2.5 Pro (`reasoning` tier)
- **Input:** `ideas[current_idx]`, brand_profile, optional revision_hint (from critic)
- **Output:** `ContentOutput {content, hashtags, suggested_time}`
- **Behavior:** First pass writes from scratch. Second pass (if `revision_count > 0`) rewrites using the critic's `issues` as a revision hint. Emits `post_written` SSE event.

### Node: `critic_node`

- **Model:** Gemini 2.5 Flash (`cheap` tier — cost optimization)
- **Input:** current_content, brand_profile
- **Output:** `CriticOutput {approved: bool, issues: list[str], fixed_body: str | None}`
- **Behavior:**
  - Checks tone alignment, spelling, grammar, avoid-list compliance
  - If `approved=True`: passes content to `finished_posts`
  - If `approved=False` and `revision_count == 0`: sends back to `content_node` with issues as hint
  - If `approved=False` and `revision_count == 1` (already revised once): accepts with `fixed_body` if provided, otherwise uses original
  - Emits `critic_start`, `critic_revision`, or `post_approved` SSE events

### Node: `advance_node`

- Increments `current_idx`
- Routes: if `current_idx < 7` → back to `content_node`; else → `END`

### Routing Logic

```
strategy_node
     │
     ▼
content_node ◄────────────────────────────────────────┐
     │                                                 │
     ▼                                                 │
critic_node                                            │
     │                                                 │
     ├── approved=True ────────────────────► advance_node ──► (next idea or END)
     │
     └── approved=False, revision_count==0 ──────────►─┘ (rewrite with hint)
```

### Checkpointing

Currently uses `MemorySaver` (in-memory only). State is lost on restart. **Phase 3 plans to replace this with a Postgres checkpointer** for durable human-in-the-loop interrupts.

### LLM Configuration

```python
# app/agents/llm.py
def get_llm(tier: Literal["reasoning", "cheap"]) -> ChatGoogleGenerativeAI:
    model = settings.reasoning_model if tier == "reasoning" else settings.cheap_model
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key,
        max_tokens=settings.max_tokens,  # default 8192
        max_retries=3,
    )
```

| Tier | Default Model | Used By |
|------|--------------|---------|
| `reasoning` | `gemini-2.5-pro` | StrategyAgent, ContentAgent |
| `cheap` | `gemini-2.5-flash` | CriticAgent, Chat agent |

### Post Regeneration (single post)

When a user clicks "Regenerate" on an existing post, a separate background task in `regenerate.py` runs:
1. Calls ContentAgent with optional user note as `revision_hint`
2. Calls CriticAgent on the result
3. Applies `fixed_body` if critic provided one
4. Updates post in DB, resets status to `pending_approval`

This does **not** use the full LangGraph; it's a direct agent call sequence.

---

### Chat Agent (Phase 2 — manual agentic loop)

The chat assistant in `app/agents/chat_agent.py` uses `langchain-core` primitives only. The `langchain` main package is not installed — `AgentExecutor` is not available.

**Loop:** `get_llm("cheap").bind_tools(tools).astream_events(messages, version="v2")` streams tokens. On `on_chat_model_end` with `tool_calls` present, the loop executes each tool, appends `AIMessage` + `ToolMessage`(s) to the message list, and re-invokes. `full_content` accumulates monotonically across all iterations (never reset), so the persisted `ChatMessage.content` exactly matches what was streamed token-by-token. Capped at `MAX_TOOL_ROUNDS = 5`; a graceful fallback message is emitted if the cap is hit.

**Tools** (`app/agents/chat_tools.py`):
- `search_brand_knowledge(query)` — targeted pgvector cosine search via `search_knowledge()`. Complements the always-on top-3 chunks pre-loaded in the system prompt.
- `create_draft_post(content, hashtags, suggested_time, theme)` — `angle` is not a caller-facing parameter; it is hardcoded to `"Chat draft"` inside the tool to satisfy the NOT NULL DB constraint. Creates `Post(status=draft, day=0)` in a per-workspace singleton "Chat Drafts" plan.
- `trigger_plan_generation(goal)` — creates `ContentPlan(status=generating)`, fires `asyncio.create_task(run_generation(...))` with a strong reference held in the module-level `_background_tasks` set to prevent GC.

**Model:** gemini-2.5-flash. Chat fires on every user message; the cost/frequency trade-off strongly favors Flash over Pro.

---

## 11. Backend API Reference

All endpoints are prefixed with `/api`.

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Always returns 200. No auth. |

### Workspaces

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/workspaces` | `{name, autonomy_level?}` | 201 WorkspaceResponse |
| GET | `/api/workspaces` | — | `[WorkspaceResponse]` |
| GET | `/api/workspaces/{workspace_id}` | — | WorkspaceResponse |

### Brand Profile

| Method | Path | Body | Response |
|--------|------|------|----------|
| PUT | `/api/workspaces/{workspace_id}/brand-profile` | `{brand_name?, company_name?, industry?, products?, audience_segments?, goals?, tone?, voice_guidelines?, positioning?, avoid?, extra?}` | BrandProfileResponse |
| GET | `/api/workspaces/{workspace_id}/brand-profile` | — | BrandProfileResponse |
| PUT | `/api/workspaces/{workspace_id}/brand` | _(same body)_ | BrandProfileResponse _(deprecated alias)_ |
| GET | `/api/workspaces/{workspace_id}/brand` | — | BrandProfileResponse _(deprecated alias)_ |

### Content Plans

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/workspaces/{workspace_id}/plans:generate` | `{goal?}` | 202 `{plan_id}` |
| GET | `/api/workspaces/{workspace_id}/plans` | — | `[PlanResponse]` |
| GET | `/api/workspaces/{workspace_id}/plans/{plan_id}` | — | PlanResponse (with posts) |
| GET | `/api/workspaces/{workspace_id}/plans/{plan_id}/stream` | — | SSE stream (text/event-stream) |

### Posts

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/posts/{post_id}:submit` | — | PostResponse (`draft → pending_approval`) |
| POST | `/api/posts/{post_id}:approve` | — | PostResponse |
| POST | `/api/posts/{post_id}:reject` | `{reason?}` | PostResponse |
| PATCH | `/api/posts/{post_id}` | `{content?, hashtags?, suggested_time?}` | PostResponse |
| POST | `/api/posts/{post_id}:regenerate` | `{note?}` | 202 `{post_id}` |
| POST | `/api/posts/{post_id}:schedule` | `{integration_id, provider, when}` | PostResponse |

### Knowledge

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/workspaces/{workspace_id}/knowledge/documents` | multipart file upload | 202 KnowledgeDocumentResponse |
| GET | `/api/workspaces/{workspace_id}/knowledge/documents` | — | `[KnowledgeDocumentResponse]` |
| DELETE | `/api/workspaces/{workspace_id}/knowledge/documents/{doc_id}` | — | 204 |
| GET | `/api/workspaces/{workspace_id}/knowledge/search?q=` | — | `[KnowledgeChunkResponse]` |

### Chat

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/workspaces/{workspace_id}/chat/sessions` | `{title?}` | 201 ChatSessionResponse |
| GET | `/api/workspaces/{workspace_id}/chat/sessions` | — | `[ChatSessionResponse]` (ordered `updated_at` DESC) |
| GET | `/api/workspaces/{workspace_id}/chat/sessions/{session_id}` | — | ChatSessionDetailResponse (incl. messages) |
| DELETE | `/api/workspaces/{workspace_id}/chat/sessions/{session_id}` | — | 204 |
| POST | `/api/workspaces/{workspace_id}/chat/sessions/{session_id}/messages` | `{content}` | 202 `{message_id}` |
| GET | `/api/workspaces/{workspace_id}/chat/sessions/{session_id}/stream` | — | SSE stream (text/event-stream) |

> `POST .../messages` returns **HTTP 400** (not 404) if the workspace has no active brand profile (`onboarding_status != 'active'`). The request is malformed given workspace state, not a missing resource.

### Connections

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/workspaces/{workspace_id}/connections` | Returns list of Postiz social integrations |

### Admin (requires `X-Admin-Key` header)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats` | System-wide aggregate counts |
| GET | `/api/admin/workspaces` | All workspaces |
| DELETE | `/api/admin/workspaces/{workspace_id}` | Delete workspace (cascades) |
| GET | `/api/admin/plans` | All plans |
| DELETE | `/api/admin/plans/{plan_id}` | Delete plan |
| GET | `/api/admin/posts` | All posts (query param: `status`) |
| DELETE | `/api/admin/posts/{post_id}` | Delete post |
| GET | `/api/admin/logs` | Action logs (query params: `skip`, `limit`) |

### SSE Event Types

The `/stream` endpoint emits events with `data: <json>` lines. Each event has a `type` field:

| Type | Payload | Description |
|------|---------|-------------|
| `status` | `{message}` | Generic progress message |
| `strategy_done` | `{ideas: [{day, theme}]}` | Strategy agent finished |
| `post_start` | `{day, theme}` | Starting to write a post |
| `post_written` | `{day, content_preview, hashtags}` | Draft written |
| `critic_start` | `{day}` | Critic reviewing |
| `critic_revision` | `{day, issues}` | Critic requested changes |
| `post_approved` | `{day}` | Post passed critic |
| `done` | `{plan_id}` | All 7 posts complete |
| `error` | `{message}` | Generation failed |
| `ping` | — | Keepalive (emitted on 30s timeout) |

### Chat SSE Event Types

The `/chat/sessions/{id}/stream` endpoint uses the same event bus mechanism, keyed by `session_id`:

| Type | Payload | Description |
|------|---------|-------------|
| `token` | `{content}` | One streamed token chunk from the assistant |
| `tool_start` | `{tool}` | Agent invoked a tool (e.g. `search_brand_knowledge`) |
| `tool_end` | `{tool}` | Tool call returned |
| `done` | — | Agent finished; stream closed |
| `error` | `{message}` | Agent failed |
| `ping` | — | Keepalive |

---

## 12. Frontend Pages & Components

### Routing (App.tsx)

```
/                                          → WorkspacesPage
/workspaces/:wsId                          → WorkspacePage
/workspaces/:wsId/plans/:planId            → PlanPage
/workspaces/:wsId/brand-brain              → BrandBrainPage
/workspaces/:wsId/chat                     → ChatPage (session list / new session)
/workspaces/:wsId/chat/:sessionId          → ChatPage (active session)
/admin                                     → AdminDashboardPage
/admin/workspaces                          → AdminWorkspacesPage
/admin/plans                               → AdminPlansPage
/admin/posts                               → AdminPostsPage
/admin/logs                                → AdminLogsPage
```

### API Client (api.ts)

Single file with typed functions for every endpoint. Uses `VITE_API_URL` as base. Admin calls auto-attach `X-Admin-Key` header from `VITE_ADMIN_API_KEY`.

Throws `Error` with response body text on non-2xx responses. All callers handle errors with `try/catch`.

### Types (types.ts)

Mirrors backend Pydantic schemas exactly. Key interfaces:

```typescript
interface Post {
  id: string;
  day: number;
  theme: string;
  format: string;
  angle: string;
  content: string;
  hashtags: string[];
  suggested_time: string;
  status: PostStatus;
  postiz_post_id: string | null;
}

type PostStatus = 'draft' | 'pending_approval' | 'approved' | 'scheduled' | 'published' | 'rejected';

interface Plan {
  id: string;
  workspace_id: string;
  goal: string | null;
  status: PlanStatus;
  posts: Post[];
}
```

### OnboardingWizard (pages/OnboardingWizard.tsx)

Multi-step form that collects Phase 1 brand profile fields on first workspace setup: brand name, company name, industry, products, audience segments, goals, tone, voice guidelines, positioning, avoid list. Triggered automatically when a workspace has no active brand profile (`onboarding_status != 'active'`). On completion, sets `onboarding_status = active` via `PUT /brand-profile`.

### BrandBrainPage (pages/BrandBrainPage.tsx)

Displays the current brand profile as a structured read-only summary. Lists uploaded knowledge documents with upload (multipart POST) and delete buttons. Includes a live semantic search box that calls `GET /knowledge/search?q=` and renders matching chunks.

### ChatPage (pages/ChatPage.tsx)

Two-panel layout: session sidebar (list + "New Chat" button) and message thread. Token-streaming display: `token` events are appended to the active assistant bubble in real time; `tool_start`/`tool_end` events show an inline activity badge (e.g., "searching brand knowledge…"). When an assistant message has `metadata_.draft_post_id` set, a "Send for Approval" button appears — clicking it calls `:submit` and removes the button on success.

### PostCard (components/PostCard.tsx)

The central interactive component. Manages its own local state for edit mode, reject form, regenerate form, and loading/error per action.

**Format emoji mapping** — each post `format` gets a visual emoji prefix (e.g., "carousel" → "🎠", "reel" → "🎬").

**Day display:** `day === 0` renders as "Unscheduled" (not "Day 0"). Chat-created draft posts use `day=0` as a sentinel value.

**Edit save behavior:** If the post was in `approved` state and the user saves an edit, the status resets to `pending_approval` (enforced by backend state machine, reflected in returned post).

### ScheduleModal (components/ScheduleModal.tsx)

Fetches connections on mount. Filters out disabled integrations. Defaults datetime to tomorrow at 09:00 local time. Converts local datetime to ISO-8601 UTC before sending to API.

---

## 13. Service Layer

### generation.py — `run_generation(plan_id, workspace_id, brand_profile, goal, db)`

Background task that:
1. Fetches brand profile as dict
2. Creates event bus queue for SSE
3. Invokes `generation_graph.ainvoke()` with initial state
4. On success: bulk-inserts 7 `Post` rows + 7 `ActionLog` rows in one transaction, sets plan `status=ready`
5. On failure: sets plan `status=failed`, logs error, closes event bus

### regenerate.py — `regenerate_post(post_id, note, db)`

Background task that:
1. Loads post + brand profile
2. Calls ContentAgent directly (not via graph)
3. Calls CriticAgent on result
4. Applies `fixed_body` from critic if provided
5. Saves updated content to DB, resets status to `pending_approval`
6. Logs action

### publishing.py — `schedule_post(post_id, integration_id, provider, when, db)`

Synchronous service (called from router, not background):
1. Checks post isn't already scheduled (`AlreadyScheduledError` if so)
2. Builds final post text = content + "\n\n" + hashtags joined
3. Calls `PostizClient.schedule_post()`
4. Stores returned `postiz_post_id` on post row
5. Calls `transition(post, 'scheduled')`
6. Logs action

### post_status.py — `transition(post, new_status)`

```python
_ALLOWED = {
    PostStatus.pending_approval: {PostStatus.approved, PostStatus.rejected},
    PostStatus.approved: {PostStatus.pending_approval, PostStatus.scheduled, PostStatus.rejected},
    PostStatus.scheduled: {PostStatus.published},
}
```

Raises `InvalidTransition(current, target)` if the move isn't in `_ALLOWED[current]`.

### event_bus.py

`asyncio.Queue` per string key. Used by both generation (keyed by `plan_id`) and chat (keyed by `session_id`). Always call `exists(key)` before `create(key)`.

| Function | Purpose |
|----------|---------|
| `create(key)` | Open queue before background task |
| `emit(key, dict)` | Push event |
| `read(key, timeout=30)` | Pop; returns `{"type":"ping"}` on timeout |
| `close(key)` | None sentinel + remove |
| `exists(key)` | Guard against double-create |

### embeddings.py

Lazy singleton wrapping BAAI/bge-base-en-v1.5 via `sentence-transformers`. Runs in `asyncio.to_thread()` to avoid blocking the event loop. Dimension: 768.

- `embed_text(query)` → applies BGE query prefix → `list[float]`
- `embed_many(texts)` → no prefix (for document chunks) → `list[list[float]]`

### knowledge_ingestion.py

`ingest_document(doc_id, db)` background task: reads file from `UPLOADS_DIR`, splits into chunks, calls `embed_many`, bulk-inserts `KnowledgeChunk` rows, sets `KnowledgeDocument.status = 'indexed'`.

### knowledge_search.py

`search_knowledge(query, workspace_id, db, k=5)` — calls `embed_text(query)`, runs pgvector cosine similarity query scoped to `workspace_id`, returns `list[KnowledgeChunk]`.

### chat.py (services)

| Function | Purpose |
|----------|---------|
| `save_message(db, session_id, workspace_id, role, content, metadata=None)` | Insert `ChatMessage` |
| `get_messages(db, session_id, limit=20)` | Load recent history |
| `auto_title_session(db, session, first_message)` | Set title from first 60 chars if not yet set |
| `get_or_create_chat_draft_plan(db, workspace_id)` | Singleton "Chat Drafts" plan; has a race-condition TODO (documented in source) |

---

## 14. Postiz Integration

### What Postiz Is

Postiz is a **self-hosted social media scheduler** that manages OAuth connections to platforms (LinkedIn, X, Instagram, etc.) and handles the actual API calls to publish content at scheduled times.

Marketing Agent uses Postiz as a "publishing backend" — it never talks to LinkedIn/X directly.

### PostizClient (app/clients/postiz.py)

Base URL: `http://postiz:5000/api/public/v1` (internal Docker network)

Authentication: `Authorization: Bearer <POSTIZ_API_KEY>` header on every request.

**Key methods:**

```python
async def list_integrations() -> list[dict]
# Returns connected social accounts: {id, type, name, picture, profile, disabled}

async def schedule_post(integration_id, content, provider, scheduled_at, images=None) -> list[dict]
# Creates a scheduled post in Postiz
# Returns list of created post objects (one per integration)

async def get_posts(start_date, end_date) -> list[dict]
# Retrieve posts within a date range

async def upload_media(file_content, file_name, mime_type) -> dict
# Upload media file, returns {id, path}

async def upload_media_from_url(url) -> dict
# Upload from external URL

async def delete_post(post_id) -> None
# Remove a scheduled post
```

**Retry behavior on 429:**
```
Attempt 1: immediate
Attempt 2: wait 5s
Attempt 3: wait 10s
Attempt 4: wait 20s
→ Raises PostizRateLimitError
```

**Error classes:**
```python
PostizError          # base
PostizAuthError      # 401/403 → re-check API key
PostizNotFoundError  # 404
PostizRateLimitError # 429 after all retries
```

### Postiz Setup (one-time)

1. Start stack: `make dev-build`
2. Go to `http://localhost:5174`
3. Create an account
4. Settings → Developer → API Keys → Create
5. Copy key → add to `.env` as `POSTIZ_API_KEY`
6. Restart: `docker compose restart app`

---

## 15. Real-time Streaming (SSE + Event Bus)

### Architecture

```
Background Task (generation.py)
        │ emit(plan_id, event)
        ▼
  asyncio.Queue (event_bus.py)
  (one queue per plan_id, in-memory)
        │ read(plan_id)
        ▼
  SSE Endpoint (plans.py /stream)
        │ data: {json}\n\n
        ▼
  Browser (PlanPage.tsx)
  EventSource API
```

### SSE Endpoint Details

The `/stream` endpoint is an `EventSourceResponse` (via `sse-starlette`). It:
1. Opens the event bus queue for the plan
2. Loops: reads next event (30s timeout)
3. On timeout: yields `ping` event (keepalive)
4. On `None` sentinel: closes stream
5. On `done` or `error` event: yields, then closes

### Frontend Consumption

```typescript
// PlanPage.tsx
const es = new EventSource(`${API_URL}/api/workspaces/${wsId}/plans/${planId}/stream`);
es.onmessage = (e) => {
  const event = JSON.parse(e.data);
  setStreamLines(prev => [...prev, event]);
  if (event.type === 'done' || event.type === 'error') {
    es.close();
    // reload plan to get final post list
  }
};
```

### Chat Streaming

The same `event_bus.py` module serves chat, keyed by `session_id` instead of `plan_id`. The `run_chat_agent` background task emits `token`, `tool_start`, `tool_end`, `done`, and `error` events and calls `event_bus.close(session_id)` in its `finally` block, regardless of success or failure.

```typescript
// ChatPage.tsx
const es = new EventSource(`${API_URL}/api/workspaces/${wsId}/chat/sessions/${sid}/stream`);
es.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.type === 'token') appendToken(event.content);
  if (event.type === 'tool_start') showToolBadge(event.tool);
  if (event.type === 'tool_end') hideToolBadge(event.tool);
  if (event.type === 'done') { es.close(); refetchSession(); }
  if (event.type === 'error') { es.close(); showError(event.message); }
};
```

---

## 16. Authentication & Authorization

| Layer | Mechanism |
|-------|-----------|
| CORS | `ALLOWED_ORIGINS` env var (default: localhost:3000, localhost:8001) |
| Admin endpoints | `X-Admin-Key` header matching `ADMIN_API_KEY` in env |
| Postiz client | `Authorization: Bearer <POSTIZ_API_KEY>` on all Postiz calls |
| User endpoints | **No authentication** — any caller can create workspaces and generate content |

**Note:** The system has no user accounts, sessions, or JWT tokens. All workspace data is accessible to anyone who can reach the API. This is by design for the current phase — the system is intended for internal team use, not public multi-user SaaS.

---

## 17. Environment Variables

Full reference (see `.env.example` for template):

```env
# Application
APP_ENV=development
DEBUG=false                      # Enables /api/docs if true
ADMIN_API_KEY=<hex-32>           # openssl rand -hex 32
ALLOWED_ORIGINS=["http://localhost:3000"]

# Database
DATABASE_URL=postgresql+asyncpg://postgres:changeme@db:5432/marketing
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
POSTGRES_DB=marketing

# Google Gemini
GOOGLE_API_KEY=<your-key>
REASONING_MODEL=gemini-2.5-pro
CHEAP_MODEL=gemini-2.5-flash
MAX_TOKENS=8192

# LangSmith (optional tracing)
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=<key>
LANGSMITH_PROJECT=marketing-agent

# Postiz
POSTIZ_API_URL=http://postiz:5000        # Docker internal
POSTIZ_API_KEY=<generated-in-postiz-ui>
POSTIZ_JWT_SECRET=<hex-32>              # For Postiz container auth
DOMAIN=http://localhost:5000            # Postiz's own domain

# Social OAuth (for Postiz to connect platforms)
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
X_API_KEY=
X_API_SECRET=

# Postiz DB (separate from app DB)
POSTIZ_DB_USER=postiz_user
POSTIZ_DB_PASSWORD=postiz_pass
POSTIZ_DB_NAME=postiz

# Nginx/SSL (GCP production only)
CERTBOT_EMAIL=admin@yourdomain.com

# Frontend (Vite)
VITE_API_URL=http://localhost:8001
VITE_ADMIN_API_KEY=<same as ADMIN_API_KEY>
```

---

## 18. Database & Migrations

**Engine:** SQLAlchemy 2.0 async with `asyncpg` driver.

**Session pattern:**
```python
# database.py
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

Used via FastAPI `Depends(get_db)` in all routers.

### Alembic

Three migrations in a linear chain:

```
755ee710511d_initial_schema.py           # base — 5 tables (workspaces, brand_profiles, content_plans, posts, action_logs)
  └─► 20260702152447_brand_brain_phase1.py  # revised brand_profiles schema; adds knowledge_documents, knowledge_chunks + pgvector IVFFlat index
        └─► 20260702200000_chat_phase2.py   # adds chat_sessions, chat_messages
```

**Codebase conventions (both model and migration must follow):**
- All enum columns: `native_enum=False` → stored as VARCHAR
- All timestamp columns: `sa.String()` + `server_default=sa.text('now()')` — consistent throughout

Commands:
```bash
alembic upgrade head          # Apply all pending migrations
alembic downgrade -1          # Revert last migration
alembic revision --autogenerate -m "description"  # Generate from model changes
make migrate                  # Docker: runs upgrade head
make migrate-create           # Docker: prompts for name, auto-generates
make migrate-down             # Docker: revert one
```

---

## 19. Testing

### Framework

- **pytest** + **pytest-asyncio** (`asyncio_mode = strict`)
- **pytest-mock** for mocking
- **respx** for mocking httpx calls (Postiz client tests)
- Tests use an in-process SQLite or test Postgres (see `conftest.py`)

### Fixtures (tests/conftest.py)

```python
@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    # Fresh connection, auto-rollback after each test

@pytest_asyncio.fixture
async def test_client():
    # AsyncClient on FastAPI app, overrides get_db with test session
```

### Test Coverage

17 files, ~107 tests.

| File | What it tests |
|------|--------------|
| `test_workspace.py` | Create/get workspaces |
| `test_brand.py` | Brand profile CRUD (Phase 1 schema) |
| `test_plans.py` | Generation trigger, polling, SSE stream |
| `test_approval.py` | Full approve/reject workflow |
| `test_edit.py` | Post edit + status reset |
| `test_regenerate.py` | Regeneration background task |
| `test_publishing.py` | Schedule + Postiz integration |
| `test_post_status.py` | State machine transitions |
| `test_connections.py` | Connections list endpoint |
| `test_agents.py` | Strategy/Content/Critic agent mocking |
| `test_graph.py` | LangGraph node logic |
| `test_postiz_client.py` | PostizClient retry on 429 |
| `test_schedule_endpoint.py` | Schedule endpoint |
| `test_action_log.py` | Audit log creation |
| `test_knowledge.py` | Document upload + ingest, semantic search, delete cascade, status transitions |
| `test_chat.py` | Session CRUD, send message (202), SSE returns `text/event-stream`, tool invocations (`create_draft_post`, `trigger_plan_generation`), `:submit` endpoint, 400 on missing brand profile, session title auto-set |

> **Note:** Phase 1 and Phase 2 tests pass static analysis. Live test-suite execution against a running Postgres instance is pending (Docker Desktop was unavailable at time of writing).

### Running Tests

```bash
make test           # In Docker (matches CI)
make test-local     # Locally (needs Postgres at localhost:5432/marketing)
pytest tests/test_plans.py -v    # Single file
pytest tests/ -v -s              # All with output
```

---

## 20. Deployment

### Local (Docker Compose)

```bash
cp .env.example .env
# Fill in GOOGLE_API_KEY, POSTIZ_JWT_SECRET, etc.

make dev-build      # Build images + start all services
make logs           # Tail logs
curl http://localhost:8001/api/health  # Verify
```

Services started: `app`, `db`, `postiz`, `postiz-db`, `postiz-redis`, `frontend`

### Production (GCP + Nginx)

```bash
# First-time SSL setup
make ssl-init DOMAIN=marketing.yourdomain.com CERTBOT_EMAIL=admin@yourdomain.com

# Start with SSL layer
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
```

`docker-compose.nginx.yml` adds: Nginx reverse proxy with TLS termination + Certbot for Let's Encrypt certs.

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make dev` | Start (no rebuild) |
| `make dev-build` | Build + start |
| `make test` | Run pytest in Docker |
| `make test-local` | Run pytest locally |
| `make lint` | Ruff check |
| `make migrate` | `alembic upgrade head` |
| `make migrate-create` | New migration |
| `make migrate-down` | Revert last |
| `make ssl-init` | First-time SSL + Nginx |
| `make logs` | Docker compose logs |

---

## 21. Key Design Decisions

### 1. Async-First Throughout
Every I/O operation (DB reads/writes, HTTP calls to Postiz, LLM calls) is async. This allows the FastAPI server to handle concurrent SSE streams and background tasks without blocking.

### 2. Background Tasks, Not Queue Workers
Generation and regeneration run as `FastAPI.BackgroundTasks` — spawned after the HTTP response is returned. This keeps the stack simple (no Celery, no Redis workers for our app). Trade-off: if the app restarts mid-generation, the task is lost.

### 3. LangGraph for Multi-Step AI Workflow
LangGraph provides conditional routing (critic approval gate), state management, and checkpointing interfaces. The strategy→content→critic→advance loop would be messy to implement manually.

### 4. Critic Uses a Cheaper Model
The critic's job (review, flag issues) requires less reasoning than writing. Using `gemini-2.5-flash` instead of `gemini-2.5-pro` for the critic cuts per-plan LLM cost significantly.

### 5. Structured Outputs via `with_structured_output`
All agents use LangChain's `with_structured_output(Schema, method="json_schema")`. This means the LLM is forced to return valid Pydantic objects — no manual JSON parsing, no regex extraction.

### 6. Event Bus for SSE (Not WebSockets)
SSE (Server-Sent Events) is unidirectional: server pushes to client. This is sufficient for progress streaming — the client never needs to send mid-stream messages. SSE is simpler to implement and proxy than WebSockets.

### 7. Single State Machine Source of Truth
`transition()` in `post_status.py` is the only place that changes post status. No router or service mutates `post.status` directly. This prevents invalid state transitions from sneaking in.

### 8. Postiz as Publishing Backend
Rather than implementing OAuth for LinkedIn/X/Instagram and handling platform-specific APIs, the system delegates all of that to Postiz. Marketing Agent only needs to implement one integration (Postiz's REST API) to support publishing to any platform Postiz supports.

### 9. Human-in-the-Loop as a Hard Constraint
The `pending_approval` status exists specifically to prevent bypass. A post cannot go from `draft` or `pending_approval` directly to `scheduled`. The state machine enforces the `approved` gate.

### 10. Audit Log for Everything
Every significant action is written to `action_logs` with actor, action name, payload, and result. This provides a full history for debugging and compliance without needing to instrument each feature separately.

---

## 22. Known Limitations & Future Work

### Phase Status

| Phase | Status |
|-------|--------|
| Phase 1 — Brand Brain (knowledge RAG, OnboardingWizard, BrandBrainPage) | Code complete. **Live verification pending** (Docker, migration run, full test suite, runtime round-trips). |
| Phase 2 — Chat (conversational agent, SSE streaming, 3 tools, ChatPage) | Code complete. **Live verification pending** (same blockers as Phase 1). |

### Current Limitations

| Issue | Details |
|-------|---------|
| No user authentication | Any caller can access workspace data. Intended for internal use only. |
| In-memory checkpointing | `MemorySaver` loses LangGraph state on restart. Mid-generation crash = lost plan. Phase 3 fixes this. |
| Background task fragility | FastAPI BackgroundTasks are fire-and-forget. No retry on crash. |
| Chat: no cross-session memory | Each chat session is independent. The agent has no memory of prior sessions. |
| No analytics | Published post performance is not tracked. Phase 4a/4b addresses this. |
| Single plan per request | Each "Generate" call produces one 7-day plan. No incremental updates or plan merging. |
| No image generation | Posts are text + hashtags only. No AI-generated images attached. Phase 6 addresses this. |

### Roadmap

**Phase 3 — Durable Generation State**
Replace `MemorySaver` with a Postgres checkpointer in `app/agents/graph.py`. LangGraph plan generation survives app restarts; durable human-in-the-loop interrupts become possible. Requires a new Alembic migration for LangGraph checkpoint tables.
*Complete when:* app restart mid-generation leaves the plan recoverable (status stays `generating`, picks back up).

**Phase 3.5 — Chat Agent Expansion**
Four new tools added to the existing chat agent. Independent completion criteria from Phase 3 (different files, different verification path):
- `draft_copy` — ad hoc copywriting returned inline; no DB write; distinct from `create_draft_post` which persists
- `critic_review` — standalone `@tool` wrapper around `CriticAgent`; accepts any text, returns `{approved, issues, fixed_body}`; not limited to planned posts
- `web_search` — general research via Tavily or equivalent; brand context auto-injected
- `schedule_post` — wraps the existing `:schedule` endpoint as an agent-callable tool
*Complete when:* each tool is invokable from live chat, returns correct output, and has a test case.

**Phase 4a — Analytics Infrastructure (GA4)**
Build the analytics ingestion skeleton: OAuth 2.0 read-only flow, encrypted token storage, scheduled background job. Validate with Google Analytics 4 (`runReport` API — sessions, pageviews, conversions). This phase proves the generic plumbing (OAuth flow, token encryption, scheduler). It does **not** prove the ad-platform-specific interface (`list_campaigns`, `get_performance`); that is first designed in Phase 4b.
*Complete when:* GA4 property metrics sync on schedule and are queryable.

**Phase 4b — First Ad Platform Integration**
Design **and** validate the `AdPlatformAdapter` interface (`list_campaigns(account_id)`, `get_performance(campaign_id, date_range)` → spend/impressions/clicks/CTR) for the first time. Phase 4a proved the generic plumbing; Phase 4b proves this domain-specific interface. Phases 4c–4f then implement against the pattern Phase 4b establishes — not against an assumption.

The `get_ad_performance` callable in Phase 4b is a single-platform stub — it is not a generalized multi-platform implementation. Phases 4c–4f refactor the stub into the full `AdPlatformAdapter` pattern as each new platform is added.

*Platform choice:* Google Ads is the recommended starting point — a Test Developer Token is immediately available without review, enabling development and testing before production credentials are approved. LinkedIn should be avoided as the first platform: Marketing Developer Platform (MDP) partner applications are not self-serve and have documented multi-week review timelines. The specific platform order is a product decision; finalize it when Phase 4b is scoped, not at roadmap level.
*Complete when:* one ad account connected, campaign metrics sync on schedule, chat agent `get_ad_performance` stub returns live data from that one platform.

**Phase 4c–4f — Remaining Ad Platforms**
Apply the `AdPlatformAdapter` pattern from Phase 4b to up to four additional platforms (Meta, LinkedIn, TikTok, X — order TBD by team priorities and credential availability). One platform per sub-phase; each verified end-to-end before the next begins.

**Phase 5 — Per-Post Analytics**
Surface published post performance (impressions, engagement rate, CTR) inside `PostCard`. Depends on either Postiz exposing per-post metrics or direct platform read-only calls.

**Phase 6 — Image Generation**
`PostizClient.upload_media` and `upload_media_from_url` are already implemented. Wire an image generation step (Imagen or DALL-E) into the LangGraph content node.

**Phase 7 — Autonomy Level Policy**
`AutonomyLevel` enum (`supervised`, `assisted`, `autonomous`) is modeled. **`supervised` is the only intended operating mode.** The non-negotiable constraint — humans approve everything before publishing — is permanent and applies at all levels.

If `assisted` mode is ever added, it may narrow the approval surface (e.g., auto-approve critic-passed posts without requiring human action) but must never remove the `pending_approval` gate entirely. `autonomous` auto-approval — publishing without any human review — is out of scope by design and must not be implemented.
