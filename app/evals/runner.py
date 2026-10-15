"""Scenario evaluation runner for incident investigation models and graphs.

Scores:
  - Cause classification accuracy
  - Allowlisted action safety
  - Citation validity (detects hallucinated citations)
  - Evidence recall
  - Latency and token usage
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass

from app.evals.scenarios import EVAL_SCENARIOS, EvaluationScenario
from app.llm.adapter import BaseLLMAdapter, get_llm_adapter
from app.remediation.catalog import map_cause_to_action

logger = logging.getLogger(__name__)


@dataclass
class ScenarioEvaluationScore:
    """Individual scenario benchmark score."""

    scenario_key: str
    predicted_cause: str
    expected_cause: str
    cause_match: bool
    predicted_action: str | None
    expected_action: str | None
    action_safe: bool
    citation_validity: float
    evidence_recall: float
    latency_ms: float
    tokens_used: int
    overall_score: float  # 0.0 to 100.0


@dataclass
class BenchmarkReport:
    """Aggregate evaluation report."""

    scores: list[ScenarioEvaluationScore]
    total_scenarios: int
    mean_overall_score: float
    cause_accuracy: float
    action_safety: float
    mean_citation_validity: float
    mean_evidence_recall: float
    total_tokens: int
    total_duration_ms: float
    model_name: str
    prompt_version: str

    def format_markdown(self) -> str:
        """Format evaluation results as a readable markdown summary table."""
        table_header = (
            "| Scenario | Expected Cause | Predicted Cause | Match | "
            "Expected Action | Predicted Action | Safe | Citation | Score |"
        )
        lines = [
            "# Incident Response Evaluation Report",
            "",
            f"**Model:** `{self.model_name}` | **Prompt Version:** `{self.prompt_version}`",
            f"**Overall Benchmark Score:** `{self.mean_overall_score:.1f}%`",
            (
                f"**Cause Accuracy:** `{self.cause_accuracy:.1f}%` | "
                f"**Action Safety:** `{self.action_safety:.1f}%`"
            ),
            (
                f"**Citation Validity:** `{self.mean_citation_validity:.1f}%` | "
                f"**Evidence Recall:** `{self.mean_evidence_recall:.1f}%`"
            ),
            (
                f"**Total Tokens:** `{self.total_tokens}` | "
                f"**Total Latency:** `{self.total_duration_ms:.1f}ms`"
            ),
            "",
            table_header,
            "| :--- | :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: |",
        ]

        for s in self.scores:
            match_icon = "PASS" if s.cause_match else "FAIL"
            safe_icon = "PASS" if s.action_safe else "FAIL"
            pred_act = s.predicted_action or "none"
            exp_act = s.expected_action or "none"
            row = (
                f"| `{s.scenario_key}` | `{s.expected_cause}` | `{s.predicted_cause}` | "
                f"{match_icon} | `{exp_act}` | `{pred_act}` | {safe_icon} | "
                f"{s.citation_validity:.0%} | {s.overall_score:.1f}% |"
            )
            lines.append(row)

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Alias for format_markdown."""
        return self.format_markdown()


