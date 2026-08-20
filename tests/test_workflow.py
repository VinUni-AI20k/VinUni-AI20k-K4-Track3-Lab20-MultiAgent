"""Integration tests for MultiAgentWorkflow (the LangGraph wiring).

Uses fake search/LLM clients injected into the real agents, so the graph
routing (supervisor -> worker -> supervisor -> ... -> done) is exercised
end-to-end without hitting OpenAI or the offline corpus.
"""

from multi_agent_research_lab.agents.analyst import AnalystAgent
from multi_agent_research_lab.agents.researcher import ResearcherAgent
from multi_agent_research_lab.agents.writer import WriterAgent
from multi_agent_research_lab.core.schemas import ResearchQuery, SourceDocument
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.graph.workflow import MultiAgentWorkflow
from multi_agent_research_lab.services.llm_client import LLMResponse

_DOC = SourceDocument(title="Doc A", url="https://example.com/a", snippet="snippet A")


class _FakeSearchClient:
    def __init__(self, docs: list[SourceDocument] | None = None) -> None:
        self._docs = [_DOC] if docs is None else docs

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        return self._docs[:max_results]


class _FakeLLMClient:
    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(content=self._content, input_tokens=5, output_tokens=5, cost_usd=0.0001)


def _build_workflow() -> MultiAgentWorkflow:
    return MultiAgentWorkflow(
        researcher=ResearcherAgent(search_client=_FakeSearchClient()),
        analyst=AnalystAgent(llm_client=_FakeLLMClient("key claim: X")),
        writer=WriterAgent(llm_client=_FakeLLMClient("Summary [1].")),
    )


def test_workflow_runs_full_pipeline_then_stops() -> None:
    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    result = _build_workflow().run(state)

    assert result.route_history == ["researcher", "analyst", "writer", "done"]
    assert result.sources == [_DOC]
    assert result.analysis_notes == "key claim: X"
    assert result.final_answer == "Summary [1]."
    assert result.errors == []
    # Business events (from each agent) interleaved with "node.<name>.timing"
    # events (added by the graph's timing wrapper around every node), plus a
    # final "workflow.done" once the whole graph.invoke() call returns.
    assert [event["name"] for event in result.trace] == [
        "supervisor.route",
        "node.supervisor.timing",
        "researcher.done",
        "node.researcher.timing",
        "supervisor.route",
        "node.supervisor.timing",
        "analyst.done",
        "node.analyst.timing",
        "supervisor.route",
        "node.supervisor.timing",
        "writer.done",
        "node.writer.timing",
        "supervisor.route",
        "node.supervisor.timing",
        "workflow.done",
    ]
    timing_events = [e for e in result.trace if e["name"].endswith(".timing")]
    assert all(e["payload"]["duration_seconds"] >= 0 for e in timing_events)
    assert result.trace[-1]["payload"]["duration_seconds"] >= 0


def test_workflow_returns_a_research_state_instance() -> None:
    # LangGraph's invoke() returns a plain dict for a Pydantic state schema;
    # MultiAgentWorkflow.run() must normalize that back before returning.
    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    result = _build_workflow().run(state)
    assert isinstance(result, ResearchState)


def test_workflow_stops_at_max_iterations_instead_of_looping_forever() -> None:
    workflow = MultiAgentWorkflow(researcher=ResearcherAgent(search_client=_FakeSearchClient([])))
    state = ResearchState(request=ResearchQuery(query="Explain multi-agent systems"))
    result = workflow.run(state)

    assert result.route_history[-1] == "done"
    assert result.route_history.count("researcher") == 6  # Settings.max_iterations default
