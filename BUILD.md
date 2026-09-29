# Agentic Incident Response System — Build Specification

> **Purpose:** This document is the product specification, architecture guide, and staged implementation plan for a portfolio project that demonstrates meaningful LangGraph engineering. It is intentionally honest about its boundaries: ShopAPI, its telemetry, incidents, and remediation targets are local simulations. Nothing here connects to or repairs a real production environment.

## 1. Product vision

Build a local incident-response workbench that accepts an incident report, gathers evidence from a simulated service, reasons over that evidence with an explicit LangGraph workflow, proposes a constrained remediation, and waits for a human decision before applying any simulated change. The application should make the workflow inspectable: users can see what was investigated, which tools ran, what evidence supports the diagnosis, why the graph routed as it did, and what changed after approval.

The learning objective is to master LangGraph concepts by using them where they matter: typed state, node boundaries, tool calls, parallel branches, conditional routing, bounded loops, checkpointed execution, interrupts, resumability, streaming, and evaluation. The LLM is one component in a deterministic, observable backend system—not the whole product.

### Goals

- Provide a runnable local end-to-end demo with seeded incidents and reproducible failure scenarios.
- Build an explicit, testable LangGraph workflow whose state and transitions are inspectable.
- Collect independent log, metric, trace, and change-history evidence concurrently.
- Separate observations, hypotheses, verified findings, and recommendations.
- Use human approval and an allowlisted sandbox before any remediation action.
- Teach backend fundamentals: APIs, schemas, persistence, migrations, testing, observability, and security.
- Work comfortably on a 16 GB RAM, i3-class laptop without a GPU.
- Make evaluation repeatable without depending on an LLM for every test.

### Non-goals

- Real production monitoring, cloud credentials, live incident response, or autonomous production changes.
- Kubernetes, service meshes, a fleet of microservices, or a large distributed platform in the initial project.
- Training or hosting a large language model locally.
- Claiming that generated telemetry is equivalent to real Prometheus, OpenTelemetry, or production logs.
- Unbounded agent loops, arbitrary shell execution, arbitrary SQL, or an agent that can invent and execute fixes.
- Multi-tenant enterprise RBAC, compliance certification, or high availability in the MVP.

## 2. Product boundaries and terminology

**ShopAPI** is a small locally running fictional commerce API. It has deterministic endpoints, a small PostgreSQL database, configurable fault modes, and instrumented requests. **Incident simulator** starts known fault scenarios and creates an incident record. **Investigation** is a bounded graph run that queries read-only evidence sources. **Remediation** is an allowlisted, reversible change to simulator configuration (for example, disabling an injected latency fault); it does not modify a real service.

Use “simulated” in the UI and documentation anywhere a reader could otherwise mistake demo data for production evidence. The LLM may summarize evidence and produce structured hypotheses, but code validates tool arguments, evidence references, confidence bounds, and proposed action types.

## 3. Recommended stack

Pin exact versions in lock files when starting implementation. The version families below are a compatibility target, not a claim that these are the newest releases. Before setup, select mutually compatible current patch releases and record them in `docs/decisions/`.

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.12.x | Broad library support, typed backend code, good LangGraph ecosystem. |
| Package/dependency management | `uv` (current stable), `pyproject.toml` + committed `uv.lock` | Fast reproducible installs and one project environment. |
| API | FastAPI (current stable, Pydantic v2) + Uvicorn | Typed HTTP API, async support, OpenAPI docs, SSE-friendly streaming. |
| Agent workflow | LangGraph 1.x-compatible release and matching LangChain core packages | Explicit graph state, routing, persistence, interrupts, streaming, and subgraphs. Pin compatible versions together. |
| LLM interface | LangChain chat model integration for one provider, configured by environment | Keep provider choice replaceable. Start with a hosted low-cost model; support a deterministic fake model for tests. |
| Database | PostgreSQL 16.x container; SQLAlchemy 2.x async or psycopg 3; Alembic | Familiar relational persistence and migrations. Keep the graph checkpoint store separate from domain tables. |
| Frontend | Node.js 22 LTS, React 19, TypeScript 5.x, Vite 6/7-compatible release | Lightweight dashboard, typed API boundary, fast local development. |
| UI/data | React Router, TanStack Query, a small chart library such as Recharts | Keep client state focused; server remains source of truth. |
| Tests | pytest, pytest-asyncio, HTTPX, React Testing Library, Vitest | Unit, API, graph, and UI behavior. |
| Quality | Ruff, mypy or Pyright, ESLint, Prettier | Consistent formatting and useful static checks. |
| Local services | Docker Compose v2 | Start PostgreSQL and later telemetry services with one command. |
| Metrics/visualization (later) | Prometheus 2.x and Grafana 11.x-compatible images | Teach metric scraping and dashboards after the core workflow works. |
| Tracing (later) | OpenTelemetry Python SDK/API + OTLP; Jaeger all-in-one or an OTLP-capable local collector | Teach spans and cross-service correlation without making tracing a prerequisite for MVP. |

Use supported patch releases and image tags pinned to explicit versions (prefer digest pinning for a published reproducibility pass). Avoid `latest` tags in the committed Compose file. LangGraph and provider APIs evolve; isolate provider configuration, keep lock files committed, and add a small compatibility smoke test when upgrading.

