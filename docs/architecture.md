# Architecture Overview

> **This document describes the target architecture. Not all components exist yet — see the phase markers.**

## System Context

NexOps is a local incident-response workbench. It accepts incident reports, gathers evidence from a simulated service (ShopAPI), reasons over evidence using a LangGraph workflow, proposes constrained remediation, and waits for human approval before applying any simulated change.

```
Browser (React dashboard)
        │ HTTP + SSE
        ▼
FastAPI ─────── PostgreSQL
   │            (domain data + graph checkpoints)
   │
   ├── LangGraph workflow
   │      ├── triage
   │      ├── parallel evidence (logs / metrics / traces / changes)
   │      ├── synthesis + bounded sufficiency loop
   │      ├── recommendation + human approval interrupt
   │      └── sandbox action + verification
   │
   └── ShopAPI (simulated service + telemetry)
```

## Key Boundaries

| Boundary | Responsibility |
|---|---|
| `app/api/` | HTTP routers, request/response schemas, CORS |
| `app/core/` | Settings, logging, error handling, auth boundary |
| `app/db/` | Engine, sessions, models, repositories |
| `app/shopapi/` | Simulated commerce API, faults, telemetry |
| `app/incidents/` | Incident lifecycle, simulator integration |
| `app/graph/` | LangGraph state, nodes, edges, tools, subgraphs |
| `app/remediation/` | Action catalog, policy, sandbox executor, verification |
| `frontend/` | React dashboard, API client, typed UI components |

## Design Decisions

See [docs/decisions/](decisions/) for Architecture Decision Records (ADRs).
