"""Benchmark report rendering."""

from datetime import UTC, datetime

from multi_agent_research_lab.core.schemas import BenchmarkMetrics


def render_markdown_report(metrics: list[BenchmarkMetrics], trace_path: str | None = None) -> str:
    """Render benchmark metrics to a markdown report: summary section + run table."""

    lines = [
        "# Benchmark Report",
        "",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    if trace_path:
        lines += [f"Trace: `{trace_path}`", ""]

    lines += _summary_lines(metrics)

    lines += [
        "## Runs",
        "",
        "| Run | Latency (s) | Cost (USD) | Quality | Citation cov. | Failure rate | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in metrics:
        cost = "" if item.estimated_cost_usd is None else f"{item.estimated_cost_usd:.4f}"
        quality = "" if item.quality_score is None else f"{item.quality_score:.1f}"
        citation = "" if item.citation_coverage is None else f"{item.citation_coverage:.0%}"
        failure = "" if item.failure_rate is None else f"{item.failure_rate:.0%}"
        lines.append(
            f"| {item.run_name} | {item.latency_seconds:.2f} | {cost} | {quality} "
            f"| {citation} | {failure} | {item.notes} |"
        )
    return "\n".join(lines) + "\n"


def _summary_lines(metrics: list[BenchmarkMetrics]) -> list[str]:
    if not metrics:
        return ["## Summary", "", "No runs recorded.", ""]

    avg_latency = sum(m.latency_seconds for m in metrics) / len(metrics)
    known_costs = [m.estimated_cost_usd for m in metrics if m.estimated_cost_usd is not None]
    failed = sum(1 for m in metrics if (m.failure_rate or 0) > 0)

    lines = [
        "## Summary",
        "",
        f"- {len(metrics)} run(s), {failed} failed.",
        f"- Average latency: {avg_latency:.2f}s.",
    ]
    if known_costs:
        lines.append(f"- Total estimated cost: ${sum(known_costs):.4f}.")
    lines.append("")
    return lines
