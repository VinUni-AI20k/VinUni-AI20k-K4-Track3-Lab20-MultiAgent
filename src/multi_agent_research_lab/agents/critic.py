"""Optional critic agent for bonus work."""

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a fact-checking critic. Compare the final answer against the provided "
    "sources. List any claim that is not directly supported by a source, and any "
    "source listed but never cited. Be terse: one bullet per issue found, or say "
    "'No issues found.' if there are none."
)


class CriticAgent(BaseAgent):
    """Optional fact-checking and safety-review agent.

    Not wired into SupervisorAgent's routing by default (see design_template.md
    "Why multi-agent?" for the cost/quality trade-off) — instantiate and call
    directly, or add a route for it, when the extra verification pass is worth
    the added latency/cost.
    """

    name = "critic"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        if not state.final_answer:
            state.errors.append("critic: no final_answer to review")
            state.add_trace_event("critic.error", {"reason": "missing_final_answer"})
            logger.warning("critic.missing_final_answer")
            return state

        source_list = "\n".join(f"[{i}] {s.title}" for i, s in enumerate(state.sources, start=1))
        response = self._llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"Final answer:\n{state.final_answer}\n\nSources:\n{source_list}",
        )
        state.agent_results.append(AgentResult(agent=AgentName.CRITIC, content=response.content))
        state.add_trace_event("critic.done", {})
        logger.info("critic.done")
        return state
