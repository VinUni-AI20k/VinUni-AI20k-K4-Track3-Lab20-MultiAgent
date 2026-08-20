"""Analyst agent."""

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a research analyst. Given research notes, extract the key claims, "
    "compare differing viewpoints, and explicitly flag any claim that looks weak "
    "or unsupported by the notes. Be concise and use short bullet points."
)


class AnalystAgent(BaseAgent):
    """Turns research notes into structured insights."""

    name = "analyst"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        if not state.sources or not state.research_notes:
            state.errors.append("analyst: no research notes to analyze")
            state.add_trace_event("analyst.error", {"reason": "missing_research_notes"})
            logger.warning("analyst.missing_research_notes")
            return state

        response = self._llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"Research query: {state.request.query}\n\nResearch notes:\n{state.research_notes}"
            ),
        )
        state.analysis_notes = response.content
        state.agent_results.append(
            AgentResult(
                agent=AgentName.ANALYST,
                content=response.content,
                metadata={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": response.cost_usd,
                },
            )
        )
        state.add_trace_event("analyst.done", {})
        logger.info("analyst.done")
        return state