### Hardware-conscious operating modes

- **MVP baseline:** API, frontend dev server, one PostgreSQL container, and a remote model API. Target roughly 2–4 GB RAM for the app/services combined, excluding browser and OS. Keep database volume small and seed only a few thousand telemetry rows.
- **No-key mode:** fake/deterministic model adapter returns scripted structured outputs. All graph, UI, persistence, and simulator flows work without network access or model credentials.
- **Optional local model:** only as a later experiment. A quantized small model via a local runtime may be slow on an i3 CPU and compete for memory. It is not required and should not be part of the default Compose stack.
- Start one worker/process in development. Limit PostgreSQL memory and connection pools; avoid multiple model calls per node when a deterministic rule can answer the question.
- Run the telemetry stack only in the observability phase. Do not run PostgreSQL, Prometheus, Grafana, tracing backend, and a local LLM together by default.

## 4. Prerequisites and local setup

Install Git, Docker Desktop with Compose v2, Python 3.12, `uv`, Node.js 22 LTS with npm, and an editor. An LLM API key is optional; without it use the fake model. Allow several GB of disk for images and database data. No GPU or Kubernetes is needed.

Suggested initial workflow (adjust script names to match the implemented repository):

```text
docker compose up -d postgres
uv sync --all-groups
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev
```

Open the frontend URL printed by Vite and the API docs at `/docs`. Later, use `docker compose --profile observability up -d` to start optional metrics and tracing services. Provide Windows PowerShell equivalents in `docs/development.md` once scripts are added; keep commands platform-neutral where practical.

## 5. System architecture

```text
Browser (React dashboard)
        │ HTTP + SSE
        ▼
FastAPI ─────── PostgreSQL domain data
   │            incidents, runs, approvals, audit, simulator config
   │
   ├── LangGraph workflow ─── checkpointer (PostgreSQL in persistent phase)
   │      ├── triage
   │      ├── parallel evidence subgraphs: logs / metrics / traces / changes
   │      ├── evidence synthesis and bounded sufficiency loop
   │      ├── recommendation and human approval interrupt
   │      └── allowlisted sandbox action + verification
   │
   └── ShopAPI + telemetry store (same app initially; separate process later)
          ├── deterministic commerce endpoints
          ├── structured logs
          ├── request/latency/error metrics
          └── trace spans / simulated dependency calls

Optional later: Prometheus scrapes metrics; Grafana displays dashboards;
OTel collector/Jaeger receives spans.
```

Start as a modular monolith: one Python repository and one Compose database. Keep package boundaries clear so ShopAPI or the graph worker can be split later if there is a learning reason. Do not create microservices just to make the diagram look distributed.

### Repository structure target

```text
.
├── BUILD.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── compose.yaml
├── alembic.ini
├── migrations/
├── app/
│   ├── main.py                 # FastAPI assembly
│   ├── api/                    # routers, request/response schemas
│   ├── core/                   # settings, logging, errors, auth boundary
│   ├── db/                     # engine, session, models, repositories
│   ├── shopapi/                # simulated service, faults, telemetry
│   ├── incidents/              # lifecycle and simulator
│   ├── graph/                  # state, nodes, edges, tools, subgraphs
│   ├── remediation/            # policy, sandbox executor, verification
│   └── evals/                  # fixtures, runner, scoring
├── frontend/
│   ├── package.json
│   └── src/                    # routes, components, API client, types
├── tests/
│   ├── unit/                   # pure logic and tools
│   ├── integration/            # DB/API/graph persistence
│   ├── e2e/                    # key user journeys
│   └── fixtures/
├── evals/                      # versioned scenario definitions and expected facts
├── dashboards/                 # provisioned Grafana JSON, later phase
└── docs/
    ├── development.md
    ├── architecture.md
    └── decisions/
```

Keep secrets, local database files, generated reports, and provider traces out of Git. Use typed request/response models and domain services; avoid putting business logic in route handlers or React components.

## 6. Compose services by phase

### Initial `postgres`

- PostgreSQL 16.x, local-only published port (default `5432`, configurable), named volume, health check, and non-superuser app database/user.
- Set reasonable container memory/resource limits where supported. Never expose the database to a public interface.
- API and frontend initially run on the host for fast reload. The app connects to `localhost` on the published port.

### Optional `observability` profile (later)

- Prometheus: scrape the API's `/metrics`; local-only port, short retention (for example, 3 days), small storage limit.
- Grafana: provision a local data source and dashboard; no default public exposure.
- OTel collector and/or Jaeger: receive local OTLP traces. Add only once spans are emitted by both API and ShopAPI.

Do not add Redis, Kafka, Kubernetes, or a separate vector database to the MVP. If a durable background queue later becomes necessary, document the reason and compare PostgreSQL-backed jobs with a broker before adding infrastructure.

## 7. ShopAPI: simulated production service

ShopAPI models a small fictional store with `GET /health`, `GET /products`, `GET /products/{id}`, `POST /orders`, and `GET /orders/{id}`. Seed a handful of products and keep order creation deterministic and idempotent when given an idempotency key. All endpoints should have predictable schemas, validation, and useful status codes.

