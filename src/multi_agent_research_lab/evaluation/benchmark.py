"""Benchmark harness for single-agent vs multi-agent runs."""

import re
from collections.abc import Callable
from time import perf_counter

from multi_agent_research_lab.core.schemas import BenchmarkMetrics, ResearchQuery
from multi_agent_research_lab.core.state import ResearchState

Runner = Callable[[str], ResearchState]

_CITATION_RE = re.compile(r"\[(\d+)\]")


def run_benchmark(
    run_name: str, query: str, runner: Runner
) -> tuple[ResearchState, BenchmarkMetrics]:
    """Run `runner(query)` and measure latency, cost, citation coverage, and failure.

    `quality_score` is intentionally left unset here: per `docs/peer_review_rubric.md`
    it is a 0-10 score from human (or explicitly labeled LLM-judge) review, not
    something this function should silently compute — fill it in on the returned
    `BenchmarkMetrics` after scoring.
    """

    started = perf_counter()
    try:
        state = runner(query)
        failed = bool(state.errors)
    except Exception as exc:  # noqa: BLE001 - one bad query must not abort the whole sweep
        # `query` is echoed into a fresh ResearchState so the failure is still
        # attributable to a specific run; pad it to satisfy ResearchQuery's own
        # min_length so a malformed/too-short query can't make this fallback
        # itself raise and defeat the point of the try/except.
        safe_query = query if len(query) >= 5 else query.ljust(5, ".")
        state = ResearchState(request=ResearchQuery(query=safe_query))
        state.errors.append(f"benchmark: runner raised {type(exc).__name__}: {exc}")
        failed = True
    latency = perf_counter() - started

    metrics = BenchmarkMetrics(
        run_name=run_name,
        latency_seconds=latency,
        estimated_cost_usd=_total_cost_usd(state),
        citation_coverage=_citation_coverage(state),
        failure_rate=1.0 if failed else 0.0,
        notes=f"iterations={state.iteration}, errors={len(state.errors)}",
    )
    return state, metrics


def _total_cost_usd(state: ResearchState) -> float | None:
    """Sum `cost_usd` recorded by each agent (see LLMClient.complete)."""

    known = [
        result.metadata["cost_usd"]
        for result in state.agent_results
        if result.metadata.get("cost_usd") is not None
    ]
    return sum(known) if known else None


def _citation_coverage(state: ResearchState) -> float | None:
    """Fraction of `state.sources` referenced as `[n]` in `state.final_answer`."""

    if not state.sources or not state.final_answer:
        return None
    cited = {int(match) for match in _CITATION_RE.findall(state.final_answer)}
    hits = sum(1 for i in range(1, len(state.sources) + 1) if i in cited)
    return hits / len(state.sources)
