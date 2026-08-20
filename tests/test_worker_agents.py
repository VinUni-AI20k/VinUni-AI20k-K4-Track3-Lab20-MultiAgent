"""Unit tests for the worker agents (Researcher, Analyst, Writer, Critic).

Uses fake search/LLM clients that satisfy the same `search()`/`complete()`
duck-typed interface as the real services, so these tests run offline,
deterministically, and without spending API credits.
"""

from multi_agent_research_lab.agents.analyst import AnalystAgent
from multi_agent_research_lab.agents.critic import CriticAgent
from multi_agent_research_lab.agents.researcher import ResearcherAgent
from multi_agent_research_lab.agents.writer import WriterAgent
from multi_agent_research_lab.core.schemas import AgentName, ResearchQuery, SourceDocument
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMResponse

_DOC = SourceDocument(title="Doc A", url="https://example.com/a", snippet="snippet A")


class _FakeSearchClient:
    def __init__(self, docs: list[SourceDocument]) -> None:
        self._docs = docs

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        return self._docs[:max_results]


class _FakeLLMClient:
    def __init__(self, content: str = "fake response") -> None:
        self._content = content
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.calls.append((system_prompt, user_prompt))
        return LLMResponse(content=self._content, input_tokens=10, output_tokens=20, cost_usd=0.001)


def _state(**overrides: object) -> ResearchState:
    return ResearchState(request=ResearchQuery(query="Explain multi-agent systems"), **overrides)


def test_researcher_populates_sources_and_notes() -> None:
    state = ResearcherAgent(search_client=_FakeSearchClient([_DOC])).run(_state())
    assert state.sources == [_DOC]
    assert "Doc A" in (state.research_notes or "")
    assert state.agent_results[-1].agent == AgentName.RESEARCHER
    assert state.trace[-1]["name"] == "researcher.done"


def test_researcher_records_error_when_no_sources_found() -> None:
    state = ResearcherAgent(search_client=_FakeSearchClient([])).run(_state())
    assert state.sources == []
    assert state.errors
    assert state.trace[-1]["name"] == "researcher.error"


def test_analyst_populates_analysis_notes() -> None:
    fake_llm = _FakeLLMClient(content="key claim: X")
    state = _state(sources=[_DOC], research_notes="- Doc A: snippet A")
    state = AnalystAgent(llm_client=fake_llm).run(state)
    assert state.analysis_notes == "key claim: X"
    assert state.agent_results[-1].agent == AgentName.ANALYST
    assert len(fake_llm.calls) == 1


def test_analyst_guards_against_missing_research_notes() -> None:
    state = AnalystAgent(llm_client=_FakeLLMClient()).run(_state())
    assert state.analysis_notes is None
    assert state.errors


def test_writer_produces_final_answer_with_citations() -> None:
    fake_llm = _FakeLLMClient(content="Summary [1].")
    state = _state(sources=[_DOC], analysis_notes="key claim: X")
    state = WriterAgent(llm_client=fake_llm).run(state)
    assert state.final_answer == "Summary [1]."
    assert state.agent_results[-1].agent == AgentName.WRITER
    _, user_prompt = fake_llm.calls[0]
    assert "[1] Doc A" in user_prompt


def test_writer_falls_back_to_research_notes_when_no_analysis() -> None:
    fake_llm = _FakeLLMClient(content="Summary [1].")
    state = _state(sources=[_DOC], research_notes="- Doc A: snippet A")
    state = WriterAgent(llm_client=fake_llm).run(state)
    assert state.final_answer == "Summary [1]."


def test_writer_guards_against_no_notes_at_all() -> None:
    state = WriterAgent(llm_client=_FakeLLMClient()).run(_state())
    assert state.final_answer is None
    assert state.errors


def test_critic_reviews_final_answer() -> None:
    fake_llm = _FakeLLMClient(content="No issues found.")
    state = _state(sources=[_DOC], final_answer="Summary [1].")
    state = CriticAgent(llm_client=fake_llm).run(state)
    assert state.agent_results[-1].agent == AgentName.CRITIC
    assert state.agent_results[-1].content == "No issues found."


def test_critic_guards_against_missing_final_answer() -> None:
    state = CriticAgent(llm_client=_FakeLLMClient()).run(_state())
    assert state.errors
