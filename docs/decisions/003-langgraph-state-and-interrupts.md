# ADR-003: LangGraph State Management, Checkpoints, and Interrupts

**Status:** Accepted  
**Date:** 2026-10-19  
**Context:** Designing the workflow engine for multi-signal incident investigation and human-gated remediation.

## Decision

Use LangGraph (`StateGraph`) with typed state (`IncidentState`), explicit list reducers (`Annotated[list[EvidenceItem], add]`), and PostgreSQL-backed checkpointing (`AsyncPostgresSaver` with in-memory fallback for testing). Remediation requires a durable workflow interrupt that pauses graph execution and resumes only upon an explicit human approval or rejection API call.

## Rationale

1. **Non-linear Investigation:** Real incident investigation is not a simple linear chain. It requires parallel evidence gathering across disparate modalities (logs, metrics, traces, change events), followed by synthesis, confidence assessment, and potential bounded reassessment if evidence is ambiguous or incomplete.
2. **Deterministic State Evolution:** By defining typed state schemas with Pydantic and using explicit reducers, parallel subgraph branches append evidence safely without race conditions or list overwrites.
3. **Durable Human-in-the-Loop Interrupts:** Remediating operational infrastructure must never be autonomous. LangGraph interrupts pause graph execution durably at the recommendation boundary. The process can reboot, reload, or crash during the human decision window; when the user submits an approval or rejection, the graph resumes from the exact persisted checkpoint.
4. **Bounded Cycles:** Traditional ReAct agent loops are prone to infinite hallucination cycles. LangGraph provides programmatic conditional edges with strict iteration bounds (`max_rounds = 3`), guaranteeing termination in an `insufficient_evidence` terminal state if convergence is not reached.

## Consequences

- All state keys must be typed and annotated with reducers if mutated across parallel branches.
- Node functions must remain pure state transformations with error envelopes (`error: str | None`) rather than throwing uncaught exceptions that would crash the run.
- Database migrations must support checkpointer tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) when PostgreSQL persistence is enabled.
- Unit testing requires deterministic mock checkpointers (`MemorySaver`) to validate graph topologies without database dependencies.
