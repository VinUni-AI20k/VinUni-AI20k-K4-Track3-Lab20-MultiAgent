"""Unit tests for evaluation.benchmark.run_benchmark."""

import pytest

from multi_agent_research_lab.core.schemas import (
    AgentName,
    AgentResult,
    ResearchQuery,
    SourceDocument,
)
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.evaluation.benchmark import run_benchmark

_DOC = SourceDocument(title="Doc A", snippet="s")


def _successful_runner(query: str) -> ResearchState:
    state = ResearchState(request=ResearchQuery(query=query))
    state.sources = [_DOC, _DOC]
    state.final_answer = "Summary [1]."
    state.agent_results = [
        AgentResult(agent=AgentName.WRITER, content="x", metadata={"cost_usd": 0.001}),
        AgentResult(agent=AgentName.ANALYST, content="y", metadata={"cost_usd": 0.002}),
    ]
    return state


def test_run_benchmark_measures_latency() -> None:
    _, metrics = run_benchmark("run", "Explain multi-agent systems", _successful_runner)
    assert metrics.run_name == "run"
    assert metrics.latency_seconds >= 0


def test_run_benchmark_sums_cost_from_agent_results() -> None:
    _, metrics = run_benchmark("run", "Explain multi-agent systems", _successful_runner)
    assert metrics.estimated_cost_usd == pytest.approx(0.003)


def test_run_benchmark_computes_citation_coverage() -> None:
    # 2 sources, only [1] is cited in the final answer -> 0.5 coverage.
    _, metrics = run_benchmark("run", "Explain multi-agent systems", _successful_runner)
    assert metrics.citation_coverage == 0.5


def test_run_benchmark_leaves_quality_score_unset() -> None:
    # Quality is a human/peer-review score (docs/peer_review_rubric.md), not
    # something run_benchmark should silently compute.
    _, metrics = run_benchmark("run", "Explain multi-agent systems", _successful_runner)
    assert metrics.quality_score is None


def test_run_benchmark_marks_failure_when_state_has_errors() -> None:
    def failing_runner(query: str) -> ResearchState:
        state = ResearchState(request=ResearchQuery(query=query))
        state.errors.append("boom")
        return state

    _, metrics = run_benchmark("run", "Explain multi-agent systems", failing_runner)
    assert metrics.failure_rate == 1.0


def test_run_benchmark_catches_runner_exceptions_instead_of_aborting() -> None:
    def crashing_runner(query: str) -> ResearchState:
        raise RuntimeError("simulated crash")

    state, metrics = run_benchmark("run", "Explain multi-agent systems", crashing_runner)
    assert metrics.failure_rate == 1.0
    assert state.errors
    assert "simulated crash" in state.errors[0]


def test_run_benchmark_exception_fallback_survives_a_too_short_query() -> None:
    # ResearchQuery requires min_length=5. If the crash-recovery branch in
    # run_benchmark re-validated the *original* query verbatim, a query this
    # short would make the fallback's own ResearchQuery(...) construction raise
    # -- defeating the whole point of catching the runner's exception.
    def crashing_runner(query: str) -> ResearchState:
        raise RuntimeError("boom")

    state, metrics = run_benchmark("run", "hi", crashing_runner)
    assert metrics.failure_rate == 1.0
    assert "boom" in state.errors[0]


def test_run_benchmark_cost_is_none_when_no_agent_recorded_cost() -> None:
    def no_cost_runner(query: str) -> ResearchState:
        return ResearchState(request=ResearchQuery(query=query))

    _, metrics = run_benchmark("run", "Explain multi-agent systems", no_cost_runner)
    assert metrics.estimated_cost_usd is None
    assert metrics.citation_coverage is None
