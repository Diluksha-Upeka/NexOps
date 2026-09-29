# ADR-001: Modular Monolith Architecture

**Status:** Accepted  
**Date:** 2026-09-29  
**Context:** Choosing the initial deployment architecture for the incident response system.

## Decision

Build as a modular monolith: one Python repository, one PostgreSQL database, and one frontend. Keep package boundaries clear (`app/shopapi/`, `app/graph/`, `app/incidents/`, `app/remediation/`) so components can be split later if a demonstrated requirement justifies it.

## Rationale

- The project runs on a single laptop (16 GB RAM, i3-class CPU). Microservices would add operational overhead without teaching new concepts at this stage.
- A monolith with clear module boundaries is easier to test, debug, and reason about.
- Docker Compose starts only PostgreSQL; the API and frontend run on the host for fast reload.
- Splitting is always possible later — package boundaries enforce separation of concerns now.

## Consequences

- All domain logic lives in one process; no inter-service networking or distributed tracing needed initially.
- Must enforce module boundaries via imports and review, not via network isolation.
- Later phases (observability) can introduce additional Compose services when there is a learning reason.