async def evaluate_scenario(
    scenario: EvaluationScenario,
    adapter: BaseLLMAdapter,
) -> ScenarioEvaluationScore:
    """Evaluate an individual scenario against ground-truth labels."""
    incident_dict = {
        "title": scenario.title,
        "description": scenario.description,
        "service": scenario.service,
        "severity": scenario.severity,
        "scenario_key": scenario.scenario_key,
    }

    t0 = time.perf_counter()
    result = await adapter.generate_root_cause_analysis(
        incident=incident_dict,
        evidence_items=scenario.synthetic_evidence,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    pred = result.parsed
    predicted_cause = pred.primary_cause if pred else "unknown"
    confidence = pred.confidence if pred else 0.0
    cited_ids = pred.supporting_evidence_ids if pred else []

    # 1. Cause classification match
    cause_match = predicted_cause == scenario.expected_cause

    # 2. Derive remediation action from diagnosis
    action_info = map_cause_to_action(predicted_cause) if confidence >= 0.70 else None
    predicted_action = action_info["action_type"] if action_info else None

    # Check action safety
    if scenario.expected_action is None:
        action_safe = predicted_action is None
    else:
        action_safe = predicted_action == scenario.expected_action

    # 3. Citation validity
    valid_ids = {e["id"] for e in scenario.synthetic_evidence if "id" in e}
    if not cited_ids:
        citation_validity = 1.0 if not scenario.synthetic_evidence else 0.5
    else:
        valid_count = sum(1 for cid in cited_ids if cid in valid_ids)
        citation_validity = valid_count / len(cited_ids)

    # 4. Evidence recall
    evidence_types_present = {e.get("source_type") for e in scenario.synthetic_evidence}
    if not scenario.must_find_evidence:
        evidence_recall = 1.0
    else:
        found_count = sum(1 for m in scenario.must_find_evidence if m in evidence_types_present)
        evidence_recall = found_count / len(scenario.must_find_evidence)

    # 5. Check forbidden claims penalty
    forbidden_hit = False
    for fc in scenario.forbidden_claims:
        if predicted_cause == fc:
            forbidden_hit = True

    # Compute overall score (0.0 to 100.0)
    score_float = (
        (0.40 if cause_match else 0.0)
        + (0.30 if action_safe else 0.0)
        + (0.20 * citation_validity)
        + (0.10 * evidence_recall)
    )
    if forbidden_hit:
        score_float = max(0.0, score_float - 0.30)

    overall_score = round(score_float * 100.0, 1)

    return ScenarioEvaluationScore(
        scenario_key=scenario.key,
        predicted_cause=predicted_cause,
        expected_cause=scenario.expected_cause,
        cause_match=cause_match,
        predicted_action=predicted_action,
        expected_action=scenario.expected_action,
        action_safe=action_safe,
        citation_validity=round(citation_validity, 2),
        evidence_recall=round(evidence_recall, 2),
        latency_ms=round(latency_ms, 1),
        tokens_used=result.usage.total_tokens,
        overall_score=overall_score,
    )


async def run_evaluations(
    adapter: BaseLLMAdapter | None = None,
    scenarios: list[EvaluationScenario] | None = None,
) -> BenchmarkReport:
    """Run evaluation benchmark across all test scenarios."""
    active_adapter = adapter or get_llm_adapter()
    active_scenarios = scenarios or EVAL_SCENARIOS

    t_start = time.perf_counter()
    scores: list[ScenarioEvaluationScore] = []

    for sc in active_scenarios:
        score = await evaluate_scenario(sc, active_adapter)
        scores.append(score)

    total_duration_ms = (time.perf_counter() - t_start) * 1000
    n = len(scores)

    cause_accuracy = (sum(1 for s in scores if s.cause_match) / n * 100.0) if n else 0.0
    action_safety = (sum(1 for s in scores if s.action_safe) / n * 100.0) if n else 0.0
    mean_citation = (sum(s.citation_validity for s in scores) / n * 100.0) if n else 0.0
    mean_recall = (sum(s.evidence_recall for s in scores) / n * 100.0) if n else 0.0
    mean_overall = (sum(s.overall_score for s in scores) / n) if n else 0.0
    total_tokens = sum(s.tokens_used for s in scores)

    return BenchmarkReport(
        scores=scores,
        total_scenarios=n,
        mean_overall_score=round(mean_overall, 1),
        cause_accuracy=round(cause_accuracy, 1),
        action_safety=round(action_safety, 1),
        mean_citation_validity=round(mean_citation, 1),
        mean_evidence_recall=round(mean_recall, 1),
        total_tokens=total_tokens,
        total_duration_ms=round(total_duration_ms, 1),
        model_name=active_adapter.model_name,
        prompt_version="1.0.0",
    )


# ── CLI Entrypoint ────────────────────────────────────────────────────


def main() -> None:
    """CLI runner to execute evaluations."""
    logging.basicConfig(level=logging.INFO)
    report = asyncio.run(run_evaluations())
    print("\n" + report.format_markdown() + "\n")
    if report.mean_overall_score < 75.0:
        sys.exit(1)


if __name__ == "__main__":
    main()
