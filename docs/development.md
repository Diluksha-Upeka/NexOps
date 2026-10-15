# Development Guide

## Prerequisites

- **Git** — version control
- **Docker Desktop** with Compose v2 — runs PostgreSQL
- **Python 3.12** — backend runtime
- **uv** (current stable) — Python package/dependency manager
- **Node.js 22 LTS** with npm — frontend tooling
- **An editor** (VS Code recommended)

An LLM API key is **optional**. Without one, the system uses a deterministic fake model.

## Quick Start

### 1. Clone and configure

```powershell
git clone <repo-url>
cd NexOps
cp .env.example .env   # edit .env if needed
```

### 2. Start PostgreSQL

```powershell
docker compose up -d postgres
```

Verify health:
```powershell
docker compose ps
# postgres should show "healthy"
```

### 3. Install Python dependencies

```powershell
uv sync --all-groups
```

### 4. Run database migrations

```powershell
uv run alembic upgrade head
```

### 5. Start the API server

```powershell
uv run uvicorn app.main:app --reload
```

API docs available at: http://127.0.0.1:8000/docs  
Health check: http://127.0.0.1:8000/api/v1/health

### 6. Start the frontend

```powershell
cd frontend
npm ci
npm run dev
```

Frontend available at: http://localhost:5173

## Investigation approval flow

`POST /api/v1/incidents/{id}/investigations` runs the bounded graph against
the durable PostgreSQL checkpointer. When the graph reaches a remediation
proposal it pauses before any mutation and creates an approval record.
`GET /api/v1/runs/{id}` returns the run, cited evidence, and current approval.
Submit `approved`, `rejected`, or `request_more_evidence` to
`POST /api/v1/runs/{id}/approval` with an idempotency key.

Progress is replayable over `GET /api/v1/runs/{id}/events`. Pass
`last_event_id` when reconnecting to receive only events after the last
sequence number; events are persisted rather than held only in browser memory.

## Common Commands

| Task | Command |
|---|---|
| Start database | `docker compose up -d postgres` |
| Stop database | `docker compose down` |
| Install Python deps | `uv sync --all-groups` |
| Run migrations | `uv run alembic upgrade head` |
| Start API (dev) | `uv run uvicorn app.main:app --reload` |
| Run tests | `uv run pytest` |
| Lint/format | `uv run ruff check . && uv run ruff format .` |
| Type check | `uv run mypy app/` |
| Frontend dev | `cd frontend && npm run dev` |
| Frontend lint | `cd frontend && npm run lint` |

## Environment Variables

See [`.env.example`](../.env.example) for all available configuration. Key variables:

- `LLM_PROVIDER=fake` — runs without an API key (deterministic mode)
- `DATABASE_URL` — PostgreSQL connection string
- `SIMULATOR_ENABLED=true` — enables fault simulator routes

## Resource Usage

The MVP targets **2–4 GB RAM** for app + services (excluding browser/OS). PostgreSQL has a 256 MB memory limit in Compose.
