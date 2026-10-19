# ADR-005: Progressive Observability and Operational Resilience

**Status:** Accepted  
**Date:** 2026-10-19  
**Context:** Ensuring the incident response workbench itself is observable, debuggable, and resilient against downstream latency and failures.

## Decision

Implement progressive, standard-compliant observability and resilience across the entire backend:
1. **Prometheus Metrics with Cardinality Protection:** Use standard Prometheus metrics (`requests_total`, `request_duration_seconds`, `investigation_runs_total`, `investigation_duration_seconds`) with strict route template normalization (`/api/v1/products/{id}` instead of raw UUIDs) to prevent metric cardinality explosions.
2. **OpenTelemetry W3C Distributed Tracing:** Instrument HTTP middleware, LangGraph node execution, and evidence tool invocations with OpenTelemetry spans and W3C `traceparent` context propagation exported to Jaeger via OTLP/HTTP.
3. **Structured JSON Logging with Trace Correlation:** Emit structured JSON logs containing `trace_id` and `span_id` extracted from OpenTelemetry span context for seamless log-to-trace navigation.
4. **Resilience Patterns:** Wrap external model and evidence calls with deterministic execution timeouts, exponential backoff with full jitter for transient retries, and automatic provider fallback.

## Rationale

1. **Self-Observing Agent:** An incident response system that cannot observe itself cannot be trusted in production. Operators need to know how long evidence collection takes, which subgraphs fail, and whether the LLM is degrading latency.
2. **Cardinality Safety:** A common trap in microservices and agent tooling is including incident IDs, user IDs, or dynamic query strings in metric labels. Normalizing paths to route templates keeps Prometheus memory usage bounded (< 256MB).
3. **Full Jitter Retries:** Naive retries or exponential backoff without jitter create "thundering herds" that exacerbate downstream service degradation. Full jitter spreads retries evenly across the backoff window.
4. **Zero-Key Local Dev:** Provider fallback ensures that if an external model API key is absent, expired, or throttled, the system falls back gracefully to a deterministic mock provider, preserving local development and testing workflows.

## Consequences

- All FastAPI routes must be registered with clean route templates.
- Developers can spin up Prometheus, Grafana, and Jaeger via the Docker Compose `observability` profile without affecting base database development.
- Logging output in production and testing uses JSON; local console formatting is preserved for human readability.
