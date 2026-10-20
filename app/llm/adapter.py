"""LLM Provider adapters — supporting deterministic fake mode and hosted API models.

Features:
  - BaseLLMAdapter protocol
  - FakeLLMAdapter for deterministic, no-key operation with failure mode injection
  - HostedOpenAIAdapter for hosted OpenAI-compatible chat completion APIs
  - Token, latency, and estimated cost instrumentation
  - Pydantic structured output validation with safe fallbacks
  - Secret redaction in all logs and error messages
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.settings import Settings, get_settings
from app.llm.models import (
    LLMResult,
    LLMUsage,
    RootCauseAnalysisPrediction,
    TriagePrediction,
)
from app.llm.prompts import (
    PROMPT_VERSION,
    ROOT_CAUSE_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    build_root_cause_prompt,
    format_untrusted_incident,
)

logger = logging.getLogger(__name__)


# ── Base Adapter ──────────────────────────────────────────────────────


class BaseLLMAdapter(ABC):
    """Abstract base adapter for LLM generation with structured validation."""

    def __init__(self, model_name: str, provider: str) -> None:
        self.model_name = model_name
        self.provider = provider

    @abstractmethod
    async def generate_root_cause_analysis(
        self,
        incident: dict[str, Any],
        evidence_items: list[dict[str, Any]],
    ) -> LLMResult[RootCauseAnalysisPrediction]:
        """Analyze incident telemetry evidence and return structured diagnosis."""
        ...

    @abstractmethod
    async def generate_triage(
        self,
        incident: dict[str, Any],
    ) -> LLMResult[TriagePrediction]:
        """Triage incident report and return classified symptoms and focus areas."""
        ...


# ── Fake Adapter (Deterministic No-Key Mode) ──────────────────────────


class FakeLLMAdapter(BaseLLMAdapter):
    """Deterministic, no-key model adapter.

    Uses deterministic rule-based analysis on the evidence items and incident
    context to simulate LLM responses without network calls or credentials.
    Supports injecting error modes to verify graceful fallback handling.
    """

    def __init__(
        self,
        model_name: str = "fake-incident-reasoner-v1",
        *,
        force_malformed_json: bool = False,
        force_schema_error: bool = False,
        force_error: str | None = None,
    ) -> None:
        super().__init__(model_name=model_name, provider="fake")
        self.force_malformed_json = force_malformed_json
        self.force_schema_error = force_schema_error
        self.force_error = force_error

    async def generate_root_cause_analysis(
        self,
        incident: dict[str, Any],
        evidence_items: list[dict[str, Any]],
    ) -> LLMResult[RootCauseAnalysisPrediction]:
        """Generate structured root-cause prediction deterministically."""
        t0 = time.perf_counter()

        # Handle forced error injection for testing
        if self.force_error:
            latency_ms = (time.perf_counter() - t0) * 1000
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=None,
                raw_text="",
                usage=LLMUsage(latency_ms=latency_ms),
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message=self.force_error,
            )

        if self.force_malformed_json:
            latency_ms = (time.perf_counter() - t0) * 1000
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=None,
                raw_text='{"primary_cause": "db_latency", "confidence": ',  # Unterminated JSON
                usage=LLMUsage(latency_ms=latency_ms),
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message="JSONDecodeError: Unterminated string starting at line 1",
            )

        if self.force_schema_error:
            latency_ms = (time.perf_counter() - t0) * 1000
            # Invalid cause key and out-of-bounds confidence (1.5 > 1.0)
            bad_data = {
                "primary_cause": "some_arbitrary_hallucinated_cause",
                "confidence": 1.5,
                "reasoning": "Invalid schema data",
                "supporting_evidence_ids": ["non-existent-id"],
            }
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=None,
                raw_text=json.dumps(bad_data),
                usage=LLMUsage(latency_ms=latency_ms),
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message="ValidationError: confidence exceeds maximum 1.0",
            )

        # Deterministic evidence reasoning
        evidence_by_type: dict[str, list[dict[str, Any]]] = {}
        for item in evidence_items:
            evidence_by_type.setdefault(item.get("source_type", "unknown"), []).append(item)

        metrics_ev = evidence_by_type.get("metrics", [])
        traces_ev = evidence_by_type.get("traces", [])
        logs_ev = evidence_by_type.get("logs", [])
        changes_ev = evidence_by_type.get("changes", [])

        has_latency_degraded = any(
            m.get("data", {}).get("latency_degraded")
            or "latency degradation" in m.get("summary", "").lower()
            for m in metrics_ev
        )
        has_slow_db = any(
            t.get("data", {}).get("has_slow_db")
            or "slow database spans" in t.get("summary", "").lower()
            for t in traces_ev
        )
        has_pool_error = any(
            log_item.get("data", {}).get("pool_error_count", 0) > 0
            or "connection pool exhaustion" in log_item.get("summary", "").lower()
            for log_item in logs_ev
        )
        has_recent_deploy = any(
            c.get("data", {}).get("deployment_count", 0) > 0 for c in changes_ev
        )
        has_dep_timeout = any(
            t.get("data", {}).get("has_timeout")
            or "dependency timeout" in t.get("summary", "").lower()
            for t in traces_ev
        )
        has_elevated_5xx = any(
            log_item.get("data", {}).get("error_count", 0) > 3 for log_item in logs_ev
        )

        scenario_key = incident.get("scenario_key")
        title = str(incident.get("title", "")).lower()

        # Correlate failure pattern
        if (
            (has_recent_deploy and (has_latency_degraded or has_elevated_5xx))
            or (scenario_key == "bad_release")
            or ("release" in title)
            or ("deploy" in title)
        ):
            supporting_ids = [c["id"] for c in changes_ev if c.get("id")]
            supporting_ids.extend([m["id"] for m in metrics_ev if m.get("id")])
            prediction = RootCauseAnalysisPrediction(
                primary_cause="bad_release",
                confidence=0.88,
                reasoning=(
                    "Change history documents a recent deployment coinciding with "
                    "degraded performance."
                ),
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
                missing_evidence=[],
            )

        elif (
            (has_latency_degraded and not has_recent_deploy)
            or (scenario_key == "db_latency")
            or ("latency" in title)
        ):
            supporting_ids = [m["id"] for m in metrics_ev if m.get("id")]
            if has_slow_db:
                supporting_ids.extend([t["id"] for t in traces_ev if t.get("id")])

            confidence = 0.92 if (has_latency_degraded and has_slow_db) else 0.75
            contradictions = []
            if has_recent_deploy:
                contradictions.append("Recent deployment observed in change history.")

            prediction = RootCauseAnalysisPrediction(
                primary_cause="db_latency",
                confidence=confidence,
                reasoning=(
                    "Metrics indicate severe request duration elevation (p95 degradation) "
                    "and trace span breakdown demonstrates database repository delay."
                ),
                supporting_evidence_ids=supporting_ids,
                contradictions=contradictions,
                missing_evidence=[],
            )

        elif has_pool_error or (scenario_key == "db_connection_exhaustion") or ("pool" in title):
            supporting_ids = [log_item["id"] for log_item in logs_ev if log_item.get("id")]
            prediction = RootCauseAnalysisPrediction(
                primary_cause="db_connection_exhaustion",
                confidence=0.90 if has_pool_error else 0.70,
                reasoning="Logs capture database connection pool timeouts and exhaustion errors.",
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
                missing_evidence=[],
            )

        elif (has_recent_deploy and has_latency_degraded) or (scenario_key == "bad_release"):
            supporting_ids = [c["id"] for c in changes_ev if c.get("id")]
            supporting_ids.extend([m["id"] for m in metrics_ev if m.get("id")])
            prediction = RootCauseAnalysisPrediction(
                primary_cause="bad_release",
                confidence=0.88,
                reasoning=(
                    "Change history documents a recent deployment coinciding with "
                    "degraded performance."
                ),
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
                missing_evidence=[],
            )

        elif has_dep_timeout or (scenario_key == "dependency_timeout"):
            supporting_ids = [t["id"] for t in traces_ev if t.get("id")]
            prediction = RootCauseAnalysisPrediction(
                primary_cause="dependency_timeout",
                confidence=0.89,
                reasoning="Trace spans confirm external downstream service calls timing out.",
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
                missing_evidence=[],
            )

        elif has_elevated_5xx and not has_pool_error:
            supporting_ids = [log_item["id"] for log_item in logs_ev if log_item.get("id")]
            prediction = RootCauseAnalysisPrediction(
                primary_cause="elevated_5xx",
                confidence=0.85,
                reasoning="Metrics and logs confirm sustained internal server error (500) rates.",
                supporting_evidence_ids=supporting_ids,
                contradictions=[],
                missing_evidence=[],
            )

        else:
            prediction = RootCauseAnalysisPrediction(
                primary_cause="unknown",
                confidence=0.30,
                reasoning=(
                    "Evidence lacks clear corroborating signals matching any known failure pattern."
                ),
                supporting_evidence_ids=[],
                contradictions=["Ambiguous or sparse telemetry observations."],
                missing_evidence=["Extended trace breakdown", "Detailed error logs"],
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        # Estimate synthetic token usage based on payload size
        prompt_str = build_root_cause_prompt(incident, evidence_items)
        raw_output = prediction.model_dump_json()

        usage = LLMUsage(
            prompt_tokens=len(prompt_str) // 4,
            completion_tokens=len(raw_output) // 4,
            total_tokens=(len(prompt_str) + len(raw_output)) // 4,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=0.0,
        )

        return LLMResult[RootCauseAnalysisPrediction](
            parsed=prediction,
            raw_text=raw_output,
            usage=usage,
            model_name=self.model_name,
            prompt_version=PROMPT_VERSION,
            provider=self.provider,
            success=True,
        )

    async def generate_triage(
        self,
        incident: dict[str, Any],
    ) -> LLMResult[TriagePrediction]:
        """Generate structured triage prediction deterministically."""
        t0 = time.perf_counter()
        title = str(incident.get("title", ""))
        desc = str(incident.get("description", ""))
        service = str(incident.get("service", "shopapi"))
        severity = str(incident.get("severity", "medium"))
        content = f"{title} {desc}".lower()

        symptoms: list[str] = []
        areas: list[str] = []

        if "latency" in content or "slow" in content or "p95" in content:
            symptoms.append("elevated_latency")
            areas.append("database_layer")
        if "500" in content or "5xx" in content or "error" in content:
            symptoms.append("server_errors")
            areas.append("application_handlers")
        if "pool" in content or "connection" in content:
            symptoms.append("pool_exhaustion")
            areas.append("connection_pool")
        if "release" in content or "deploy" in content:
            symptoms.append("recent_release")
            areas.append("deployment_config")

        prediction = TriagePrediction(
            service=service,
            severity=severity,
            symptoms=symptoms or ["general_degradation"],
            likely_areas=areas or ["infrastructure"],
        )

        latency_ms = (time.perf_counter() - t0) * 1000
        raw_text = prediction.model_dump_json()
        prompt_str = format_untrusted_incident(title, desc, service, severity)

        usage = LLMUsage(
            prompt_tokens=len(prompt_str) // 4,
            completion_tokens=len(raw_text) // 4,
            total_tokens=(len(prompt_str) + len(raw_text)) // 4,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=0.0,
        )

        return LLMResult[TriagePrediction](
            parsed=prediction,
            raw_text=raw_text,
            usage=usage,
            model_name=self.model_name,
            prompt_version=PROMPT_VERSION,
            provider=self.provider,
            success=True,
        )


# ── Hosted OpenAI-Compatible Adapter ──────────────────────────────────


class HostedOpenAIAdapter(BaseLLMAdapter):
    """Adapter for hosted OpenAI-compatible chat completion endpoints.

    Communicates over HTTP using standard /chat/completions schema.
    Instruments latency, token counts, and cost, while enforcing secret redaction
    and Pydantic output validation.
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(model_name=model_name, provider="openai")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _redact(self, message: str) -> str:
        """Ensure API keys are never leaked in error messages or logs."""
        if self.api_key and len(self.api_key) > 4:
            return message.replace(self.api_key, "[REDACTED_API_KEY]")
        return message

    async def _post_chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict[str, Any] | None, float, str | None]:
        """Make HTTP request to /chat/completions endpoint."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                latency_ms = (time.perf_counter() - t0) * 1000

                if response.status_code != 200:
                    err_msg = self._redact(f"HTTP {response.status_code}: {response.text[:200]}")
                    return None, latency_ms, err_msg

                return response.json(), latency_ms, None
        except httpx.TimeoutException:
            latency_ms = (time.perf_counter() - t0) * 1000
            return None, latency_ms, "Request timed out waiting for provider response."
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return None, latency_ms, self._redact(f"Connection error: {exc}")

    async def generate_root_cause_analysis(
        self,
        incident: dict[str, Any],
        evidence_items: list[dict[str, Any]],
    ) -> LLMResult[RootCauseAnalysisPrediction]:
        """Invoke hosted model with root cause prompt and validate structured output."""
        user_prompt = build_root_cause_prompt(incident, evidence_items)
        data, latency_ms, error = await self._post_chat_completion(
            ROOT_CAUSE_SYSTEM_PROMPT, user_prompt
        )

        if error or not data:
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=None,
                raw_text="",
                usage=LLMUsage(latency_ms=latency_ms),
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message=error or "No data returned by provider",
            )

        # Extract message content and usage
        choices = data.get("choices", [])
        raw_content = choices[0].get("message", {}).get("content", "") if choices else ""
        raw_usage = data.get("usage", {})
        prompt_tokens = raw_usage.get("prompt_tokens", 0)
        completion_tokens = raw_usage.get("completion_tokens", 0)

        # Cost estimation: (~$0.15 / 1M prompt, $0.60 / 1M completion)
        estimated_cost = (prompt_tokens * 0.00000015) + (completion_tokens * 0.00000060)

        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=round(estimated_cost, 6),
        )

        try:
            parsed_json = json.loads(raw_content)
            prediction = RootCauseAnalysisPrediction.model_validate(parsed_json)
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=prediction,
                raw_text=raw_content,
                usage=usage,
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=True,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Hosted LLM output failed schema validation: %s", exc)
            return LLMResult[RootCauseAnalysisPrediction](
                parsed=None,
                raw_text=raw_content,
                usage=usage,
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message=f"Output validation failed: {exc}",
            )

    async def generate_triage(
        self,
        incident: dict[str, Any],
    ) -> LLMResult[TriagePrediction]:
        """Invoke hosted model with triage prompt and validate structured output."""
        title = str(incident.get("title", ""))
        desc = str(incident.get("description", ""))
        service = str(incident.get("service", "shopapi"))
        severity = str(incident.get("severity", "medium"))

        formatted_incident = format_untrusted_incident(title, desc, service, severity)
        user_prompt = f"Triage the following incident:\n\n{formatted_incident}"
        data, latency_ms, error = await self._post_chat_completion(
            TRIAGE_SYSTEM_PROMPT, user_prompt
        )

        if error or not data:
            return LLMResult[TriagePrediction](
                parsed=None,
                raw_text="",
                usage=LLMUsage(latency_ms=latency_ms),
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message=error or "No data returned by provider",
            )

        choices = data.get("choices", [])
        raw_content = choices[0].get("message", {}).get("content", "") if choices else ""
        raw_usage = data.get("usage", {})
        prompt_tokens = raw_usage.get("prompt_tokens", 0)
        completion_tokens = raw_usage.get("completion_tokens", 0)

        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=round(latency_ms, 2),
            estimated_cost_usd=round(
                (prompt_tokens * 0.00000015) + (completion_tokens * 0.00000060), 6
            ),
        )

        try:
            parsed_json = json.loads(raw_content)
            prediction = TriagePrediction.model_validate(parsed_json)
            return LLMResult[TriagePrediction](
                parsed=prediction,
                raw_text=raw_content,
                usage=usage,
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=True,
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            return LLMResult[TriagePrediction](
                parsed=None,
                raw_text=raw_content,
                usage=usage,
                model_name=self.model_name,
                prompt_version=PROMPT_VERSION,
                provider=self.provider,
                success=False,
                error_message=f"Output validation failed: {exc}",
            )


# ── Adapter Factory ───────────────────────────────────────────────────


def get_llm_adapter(settings: Settings | None = None) -> BaseLLMAdapter:
    """Return the configured LLM adapter based on application settings.

    Defaults to deterministic FakeLLMAdapter whenever LLM_PROVIDER is 'fake'
    or no API key is provided.
    """
    app_settings = settings or get_settings()
    provider = (app_settings.llm_provider or "fake").lower().strip()
    api_key = app_settings.llm_api_key.get_secret_value()

    if provider in ("openai", "google", "gemini", "hosted", "hosted_openai", "remote") and api_key:
        default_base_url = (
            "https://generativelanguage.googleapis.com/v1beta/openai"
            if provider in ("google", "gemini")
            else "https://api.openai.com/v1"
        )
        return HostedOpenAIAdapter(
            model_name=app_settings.llm_model or "gpt-4o-mini",
            api_key=api_key,
            base_url=app_settings.llm_base_url or default_base_url,
            timeout_seconds=app_settings.llm_timeout_seconds,
        )

    return FakeLLMAdapter(model_name=app_settings.llm_model or "fake-incident-reasoner-v1")