Instrument every request with a request ID, route template, method, status, and duration. Emit structured JSON logs; record metric samples with route labels that avoid unbounded cardinality; add trace spans around database access and simulated dependencies. Never log credentials, full payment data, or unrestricted request bodies.

ShopAPI is a teaching simulation. It can demonstrate latency, errors, and dependency failures, but not realistic traffic volume, distributed consistency, noisy-neighbor effects, or actual production behavior. Label generated telemetry accordingly in UI and docs.

## 8. PostgreSQL domain model

Use Alembic migrations and UTC timestamps. Suggested tables (names are guidance):

| Table | Core fields and purpose |
|---|---|
| `incidents` | `id`, `title`, `description`, `service`, `severity`, `status`, `source` (manual/simulator), `scenario_key`, `started_at`, `created_at`, `resolved_at`, `version`; domain lifecycle. |
| `investigation_runs` | `id`, `incident_id`, `thread_id`, `status`, `started_at`, `finished_at`, `model_name`, `prompt_version`, `graph_version`, `error_code`; one graph execution. |
| `evidence_items` | `id`, `run_id`, `source_type`, `observed_at`, `summary`, `payload_json`, `source_ref`, `confidence`, `simulated`; immutable observations with provenance. |
| `hypotheses` | `id`, `run_id`, `statement`, `cause_key`, `confidence`, `supporting_evidence_ids`, `contradicting_evidence_ids`, `status`; explicit hypotheses and updates. |
| `recommendations` | `id`, `run_id`, `action_type`, `parameters_json`, `rationale`, `risk`, `requires_approval`, `status`; validated proposal. |
| `approvals` | `id`, `recommendation_id`, `decision`, `actor`, `comment`, `created_at`; human decision history. |
| `remediation_actions` | `id`, `incident_id`, `recommendation_id`, `action_type`, `parameters_json`, `status`, `started_at`, `finished_at`, `result_json`; sandbox execution record. |
| `audit_events` | `id`, `actor`, `event_type`, `resource_type`, `resource_id`, `details_json`, `created_at`; append-only application audit events. |
| `telemetry_events` (MVP simulator) | `id`, `scenario_id`, `kind`, `timestamp`, `service`, `attributes_json`, optional `trace_id`; small queryable demo samples. |
| `simulator_state` | singleton/config rows with active fault modes, parameters, expiry, and revision; authoritative simulated service configuration. |

Add indexes for incident status/time, run-by-incident, evidence-by-run/type/time, and telemetry-by-service/time/kind. Use foreign keys and deletion policy deliberately. Store arbitrary evidence payloads as bounded JSONB, but keep fields used for filtering/querying normalized. LangGraph checkpoints have their own tables managed by the selected checkpointer; do not hand-edit them or treat them as domain records. Retain graph checkpoints according to a documented local retention policy.

## 9. Fault injection and incident simulator

Provide a UI/API to start, inspect, and stop named scenarios. Each scenario has a stable key, description, expected root cause, expected evidence, allowed safe fix, severity, and cleanup behavior. Keep expected answers in evaluation fixtures, separate from the evidence returned to the graph.

Initial scenario set:

1. **Database latency:** add a controlled delay to ShopAPI's DB repository; latency rises while errors remain low.
2. **Database connection exhaustion:** lower the simulated pool capacity or make a dependency return a pool-exhausted signal; request failures rise.
3. **Bad release:** a simulated release changes a query/config revision, producing slow product listing; change history points to the release.
4. **Dependency timeout:** a fake shipping or payment dependency times out; traces show the dependency span as the slow/error segment.
5. **Elevated 5xx:** deterministic sampling returns errors for a bounded interval; logs and error-rate metrics correlate.

Use seeded randomness or fixed sequences so tests reproduce the same observations. Faults must have TTL/automatic cleanup, clear manual stop, and safety caps on delay/error rates. Simulator endpoints are disabled or protected outside development. Store a `scenario_id` on generated observations; do not mix simulator truth labels into evidence presented to the model.

## 10. Telemetry design and progressive observability

### Phase A: application-level telemetry

Start with structured JSON logs and a small telemetry repository in PostgreSQL. Implement bounded query tools over time windows and service/route filters. Metrics include request count, error count, latency samples or histogram buckets, and dependency errors. Trace-like records can initially be spans stored as linked event rows with trace/span IDs.

### Phase B: Prometheus and Grafana

Expose `/metrics` using Prometheus client instrumentation. Use stable labels (`service`, route template, method, status class); never label by request ID, user ID, raw URL, or exception message. Add Grafana panels for request rate, error rate, latency percentiles (or histogram quantiles), and active scenario/fault state. Document that local short-window metrics are generated by a demo workload.

### Phase C: OpenTelemetry

Add OTel instrumentation for FastAPI, database calls, and graph run boundaries; propagate trace context from API request through ShopAPI evidence calls. Export OTLP to the optional local collector/Jaeger. Persist trace IDs in evidence and display links/details in the incident UI. Keep sampling and payload capture conservative; do not export secrets or user content by default.

Introduce each layer only after the prior layer answers a practical question. The graph's evidence tools should use stable interfaces so the underlying telemetry source can change from PostgreSQL simulator data to Prometheus/OTel queries later.

