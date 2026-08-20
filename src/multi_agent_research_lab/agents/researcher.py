"""Researcher agent."""

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.search_client import SearchClient

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    """Collects sources and creates concise research notes."""

    name = "researcher"

    def __init__(self, search_client: SearchClient | None = None) -> None:
        self._search_client = search_client or SearchClient()

    def run(self, state: ResearchState) -> ResearchState:
        docs = self._search_client.search(
            state.request.query, max_results=state.request.max_sources
        )
        if not docs:
            state.errors.append("researcher: search returned no sources")
            state.add_trace_event("researcher.error", {"reason": "empty_results"})
            logger.warning("researcher.empty_results query=%r", state.request.query)
            return state

        state.sources = docs
        state.research_notes = "\n".join(f"- {d.title}: {d.snippet}" for d in docs)
        state.agent_results.append(
            AgentResult(
                agent=AgentName.RESEARCHER,
                content=state.research_notes,
                metadata={"num_sources": len(docs)},
            )
        )
        state.add_trace_event("researcher.done", {"num_sources": len(docs)})
        logger.info("researcher.done num_sources=%d", len(docs))
        return state
