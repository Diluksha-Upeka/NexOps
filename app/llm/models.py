"""Pydantic schemas for LLM structured outputs and evaluation metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field

VALID_CAUSES = {
    "db_latency",
    "db_connection_exhaustion",
    "bad_release",
    "dependency_timeout",
    "elevated_5xx",
    "unknown",
}


# ── Structured Prediction Schemas ─────────────────────────────────────


class TriagePrediction(BaseModel):
    """Structured output for incident triage."""

    service: str = Field(default="shopapi", description="Identified impacted service.")
    severity: str = Field(default="medium", pattern=r"^(critical|high|medium|low)$")
    symptoms: list[str] = Field(default_factory=list, description="Extracted key symptoms.")
    likely_areas: list[str] = Field(
        default_factory=list, description="Suspected infrastructure or code areas."
    )


class RootCauseAnalysisPrediction(BaseModel):
    """Structured output for root cause analysis."""

    primary_cause: str = Field(
        description="Diagnosed cause key. Must be one of the known fault patterns."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Calibrated confidence score between 0.0 and 1.0."
    )
    reasoning: str = Field(description="Clear explanation citing specific evidence observations.")
    supporting_evidence_ids: list[str] = Field(
        default_factory=list, description="List of evidence IDs directly supporting this diagnosis."
    )
    contradictions: list[str] = Field(
        default_factory=list, description="Any conflicting observations that weaken confidence."
    )
    missing_evidence: list[str] = Field(
        default_factory=list, description="Any observations that would strengthen the diagnosis."
    )


# ── LLM Usage and Execution Metadata ──────────────────────────────────


class LLMUsage(BaseModel):
    """Token usage, timing, and cost metrics for an LLM invocation."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0


class LLMResult[T](BaseModel):
    """Standardized wrapper for LLM responses containing typed data and provenance."""

    parsed: T | None = None
    raw_text: str = ""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    model_name: str = "fake-model"
    prompt_version: str = "1.0.0"
    provider: str = "fake"
    success: bool = True
    error_message: str | None = None
