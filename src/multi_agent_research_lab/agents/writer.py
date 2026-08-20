"""Writer agent."""

import logging

from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a technical writer producing a final answer for the given audience. "
    "You MUST cite sources inline as [1], [2], ... matching the numbered source "
    "list provided in the prompt. Do not invent facts that are not present in the "
    "notes or sources. If the notes are thin, say so rather than fabricating detail."
)


class WriterAgent(BaseAgent):
    """Produces final answer from research and analysis notes."""

    name = "writer"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        context = state.analysis_notes or state.research_notes
        if not context:
            state.errors.append("writer: no notes available to write from")
            state.add_trace_event("writer.error", {"reason": "missing_notes"})
            logger.warning("writer.missing_notes")
            return state

        source_list = (
            "\n".join(
                f"[{i}] {s.title} "
                f"({s.url or s.metadata.get('source_id') or s.metadata.get('article_id') or 'n/a'})"
                for i, s in enumerate(state.sources, start=1)
            )
            or "(no sources collected)"
        )

        response = self._llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"Audience: {state.request.audience}\n"
                f"Query: {state.request.query}\n\n"
                f"Notes:\n{context}\n\n"
                f"Sources:\n{source_list}"
            ),
        )
        state.final_answer = response.content
        state.agent_results.append(
            AgentResult(
                agent=AgentName.WRITER,
                content=response.content,
                metadata={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": response.cost_usd,
                },
            )
        )
        state.add_trace_event("writer.done", {})
        logger.info("writer.done")
        return state
