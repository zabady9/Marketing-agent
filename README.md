# Analyst Agent

AI-powered market intelligence assistant. Ask questions in natural language; a team of specialist agents researches the market, surfaces verifiable data, and synthesizes structured findings — SWOT, PESTEL, feasibility studies, competitive maps.

Built on FastAPI + PostgreSQL + LangGraph (Gemini). No content publishing. No social media scheduling. Pure analysis.

## Architecture

```
User question
    ↓
Intent classifier (18 classes)
    ↓
Meeting room: Data Scout · Quant Analyst · Insights Director · Domain Specialist
    ↓
Lead Analyst synthesis (+ optional formal report via consulting engine)
    ↓
Visual output (charts, tables, metric cards) + cited sources
```

## Quick Start (local)

```bash
cp .env.example .env
# Fill in: GOOGLE_API_KEY, TAVILY_API_KEY, ADMIN_API_KEY
make dev-build

# Health check
curl http://localhost:8001/api/health
```

**Service ports:**

| Service | Port | Purpose |
|---|---|---|
| FastAPI app | 8001 | API (host 8001 → container 8000) |
| PostgreSQL | 5432 | App database (pgvector) |
| Frontend | 3000 | React SPA |

## Key capabilities

- **Competitive analysis** — market position, competitor benchmarking, gap identification
- **Market research** — size, segments, growth rates, industry trends
- **Formal reports** — SWOT, PESTEL, feasibility studies (structured, cited)
- **Subject knowledge base** — upload PDFs/docs; agents search them during analysis
- **Visual output** — auto-generated charts, tables, and metric cards from real data

## Development

```bash
# Local dev (Postgres at localhost:5432/analyst)
DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/analyst \
  uvicorn app.main:app --reload --port 8000

# Run tests
DATABASE_URL=postgresql+asyncpg://postgres:changeme@localhost:5432/analyst \
  python -m pytest tests/ -v

# Docker
make dev-build
```

## Tech stack

**Backend:** FastAPI · SQLAlchemy 2.0 async · PostgreSQL 16 + pgvector · LangGraph · LangChain · Gemini (2.5 Pro / Flash) · sentence-transformers (BAAI/bge-base-en-v1.5) · Tavily  
**Frontend:** React 18 · TypeScript · Vite · Tailwind CSS · Recharts
