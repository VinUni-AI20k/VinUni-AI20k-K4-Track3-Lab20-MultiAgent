from multi_agent_research_lab.core.schemas import BenchmarkMetrics
from multi_agent_research_lab.evaluation.report import render_markdown_report


def test_report_renders_markdown() -> None:
    report = render_markdown_report([BenchmarkMetrics(run_name="baseline", latency_seconds=1.23)])
    assert "Benchmark Report" in report
    assert "baseline" in report


def test_report_includes_summary_and_trace_path() -> None:
    metrics = [
        BenchmarkMetrics(run_name="a", latency_seconds=1.0, estimated_cost_usd=0.01),
        BenchmarkMetrics(run_name="b", latency_seconds=2.0, failure_rate=1.0),
    ]
    report = render_markdown_report(metrics, trace_path="reports/trace_latest.json")
    assert "## Summary" in report
    assert "2 run(s), 1 failed" in report
    assert "reports/trace_latest.json" in report


def test_report_handles_empty_metrics_list() -> None:
    report = render_markdown_report([])
    assert "No runs recorded" in report
