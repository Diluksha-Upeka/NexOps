"""LLM Provider adapter and structured generation module (Phase 4)."""

from app.llm.adapter import (
    BaseLLMAdapter,
    FakeLLMAdapter,
    HostedOpenAIAdapter,
    get_llm_adapter,
)
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
    format_untrusted_evidence,
    format_untrusted_incident,
)

__all__ = [
    "PROMPT_VERSION",
    "ROOT_CAUSE_SYSTEM_PROMPT",
    "TRIAGE_SYSTEM_PROMPT",
    "BaseLLMAdapter",
    "FakeLLMAdapter",
    "HostedOpenAIAdapter",
    "LLMResult",
    "LLMUsage",
    "RootCauseAnalysisPrediction",
    "TriagePrediction",
    "build_root_cause_prompt",
    "format_untrusted_evidence",
    "format_untrusted_incident",
    "get_llm_adapter",
]
