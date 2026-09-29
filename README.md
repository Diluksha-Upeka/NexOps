# NexOps — Agentic Incident Response System

> A local incident-response workbench that investigates simulated service incidents using a LangGraph workflow with human-in-the-loop approval.

⚠️ **This is a portfolio simulation project.** ShopAPI, telemetry data, incidents, and remediation actions are all local simulations. Nothing connects to or repairs a real production environment.

## What It Does

1. **Simulated Service (ShopAPI)** — A fictional commerce API with deterministic endpoints, configurable fault modes, and instrumented requests.
2. **Incident Investigation** — A bounded LangGraph workflow that gathers evidence from logs, metrics, traces, and change history in parallel.
3. **Human Approval** — Every remediation proposal requires explicit human approval before execution.
4. **Sandbox Remediation** — Approved actions only affect the local simulator configuration via an allowlisted action catalog.

## Quick Start

### Prerequisites

- Docker Desktop with Compose v2
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 22 LTS + npm
- No GPU required • No API key required (fake/deterministic mode)

### Setup

```powershell
# 1. Configure environment
cp .env.example .env

# 2. Start PostgreSQL
docker compose up -d postgres

# 3. Install Python dependencies
uv sync --all-groups

# 4. Run database migrations
uv run alembic upgrade head

# 5. Start the API server
uv run uvicorn app.main:app --reload

# 6. Start the frontend (in a new terminal)
cd frontend
npm ci
npm run dev
```

- **API docs:** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/api/v1/health
- **Frontend:** http://localhost:5173

## Project Structure

```
├── app/                    # Python backend
│   ├── main.py             # FastAPI entry point
│   ├── api/                # HTTP routers and schemas
│   ├── core/               # Settings, logging, shared utilities
│   ├── db/                 # Database engine, sessions, models
│   ├── shopapi/            # Simulated service (Phase 1+)
│   ├── incidents/          # Incident lifecycle (Phase 1+)
│   ├── graph/              # LangGraph workflow (Phase 3+)
│   └── remediation/        # Sandbox executor (Phase 6+)
├── frontend/               # React + TypeScript dashboard
├── migrations/             # Alembic database migrations
├── tests/                  # pytest test suite
├── docs/                   # Architecture docs and ADRs
├── compose.yaml            # Docker Compose (PostgreSQL)
└── BUILD.md                # Full build specification
```

## Development

See [docs/development.md](docs/development.md) for the full development guide.

| Command | Purpose |
|---|---|
| `uv run pytest` | Run tests |
| `uv run ruff check . && uv run ruff format .` | Lint and format |
| `uv run mypy app/` | Type check |
| `docker compose down` | Stop services |

## Architecture

See [docs/architecture.md](docs/architecture.md) and [docs/decisions/](docs/decisions/) for design rationale.

## License

This is a portfolio/learning project. See BUILD.md for the full specification.