## 11. LangGraph design

### Typed state

Define a `TypedDict` or Pydantic-backed state with explicit reducers for collections that receive parallel updates. Example fields:

```text
incident_id: str
run_id: str
thread_id: str
incident: IncidentContext
plan: list[InvestigationTask]
evidence: Annotated[list[Evidence], add]       # reducer prevents parallel overwrite
hypotheses: list[Hypothesis]
confidence: float
missing_evidence: list[str]
investigation_round: int
max_investigation_rounds: int
recommendation: Recommendation | None
approval: ApprovalDecision | None
action_result: ActionResult | None
errors: Annotated[list[GraphError], add]
status: Literal[...]
```

Store only data needed to make the workflow resumable and explainable. Put large raw telemetry out of graph state and store bounded references/summaries. Validate all model-produced structured data at node boundaries. Treat evidence as immutable facts with source and timestamp.

### Nodes and responsibilities

1. **`load_incident`** — load and validate incident context; initialize IDs, limits, status, and safe defaults.
2. **`triage`** — classify service, severity, symptoms, and likely investigation areas. Use rules first and optionally an LLM for structured classification. No remediation authority.
3. **`plan_investigation`** — select applicable evidence branches from the incident and prior findings; cap task count.
4. **Parallel evidence subgraphs:**
   - **logs investigator:** query a bounded time range, aggregate matching structured log records, return cited evidence.
   - **metrics investigator:** calculate baselines/current windows, error rate, latency change, and anomalies with deterministic code.
   - **traces investigator:** identify slow/error spans and dependency boundaries from simulated or OTel data.
   - **change investigator:** query simulated deployment/config history.
   Each branch returns typed evidence and a branch status; branch failure becomes a structured error and must not erase successful siblings.
5. **`synthesize_evidence`** — deduplicate, preserve source references, and build a concise evidence packet.
6. **`analyze_root_cause`** — compare candidate causes against evidence. The LLM can explain/rank candidates, but numeric confidence is calibrated by a documented rule or evaluation; require supporting evidence IDs and record contradictions.
7. **`route_sufficiency`** — deterministic conditional edge: enough evidence and confidence → recommendation; otherwise another bounded investigation round if budget remains; otherwise produce an “insufficient evidence” report. Never loop indefinitely.
8. **`refine_plan`** — identify one or two concrete missing signals for the next round; prevent repeating identical queries. Increment round counter.
9. **`propose_remediation`** — map an approved cause key to a fixed action catalog; include expected effect, risk, rollback, and verification. Reject unknown actions and unsupported parameters.
10. **`await_human_approval`** — issue a LangGraph interrupt with recommendation and evidence summary. Persist at a stable thread/checkpoint ID; resume only from an authenticated API decision.
11. **`execute_sandbox_action`** — check approval, policy, action allowlist, argument schema, incident status, and idempotency; apply only to simulator state.
12. **`verify_remediation`** — collect post-action measurements and compare with baseline/threshold; mark resolved, mitigated, or still active. Verification failure does not silently claim success.
13. **`finalize`** — persist summary/status and release client-visible run events.

### Edges, routing, parallel execution, and cycles

Use explicit normal edges for the happy path and conditional edges for severity, evidence sufficiency, and approval outcome. Run independent evidence investigators with LangGraph fan-out/fan-in (or a `Send`-based map step); use an `Annotated` reducer to merge their results. Give every branch its own timeout, row/result limit, and error envelope.

The only normal cycle is `analyze_root_cause → refine_plan → evidence branches → synthesize → analyze`, bounded by `max_investigation_rounds` (default 2). If graph recursion limits are reached, catch the limit, persist a safe terminal run status, and return a partial report. Add a graph-level timeout and per-tool timeout. Retries are for transient I/O only, with small exponential backoff and jitter; do not retry validation errors or repeat potentially mutating actions automatically.

### Tools

Keep tool functions narrow, typed, read-only unless explicitly identified as a sandbox action, and independently testable. Initial tools:

- `query_logs(service, start, end, route?, severity?, limit)`
- `query_metrics(service, start, end, metric, group_by?)`
- `query_trace(trace_id | service, start, end, limit)`
- `query_changes(service, start, end, limit)`
- `get_simulator_status(service)`
- `propose_action(action_type, validated_parameters)` (catalog lookup only; not execution)

Tool validation must enforce time-window limits, allowed service names, result limits, SQL parameterization, and safe output sizes. The model never supplies SQL, raw PromQL, shell, Python, file paths, or arbitrary HTTP destinations. If actual PromQL is added later, generate it from validated templates and expose a small named-query API instead of free-form model queries.

### Checkpointing and persistence

In the first graph prototype, use an in-memory checkpointer for fast unit tests. Add the official PostgreSQL checkpointer in the persistence milestone, using its supported package and setup procedure. A stable `thread_id` should map to an investigation run or incident workflow instance; define whether reruns create a new thread or a new checkpoint namespace. Persist domain lifecycle in application tables and graph execution state in the checkpointer; keep the two responsibilities clear.

Test restart/resume against PostgreSQL: begin a run, reach an interrupt, restart the API process, submit approval, and verify continuation from the saved checkpoint. Document checkpoint retention and provide a dev reset procedure.

