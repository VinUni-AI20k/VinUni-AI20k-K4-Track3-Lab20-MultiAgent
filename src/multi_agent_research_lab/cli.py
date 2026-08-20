"""Command-line entrypoint for the lab starter."""

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.errors import AgentExecutionError, StudentTodoError
from multi_agent_research_lab.core.schemas import (
    AgentName,
    AgentResult,
    BenchmarkMetrics,
    ResearchQuery,
)
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.evaluation.benchmark import run_benchmark
from multi_agent_research_lab.evaluation.report import render_markdown_report
from multi_agent_research_lab.graph.workflow import MultiAgentWorkflow
from multi_agent_research_lab.observability.logging import configure_logging
from multi_agent_research_lab.observability.tracing import configure_tracing
from multi_agent_research_lab.services.llm_client import LLMClient
from multi_agent_research_lab.services.storage import LocalArtifactStore

app = typer.Typer(help="Multi-Agent Research Lab starter CLI")
console = Console()


def _init() -> bool:
    settings = get_settings()
    configure_logging(settings.log_level)
    return configure_tracing(settings)


def _parse_query(query: str) -> ResearchQuery:
    try:
        return ResearchQuery(query=query)
    except ValidationError as exc:
        console.print(
            Panel.fit(
                f"Invalid query: {exc.errors()[0]['msg']}",
                title="Input Error",
                style="red",
            )
        )
        raise typer.Exit(code=1) from exc


def _run_single_agent(query_text: str) -> ResearchState:
    """Baseline runner: a single LLM call, no search, no worker handoff.

    Plain function of `str -> ResearchState` (not a Typer command) so it can be
    reused both by the `baseline` command and as a `Runner` passed to
    `evaluation.benchmark.run_benchmark`.
    """

    state = ResearchState(request=ResearchQuery(query=query_text))
    llm = LLMClient()
    response = llm.complete(
        system_prompt=(
            "You are a research assistant. Answer the query directly and concisely. "
            "Do not fabricate sources or citations."
        ),
        user_prompt=query_text,
    )
    state.final_answer = response.content
    state.agent_results.append(
        AgentResult(
            agent=AgentName.WRITER,
            content=response.content,
            metadata={
                "mode": "single_agent_baseline",
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
            },
        )
    )
    return state


def _run_multi_agent(query_text: str) -> ResearchState:
    """Multi-agent runner: same `str -> ResearchState` shape as `_run_single_agent`."""

    state = ResearchState(request=ResearchQuery(query=query_text))
    return MultiAgentWorkflow().run(state)


@app.command()
def baseline(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
) -> None:
    """Run a single-agent baseline: one LLM call, no search, no worker handoff."""

    _init()
    request = _parse_query(query)
    try:
        state = _run_single_agent(request.query)
    except AgentExecutionError as exc:
        console.print(Panel.fit(str(exc), title="Baseline Error", style="red"))
        raise typer.Exit(code=1) from exc

    console.print(Panel.fit(state.final_answer or "", title="Single-Agent Baseline"))


@app.command("multi-agent")
def multi_agent(
    query: Annotated[str, typer.Option("--query", "-q", help="Research query")],
) -> None:
    """Run the multi-agent workflow: Supervisor routing Researcher/Analyst/Writer."""

    tracing_enabled = _init()
    state = ResearchState(request=_parse_query(query))
    workflow = MultiAgentWorkflow()
    try:
        result = workflow.run(state)
    except StudentTodoError as exc:
        console.print(Panel.fit(str(exc), title="Expected TODO", style="yellow"))
        raise typer.Exit(code=2) from exc

    console.print(result.model_dump_json(indent=2))

    trace_path = LocalArtifactStore().write_text(
        "trace_latest.json", json.dumps(result.trace, indent=2)
    )
    tracing_note = (
        f"LangSmith tracing enabled (project={get_settings().langsmith_project})"
        if tracing_enabled
        else "LangSmith tracing disabled (no LANGSMITH_API_KEY) — local trace only"
    )
    console.print(Panel.fit(f"Trace written to {trace_path}\n{tracing_note}", title="Trace"))


@app.command()
def benchmark(
    config_path: Annotated[
        str, typer.Option("--config", help="YAML file with benchmark.queries")
    ] = "configs/lab_default.yaml",
) -> None:
    """Run single-agent vs multi-agent across configured queries; write a report."""

    _init()
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    queries: list[str] = config["benchmark"]["queries"]

    all_metrics: list[BenchmarkMetrics] = []
    for query_text in queries:
        for mode_name, runner in (
            ("single_agent", _run_single_agent),
            ("multi_agent", _run_multi_agent),
        ):
            run_name = f"{mode_name}::{query_text[:40]}"
            console.print(f"Running {run_name}...")
            _, metrics = run_benchmark(run_name, query_text, runner)
            all_metrics.append(metrics)

    report_md = render_markdown_report(all_metrics, trace_path="reports/trace_latest.json")
    report_path = LocalArtifactStore().write_text("benchmark_report.md", report_md)
    console.print(Panel.fit(f"Benchmark report written to {report_path}", title="Benchmark"))


if __name__ == "__main__":
    app()
