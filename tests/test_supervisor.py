"""Unit tests for SupervisorAgent's routing policy.

Replaces the old skeleton guard test (`test_agents_todo.py`), which only
asserted that SupervisorAgent.run() raised StudentTodoError. Now that routing
is implemented, these tests assert the actual policy instead.
"""

from multi_agent_research_lab.agents.supervisor import (
    DONE,
    NEXT_ANALYST,
    NEXT_RESEARCHER,
    NEXT_WRITER,
    SupervisorAgent,
)
from multi_agent_research_lab.core.schemas import ResearchQuery, SourceDocument
from multi_agent_research_lab.core.state import ResearchState


def _state(**overrides: object) -> ResearchState:
    return ResearchState(request=ResearchQuery(query="Explain multi-agent systems"), **overrides)


def test_routes_to_researcher_when_no_sources() -> None:
    state = SupervisorAgent().run(_state())
    assert state.route_history == [NEXT_RESEARCHER]
    assert state.iteration == 1


def test_routes_to_analyst_when_sources_but_no_analysis() -> None:
    state = _state(sources=[SourceDocument(title="t", snippet="s")])
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == NEXT_ANALYST


def test_routes_to_writer_when_analysis_but_no_final_answer() -> None:
    state = _state(
        sources=[SourceDocument(title="t", snippet="s")],
        analysis_notes="key claims...",
    )
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == NEXT_WRITER


def test_routes_to_done_when_final_answer_present() -> None:
    state = _state(
        sources=[SourceDocument(title="t", snippet="s")],
        analysis_notes="key claims...",
        final_answer="the answer",
    )
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == DONE


def test_stops_at_max_iterations_even_if_incomplete() -> None:
    state = _state(iteration=6)  # equals Settings.max_iterations default
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == DONE


def test_falls_back_to_writer_when_analyst_failed_but_notes_exist() -> None:
    state = _state(
        sources=[SourceDocument(title="t", snippet="s")],
        research_notes="raw findings...",
        errors=["analyst: llm call failed"],
    )
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == NEXT_WRITER


def test_records_trace_event_for_every_route() -> None:
    state = SupervisorAgent().run(_state())
    assert state.trace[-1]["name"] == "supervisor.route"
    assert state.trace[-1]["payload"]["next"] == NEXT_RESEARCHER
