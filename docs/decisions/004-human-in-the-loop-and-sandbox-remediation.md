# ADR-004: Human-in-the-Loop Approval and Sandbox Remediation

**Status:** Accepted  
**Date:** 2026-10-19  
**Context:** Enforcing safety boundaries around agent-proposed operational interventions.

## Decision

Enforce a mandatory Human-in-the-Loop (HITL) approval gate for all remediation actions. The agent cannot directly invoke mutating shell commands, APIs, or infrastructure operations. Actions are constrained to a closed, strictly validated action catalog enum (`ActionType`), validated against a deterministic policy engine, and executed exclusively within an in-memory simulation sandbox (`ShopAPISimulator`).

## Rationale

1. **Defense Against Rogue Agent Actions:** Operational systems cannot tolerate unvetted autonomous interventions. LLMs can misinterpret telemetry, hallucinate syntax, or produce destructive commands (e.g., `rm -rf`, premature database drop, uncoordinated failover). Constraining the agent to advising rather than deciding ensures zero unauthorized mutations.
2. **Closed Action Catalog:** Instead of allowing free-form bash or arbitrary HTTP execution, all actions are modeled as a discrete enum (`RESTART_SERVICE`, `ROLLBACK_DEPLOYMENT`, `SCALE_UP_REPLICAS`, `CLEAR_CACHE`). Each action specifies strict Pydantic parameter schemas, preventing prompt injection from injecting malicious arguments.
3. **Deterministic Policy Pre-Checks:** Before reaching the human, recommendations are evaluated against deterministic policy rules (e.g., requiring secondary approvals for critical services, rate limiting restarts, parameter bounds checking).
4. **Simulator Sandbox Confinement:** All executions mutate only the in-memory state of the simulated ShopAPI service. No sub-processes, OS shell invocations, or external network requests are permitted during remediation.
5. **Post-Action Verification:** After an approved action executes, the workflow automatically runs verification checks (probing error rates and latency) to verify if the incident is resolved or mitigated, transitioning the incident lifecycle state deterministically.

## Consequences

- An incident cannot transition to `RESOLVED` or `MITIGATED` via remediation without an explicit `/approve` API call containing a valid human decision.
- The system maintains an append-only audit log (`audit_events`) recording the proposed action, policy evaluation, approving user, timestamp, and sandbox execution result.
- Automated testing requires a simulated approval mechanism or direct unit testing of policy and executor components.