### Interrupts and human review

The graph must stop before any simulated mutation. `interrupt()` displays the exact action, scope, parameters, evidence, risk, expected outcome, and rollback. The UI offers approve, reject, and optionally request-more-investigation. Approval/rejection is recorded in `approvals`; the API validates actor and run state, then resumes using the matching thread ID and a structured `Command(resume=...)` value. Rejection routes to a safe final report. “Request more evidence” routes to a bounded investigation round if budget remains. Duplicate submissions are idempotent; stale or cross-incident decisions are rejected.

For a local portfolio demo, authentication can be a development-only single-user identity. Still keep an authorization boundary in the API so real identity can replace it later. Never trust an actor name sent unchecked by the browser.

### Streaming and subgraphs

Expose run lifecycle and graph progress over SSE (or WebSocket only if bidirectional interaction proves necessary). Send typed events such as `run_started`, `node_started`, `evidence_added`, `hypothesis_updated`, `approval_required`, `action_completed`, and `run_finished`. Include run ID, sequence number, timestamp, and safe payload. Do not stream hidden chain-of-thought; stream tool activity, cited evidence, concise status, and final rationale.

Use evidence investigators as subgraphs with a stable input/output contract. This teaches composability and allows branch-level testing. Add deployment/change analysis as a second subgraph when useful. Do not create subgraphs that merely add indirection.

### Error handling

Represent expected tool failures as typed result objects with `ok`, `error_code`, `retryable`, and bounded message. Preserve partial evidence when one branch fails. Unexpected node exceptions are logged with run/node IDs, converted to a safe user-facing error, and leave the run in a resumable or clearly terminal state. Do not place secrets or raw provider exception payloads in events. Distinguish provider rate limits, timeouts, malformed structured output, tool errors, database outage, graph limit, user rejection, and policy denial. Use a deterministic fallback summary when the LLM is unavailable.

## 12. Incident lifecycle

Use an explicit lifecycle, for example:

```text
OPEN → INVESTIGATING → AWAITING_APPROVAL → REMEDIATING → VERIFYING
  └──────────────────────────────────────────────────────────→ RESOLVED
                                     ├→ MITIGATED
                                     ├→ REJECTED / OPEN
                                     └→ FAILED / OPEN
```

Model `status` transitions in a domain service with allowed-transition checks, timestamps, and audit events. Keep investigation-run status distinct from incident status; rerunning an investigation must not erase prior evidence or decisions. A human can close/reopen an incident with an audited action. Only verification may mark a simulated remediation as resolved automatically.

## 13. Sandbox remediation policy

Remediation executes only against the local simulator configuration and only after explicit approval. The action catalog may include `disable_fault(scenario_id)`, `restore_previous_config(config_revision)`, or `reduce_simulated_pool_pressure` with strict bounds. Every action must have a precondition, schema, idempotency key, maximum scope, expiry/rollback behavior, audit event, and post-action verification. The executor is ordinary application code, not a shell tool.

Reject action if incident/run mismatch, approval is missing/rejected/stale, simulator is not in development mode, target is not allowlisted, parameters exceed bounds, action was already applied inconsistently, or policy says the action is unsafe. Record denial reasons without disclosing secrets. No action can call an external system.

## 14. FastAPI API design

Use versioned `/api/v1` routes and Pydantic schemas. Suggested endpoints:

| Method and route | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness/readiness summary without leaking configuration. |
| `GET /api/v1/incidents` / `POST /api/v1/incidents` | Filter/paginate or create a manual incident. |
| `GET /api/v1/incidents/{id}` | Incident detail and lifecycle. |
| `POST /api/v1/incidents/{id}/investigations` | Start a new bounded graph run; return `202` and run ID. |
| `GET /api/v1/runs/{id}` | Run state, safe progress, evidence, hypotheses, recommendation. |
| `GET /api/v1/runs/{id}/events` | SSE progress stream; support reconnect with event ID/sequence. |
| `POST /api/v1/runs/{id}/approval` | Approve/reject/request more evidence; idempotency key required. |
| `POST /api/v1/incidents/{id}/resolve` | Audited manual close with reason. |
| `GET /api/v1/simulator/scenarios` | List scenarios and whether each is active. |
| `POST /api/v1/simulator/scenarios/{key}/start` | Start a bounded fault scenario in development mode. |
| `POST /api/v1/simulator/scenarios/{key}/stop` | Stop and clean up a scenario. |
| `GET /api/v1/simulator/telemetry` | Bounded demo telemetry query for debugging/demo UI. |

Use `201` for created resources, `202` for accepted asynchronous work, `404` for missing records, `409` for invalid lifecycle/state conflicts, `422` for schema validation, and safe `5xx` errors with correlation IDs. Paginate lists, cap ranges, and use request IDs. CORS should allow only the local frontend origin in development. Document OpenAPI examples and error schemas.

## 15. React dashboard

Core screens:

