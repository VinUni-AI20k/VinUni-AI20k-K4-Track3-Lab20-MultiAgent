"""Supervisor / router."""

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.state import ResearchState

logger = logging.getLogger(__name__)

NEXT_RESEARCHER = "researcher"
NEXT_ANALYST = "analyst"
NEXT_WRITER = "writer"
DONE = "done"


class SupervisorAgent(BaseAgent):
    """Decides which worker should run next and when to stop."""

    name = "supervisor"

    def run(self, state: ResearchState) -> ResearchState:
        route = self._decide(state, max_iterations=get_settings().max_iterations)
        state.record_route(route)
        state.add_trace_event("supervisor.route", {"next": route, "iteration": state.iteration})
        logger.info("supervisor.route next=%s iteration=%d", route, state.iteration)
        return state

    def _decide(self, state: ResearchState, max_iterations: int) -> str:
        """Route by which field of `ResearchState` is still missing.

        Deterministic and state-driven on purpose: it is cheap (no LLM call just
        to pick "what's next"), easy to unit test without mocking an LLM, and easy
        to debug from `state.route_history` alone.
        """

        # Guardrail #1: hard stop, checked first so no branch below can loop forever.
        if state.iteration >= max_iterations:
            return DONE

        # Guardrail #2: fallback — a worker already recorded an error but we still
        # have research notes to work with, so skip straight to Writer instead of
        # leaving the user with nothing.
        if state.errors and state.research_notes and not state.final_answer:
            return NEXT_WRITER

        if not state.sources:
            return NEXT_RESEARCHER
        if not state.analysis_notes:
            return NEXT_ANALYST
        if not state.final_answer:
            return NEXT_WRITER
        return DONE
