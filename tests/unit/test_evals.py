"""Unit tests for the Scenario Evaluation Benchmark Suite and Runner (Phase 4)."""

from __future__ import annotations

import pytest

from app.evals.runner import (
    BenchmarkReport,
    ScenarioEvaluationScore,
    evaluate_scenario,
    run_evaluations,
)
from app.evals.scenarios import EVAL_SCENARIOS
from app.llm.adapter import FakeLLMAdapter


def test_eval_scenarios_structure() -> None:
    """Verify that all canonical evaluation scenarios are properly defined."""
    assert len(EVAL_SCENARIOS) >= 6

    keys = [s.key for s in EVAL_SCENARIOS]
    assert len(keys) == len(set(keys)), "Scenario keys must be unique"

    expected_keys = {
        "db_latency",
        "db_connection_exhaustion",
        "bad_release",
        "dependency_timeout",
        "elevated_5xx",
        "ambiguous_jitter",
    }
    assert expected_keys.issubset(set(keys))

    for scenario in EVAL_SCENARIOS:
        assert scenario.key
        assert scenario.title
        assert scenario.expected_cause
        assert isinstance(scenario.synthetic_evidence, list)
        assert len(scenario.synthetic_evidence) > 0


@pytest.mark.asyncio
async def test_evaluate_single_scenario() -> None:
    """Verify evaluation scoring of an individual scenario."""
    adapter = FakeLLMAdapter()
    db_latency_scenario = next(s for s in EVAL_SCENARIOS if s.key == "db_latency")

    score: ScenarioEvaluationScore = await evaluate_scenario(db_latency_scenario, adapter)

    assert score.scenario_key == "db_latency"
    assert score.predicted_cause == "db_latency"
    assert score.expected_cause == "db_latency"
    assert score.cause_match is True
    assert score.action_safe is True
    assert score.citation_validity == 1.0
    assert score.evidence_recall == 1.0
    assert score.overall_score == 100.0


@pytest.mark.asyncio
async def test_run_evaluations_full_suite() -> None:
    """Verify that running the evaluation benchmark achieves high score and full accuracy."""
    adapter = FakeLLMAdapter()
    report: BenchmarkReport = await run_evaluations(adapter=adapter)

    assert report.total_scenarios == len(EVAL_SCENARIOS)
    assert report.cause_accuracy == 100.0  # 100% accuracy on known scenarios
    assert report.action_safety == 100.0
    assert report.mean_evidence_recall == 100.0
    assert report.mean_overall_score >= 85.0
    assert report.total_tokens > 0
    assert report.model_name == adapter.model_name
    assert report.prompt_version == "1.0.0"


@pytest.mark.asyncio
async def test_benchmark_report_markdown() -> None:
    """Verify the generated Markdown benchmark report contains required summary tables."""
    adapter = FakeLLMAdapter()
    report: BenchmarkReport = await run_evaluations(adapter=adapter)
    markdown = report.to_markdown()

    assert "# Incident Response Evaluation Report" in markdown
    assert "**Model:** `fake-incident-reasoner-v1`" in markdown
    assert "**Prompt Version:** `1.0.0`" in markdown
    assert "| Scenario | Expected Cause | Predicted Cause |" in markdown
    assert "`db_latency`" in markdown
    assert "`bad_release`" in markdown
    assert "`ambiguous_jitter`" in markdown


@pytest.mark.asyncio
async def test_eval_handles_failing_model_gracefully() -> None:
    """Verify that a failing model does not crash the evaluation runner."""
    broken_adapter = FakeLLMAdapter(force_error="Upstream model crash")
    report = await run_evaluations(adapter=broken_adapter)

    assert report.total_scenarios == len(EVAL_SCENARIOS)
    # When model fails, causes are diagnosed as 'unknown'
    # Only ambiguous_jitter expects 'unknown'
    assert report.cause_accuracy <= 20.0
    assert report.mean_overall_score < 50.0