- **Incident list:** severity, service, status, start time, scenario badge, and filters.
- **Incident detail:** timeline, symptom report, run history, and start-investigation action.
- **Investigation view:** live graph progress, evidence grouped by source, hypothesis and confidence, source references, branch failures, and bounded retry count.
- **Approval panel:** proposed action, exact simulator target/parameters, rationale/evidence, risk, verification plan, rollback, approve/reject/request-evidence controls.
- **Simulator panel:** available scenarios, active faults, start/stop controls, and clear simulated-data labels.
- **Observability page (later):** embedded links or charts from local Grafana, not a reimplementation of its query engine.

The UI must distinguish “investigation running,” “awaiting approval,” “insufficient evidence,” “action rejected,” “verification failed,” and “resolved.” Show timestamps and whether data is simulated. Use accessible keyboard controls and visible loading/error states. Avoid rendering arbitrary model markdown/HTML unsanitized.

## 16. Configuration and `.env`

Commit `.env.example`, never `.env`. Parse settings centrally with typed validation; fail fast on invalid required values and redact secrets in logs. Suggested variables:

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
DATABASE_URL=postgresql+psycopg://incident_app:change-me@localhost:5432/incident_lab
LLM_PROVIDER=fake
LLM_MODEL=
LLM_API_KEY=
LLM_BASE_URL=
GRAPH_MAX_ROUNDS=2
GRAPH_TIMEOUT_SECONDS=90
TOOL_TIMEOUT_SECONDS=10
SIMULATOR_ENABLED=true
SIMULATOR_MAX_FAULT_SECONDS=300
FRONTEND_ORIGIN=http://localhost:5173
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
LOG_LEVEL=INFO
```

Only set provider-specific credentials when using that provider. Do not expose backend secrets through Vite `VITE_*` variables. In non-development environments, require strong secrets and disable simulator routes unless explicitly enabled. Use Compose secrets or an external secret manager for any later deployment.

## 17. Evaluation and testing strategy

Testing is part of the design; it should not require expensive model calls or flaky timing.

### Test layers

- **Unit:** state reducers, schemas, lifecycle transitions, time-window validation, metrics calculations, action policy, idempotency, and each tool against fixtures.
- **Graph:** use fake model and deterministic tool results; assert node order/routing, branch merge, bounded cycles, partial failure behavior, interrupt payload, resume after approve/reject, and recursion/timeout handling.
- **Integration:** PostgreSQL migrations, repository queries, checkpoint persistence/restart, FastAPI status/error contracts, and SSE event sequence.
- **Frontend:** accessible approval flow, scenario controls, empty/loading/error states, and streamed updates.
- **End-to-end:** start scenario → create incident → investigate → inspect evidence → approve safe action → verify → resolve. Include reject and insufficient-evidence paths.
- **Evaluation:** versioned scenarios with expected cause, must-find evidence, forbidden unsupported claims, recommended action, and desired routing. Score evidence recall/precision, cause classification, citation validity, action safety, and completion. Keep deterministic checks primary; use model-as-judge only as supplemental and reviewable.

Record provider/model, prompt version, graph version, scenario seed, and evaluation result. Track latency, token use/cost where available, branch tool calls, retries, and human approval outcome. Compare prompt/graph changes on the same fixtures. Never use a single aggregate LLM score as proof of correctness.

Do not add tests merely to inflate count. Every test should protect an invariant or teach a concept. Keep test fixtures small and do not depend on live APIs in the default test suite.

## 18. Security and safety requirements

- No production integrations or arbitrary external tool access in the project scope.
- Secrets only in local environment/secrets store; redact them in logs, errors, SSE, and evaluation artifacts.
- Parameterized database access; model never writes SQL or executes code.
- Read-only evidence tools and strict result/time limits.
- Action allowlist, schema validation, explicit approval, policy checks, idempotency, audit record, and verification before resolution.
- Authentication boundary for approval and simulator routes; development identity clearly labeled.
- CORS allowlist, local bind by default, request size/rate limits, and safe error responses.
- Sanitize model-generated UI text; treat incident descriptions/log fields as untrusted prompt-injection content. Tool instructions and policy come from trusted code, and evidence text cannot alter permissions.
- Do not feed secrets or unnecessary personal data into the model. Minimize retained prompts and raw telemetry; define local retention and deletion behavior.
- Simulator must be disabled by default outside development and have hard duration/impact limits.
- Audit approval decisions and action results. Protect against duplicate/resumed graph runs applying the same action twice.

## 19. Example incident walk-through

Scenario: **Database latency**. Simulator adds 900 ms to the product query path. Incident reports p95 latency rising from roughly 350 ms to 1.4 s.

1. `load_incident` binds incident/run/thread identifiers.
2. `triage` marks ShopAPI latency degradation and requests metrics, traces, logs, and recent changes.
3. Parallel branches find: latency histogram shift; DB span dominates request duration; logs show no corresponding increase in 5xx; no recent release. Every statement cites evidence IDs/time windows.
4. `analyze_root_cause` selects simulated database delay with supporting evidence; it notes that a lack of release evidence does not prove no external cause.
5. Graph maps the cause to `disable_fault` for the active scenario and pauses at the human approval interrupt.
6. UI shows action scope and rollback. On approval, executor checks scenario state and idempotency and disables the injected delay.
7. Verification gathers a new window and checks latency against a threshold. If latency is still high or sample size is too small, incident remains open/mitigated with explanation.

The known scenario label belongs in evaluation truth, not in telemetry exposed to the reasoning nodes. This avoids a trivial “read the answer” demo.

## 20. Phased roadmap and definition of done

Each phase should leave a runnable, reviewable increment. Keep a short decision log when a meaningful design choice changes.

### Phase 0 — project skeleton and contracts

Create repository, Python/frontend scaffolds, formatting/type checks, `.env.example`, Compose PostgreSQL, health endpoint, and initial architecture decisions.

**Done when:** fresh setup instructions work; database health check succeeds; API and frontend start; secrets are absent from Git; CI or documented local checks run.

**Learning:** modular monolith boundaries, typed configuration, reproducible environments, Docker Compose, API contracts.

### Phase 1 — ShopAPI and deterministic simulator

Implement endpoints, seeded data, structured logs, basic metric/trace-like events, fault scenarios with TTL/cleanup, and simulator UI/API. Add at least three reproducible scenarios.

**Done when:** each scenario reliably creates distinct measurable symptoms; it can be stopped/expired; the UI clearly labels generated evidence; unit tests verify fault cleanup and safety bounds.

**Learning:** backend service design, middleware, telemetry dimensions, deterministic test fixtures, fault injection.

### Phase 2 — incident domain and evidence tools

Add migrations/domain tables, incident lifecycle service, evidence repository, and bounded read-only log/metric/change tools. Add trace tool if the simulator has trace records.

**Done when:** an incident and run can be persisted; tools return typed cited evidence within configured limits; invalid windows and unknown services are rejected; lifecycle transitions are audited.

**Learning:** relational modeling, migrations, repository boundaries, tool schemas, provenance, data validation.

### Phase 3 — deterministic LangGraph investigation MVP

Build typed state, `load_incident`, triage, parallel evidence branches, synthesis, cause analysis with a fake model/rule baseline, conditional sufficiency routing, bounded refinement loop, and final report. Begin with in-memory checkpointer.

**Done when:** graph tests assert branch fan-out/fan-in, reducer correctness, route choices, partial branch failure, maximum rounds, and an insufficient-evidence result; the graph provides traceable evidence IDs and never proposes unsupported causes in fixtures.

**Learning:** StateGraph, nodes/edges, reducers, `Send`/parallelism, conditional routing, cycles, recursion limits, subgraphs, deterministic graph tests.

### Phase 4 — real model adapter and evaluation

Add one hosted provider behind a small adapter, structured output validation, prompt versioning, fake provider mode, and scenario evaluation runner. Keep deterministic calculations for metrics and policy.

**Done when:** no-key mode still works; malformed model outputs fail safely; evaluations report cause/evidence/action scores; model and prompt metadata are recorded; cost/latency can be inspected.

**Learning:** structured generation, provider abstraction, prompt injection boundaries, evaluation design, model observability.

### Phase 5 — persistent runs, streaming, and human approval

Add PostgreSQL checkpointer, SSE event feed, interrupt approval UI/API, approval audit records, restart/resume behavior, and rejection/request-more-evidence paths.

**Done when:** a graph paused at approval survives API restart and resumes on the same thread; repeated/stale decisions are safe; browser reconnect does not lose sequence; no action runs before approval.

**Learning:** checkpointers, thread identity, durable execution, interrupts, `Command(resume=...)`, streaming modes/events, idempotency.

### Phase 6 — sandbox remediation and verification

Implement fixed action catalog, policy checks, simulator-only executor, rollback/expiry, post-action verification, and incident transitions.

**Done when:** approved action affects only simulator state; reject/denied/stale/duplicate paths cannot mutate it; audit explains each result; verification can report failure without false resolution.

**Learning:** human-in-the-loop safety, side-effect boundaries, retries vs idempotency, compensating action, verification-driven workflows.

### Phase 7 — observability and resilience

Add Prometheus metrics and Grafana dashboard; then OpenTelemetry spans/export and trace linking. Add timeouts, transient retries, provider fallback, shutdown behavior, and structured operational logs.

**Done when:** dashboard answers rate/error/latency questions; an investigation trace connects API, graph nodes, and evidence calls; bounded resource use is documented; telemetry labels avoid cardinality explosions.

**Learning:** metrics vs logs vs traces, instrumentation, correlation, backpressure/timeouts, production-style operability.

### Phase 8 — portfolio polish and deployment rehearsal

Add seeded demo walkthrough, screenshots or short recording, architecture diagram, threat model, evaluation results, decision records, clean install check, and a simple deployment guide. Optional containerize API/frontend for a single-host demo.

**Done when:** a reviewer can run the demo from the README, reproduce a scenario, understand why LangGraph is used, inspect a graph run, approve/reject safely, and see measured evaluation results and limitations.

**Learning:** technical communication, reproducibility, system tradeoffs, portfolio presentation.

### Advanced optional milestones

- Add a second evidence provider (Prometheus or a trace backend) behind the same tool interface.
- Compare hand-built graph routing with a controlled planner node and report the tradeoff.
- Add checkpoint replay, human-edited investigation plan, and graph version migration strategy.
- Add a queue/worker only after demonstrating that long runs or concurrency exceed the single-process design.
- Add MCP as a separate, explicitly permissioned adapter exposing selected read-only tools. Keep local internal tools as the source of truth and validate MCP results identically.
- Explore A2A only if there is a concrete cross-agent interoperability use case; do not split one graph into networked agents merely for novelty.

## 21. Useful workflows

Document stable project scripts such as:

```text
make dev                 # start dependencies and app processes
make db-migrate          # apply migrations
make seed                # seed demo data
make test                # fast deterministic tests
make test-integration    # tests requiring PostgreSQL
make eval                # run versioned incident scenarios
make lint                # format/type/lint checks
make reset-demo          # clear and reseed local demo data (explicitly destructive locally)
```

On Windows, equivalent PowerShell commands should be documented if `make` is unavailable. Keep `reset-demo` carefully scoped to the local development database and make it print the target database before clearing data.

## 22. Common pitfalls and what not to build initially

- **Do not make every component an agent.** Use deterministic code for metrics, validation, persistence, policy, and action execution.
- **Do not claim confidence is calibrated because an LLM said “0.9.”** Measure it against fixtures or keep it qualitative.
- **Do not let model text authorize or execute a change.** Parse a catalog action and enforce policy in code.
- **Do not put unlimited logs/traces into state or prompts.** Query, aggregate, cap, cite, and summarize.
- **Do not have parallel nodes overwrite shared lists.** Define reducers and test them.
- **Do not create an unbounded graph cycle or retry a mutation blindly.** Set round, timeout, and idempotency limits.
- **Do not conflate incident, run, and checkpoint statuses.** They have different lifetimes.
- **Do not treat checkpoint storage as the incident database.** Maintain domain records and audit events explicitly.
- **Do not stream hidden reasoning.** Show progress, tool activity, evidence, and concise rationale.
- **Do not trust logs as instructions.** Incident text and telemetry are untrusted input.
- **Do not add Kubernetes, Kafka, Redis, vector search, multi-agent debate, or local GPU assumptions to the MVP.** Add a component only when a demonstrated requirement teaches something valuable.
- **Do not describe the simulator as production-grade monitoring or remediation.** State its limits prominently.

## 23. Deployment and future direction

The initial deliverable is local development. A later demo deployment can use a single VM or managed container platform, managed PostgreSQL, HTTPS reverse proxy, secrets manager, backups, bounded worker concurrency, and disabled-by-default simulator routes. Before exposing it publicly, add real authentication/authorization, CSRF protections appropriate to the auth model, rate limits, database migration/backup procedures, secure headers, dependency scanning, and a threat review. Do not deploy with development identity or simulator mutation endpoints open.

Possible extensions include a real read-only telemetry adapter, ticketing integration, richer service dependency maps, multiple reviewers, incident deduplication, scenario generation, and MCP tool exposure. Any real integration needs least privilege and explicit operational approval. A2A is an exploration only after there is a genuine need for independently operated agents to collaborate across system boundaries.

## 24. Interview-learning map

| Portfolio discussion | Evidence to show |
|---|---|
| Why LangGraph? | Explicit stateful investigation with parallel evidence, bounded reassessment, durable human interrupt, and resume; show why a linear function is insufficient. |
| How is it safe? | Read-only investigation, untrusted evidence handling, fixed action catalog, human approval, simulator-only executor, idempotency, audit, and verification. |
| How do you handle uncertainty? | Evidence provenance, contradictions, bounded missing-signal loop, insufficient-evidence outcome, and evaluation against known scenarios. |
| How does it recover? | Per-branch error envelopes, transient-only retry, PostgreSQL checkpoint resume, bounded graph execution, and partial results. |
| How do you test an agent? | Fake model, deterministic tool fixtures, graph route assertions, scenario evaluations, citation/action checks, and a small number of end-to-end flows. |
| How does it scale? | Discuss current modular-monolith limits and measured triggers for worker/queue/service separation instead of claiming hypothetical scale. |
| What is simulated? | Clearly identify ShopAPI, generated traffic/telemetry, incidents, and remediation; explain how adapters could later connect to real sources. |

## 25. Final acceptance criteria

The project is portfolio-ready when all of the following are true:

1. A clean local setup runs on the target laptop with no GPU and offers a no-key deterministic mode.
2. ShopAPI scenarios generate distinct, repeatable and clearly labeled telemetry.
3. A user can create an incident and inspect parallel, cited evidence from the graph.
4. The graph has typed state, reducers, subgraphs, explicit routing, a bounded cycle, safe retries, and a terminal insufficient-evidence path.
5. Runs persist and resume across API restart at a human approval interrupt.
6. No remediation occurs without a validated human decision; all execution is allowlisted and confined to simulator state.
7. Post-action verification controls whether an incident is resolved, mitigated, or remains open.
8. API, UI, database, graph, and evaluation behavior have deterministic automated coverage.
9. Logs/metrics/traces have a progressive, runnable observability path, and the project documents what the simulation cannot represent.
10. README and demo instructions let a reviewer reproduce a full scenario and understand the architecture, tradeoffs, and learning outcomes.

This is a substantial project. Implement phases in order and keep each phase demonstrable. The strongest portfolio signal will be a small system whose state transitions, evidence quality, safety boundaries, and failure behavior are clear—not the number of frameworks in its Compose file.
