"""LangGraph workflow: a supervisor-directed multi-agent graph.

Keep orchestration here; keep agent internals in `agents/`.
"""

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from multi_agent_research_lab.agents.analyst import AnalystAgent
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.agents.researcher import ResearcherAgent
from multi_agent_research_lab.agents.supervisor import (
    DONE,
    NEXT_ANALYST,
    NEXT_RESEARCHER,
    NEXT_WRITER,
    SupervisorAgent,
)
from multi_agent_research_lab.agents.writer import WriterAgent
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.observability.tracing import trace_span

_SUPERVISOR = "supervisor"


class MultiAgentWorkflow:
    """Builds and runs the multi-agent graph."""

    def __init__(
        self,
        supervisor: SupervisorAgent | None = None,
        researcher: ResearcherAgent | None = None,
        analyst: AnalystAgent | None = None,
        writer: WriterAgent | None = None,
    ) -> None:
        # Constructor injection: production code uses the defaults (real
        # OpenAI/corpus-backed agents); tests pass agents wired to fake
        # search/LLM clients so the graph can be exercised without API calls.
        self._supervisor = supervisor or SupervisorAgent()
        self._workers = {
            NEXT_RESEARCHER: researcher or ResearcherAgent(),
            NEXT_ANALYST: analyst or AnalystAgent(),
            NEXT_WRITER: writer or WriterAgent(),
        }
        self._graph = self.build()

    def build(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Wire the supervisor as a hub with the three workers as spokes.

        Workers never call each other directly; every worker edge returns to the
        supervisor, which is the single routing decision point (see
        `agents/supervisor.py`). The supervisor's own conditional edge is the only
        place `END` is reachable, driven by the route it just recorded.
        """

        builder = StateGraph(ResearchState)
        _add_timed_node(builder, _SUPERVISOR, self._supervisor)
        for route_name, agent in self._workers.items():
            _add_timed_node(builder, route_name, agent)
            builder.add_edge(route_name, _SUPERVISOR)

        builder.set_entry_point(_SUPERVISOR)
        builder.add_conditional_edges(
            _SUPERVISOR,
            _route_after_supervisor,
            {
                NEXT_RESEARCHER: NEXT_RESEARCHER,
                NEXT_ANALYST: NEXT_ANALYST,
                NEXT_WRITER: NEXT_WRITER,
                DONE: END,
            },
        )
        return builder.compile()

    def run(self, state: ResearchState) -> ResearchState:
        """Execute the graph and return the final state.

        LangGraph 1.x returns a plain dict from `invoke()` even when the graph's
        state schema is a Pydantic model (verified against the installed
        langgraph==1.2.11), so the result is normalized back into a
        `ResearchState` here rather than leaking a raw dict to callers.
        """

        with trace_span("workflow.run", {"query": state.request.query}) as span:
            result: Any = self._graph.invoke(state)

        normalized = (
            result if isinstance(result, ResearchState) else ResearchState.model_validate(result)
        )
        normalized.add_trace_event("workflow.done", {"duration_seconds": span["duration_seconds"]})
        return normalized


def _add_timed_node(
    builder: StateGraph[ResearchState, Any, Any, Any], name: str, agent: BaseAgent
) -> None:
    """Register `agent` as a node whose wall-clock duration lands in `state.trace`.

    Centralized here (not inside each agent) so every node gets the same
    timing instrumentation for free, and `agents/*.py` stays free of
    observability concerns per the "keep orchestration in graph/" split. The
    closure is registered directly (rather than returned from a helper typed
    as `Callable[...]`) because routing a node function through an explicit
    `Callable[[ResearchState], ResearchState]` return type defeats mypy's
    overload resolution for `StateGraph.add_node` (it infers `NodeInputT` as
    `Never` and rejects the call) — verified against langgraph==1.2.11's stubs.
    """

    def node(state: ResearchState) -> ResearchState:
        with trace_span(f"node.{name}") as span:
            state = agent.run(state)
        state.add_trace_event(f"node.{name}.timing", {"duration_seconds": span["duration_seconds"]})
        return state

    builder.add_node(name, node)


def _route_after_supervisor(state: ResearchState) -> str:
    return state.route_history[-1] if state.route_history else DONE
