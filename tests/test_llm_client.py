"""Unit tests for services.llm_client.LLMClient.

`get_settings` is monkeypatched (never real network calls, never the real
OpenAI SDK client) so these tests are free, offline, and deterministic.
"""

from unittest.mock import MagicMock

import pytest

from multi_agent_research_lab.core.config import Settings
from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.services.llm_client import LLMClient


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "openai_api_key": "sk-test",
        "openai_model": "gpt-4o-mini",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    monkeypatch.setattr(
        "multi_agent_research_lab.services.llm_client.get_settings",
        lambda: _settings(**overrides),
    )


def test_constructor_raises_agent_execution_error_without_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, openai_api_key=None)
    with pytest.raises(AgentExecutionError):
        LLMClient()


def test_constructor_succeeds_with_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    LLMClient()  # must not raise


def _client_with_fake_openai_response(
    monkeypatch: pytest.MonkeyPatch, content: str, prompt_tokens: int, completion_tokens: int
) -> LLMClient:
    _patch_settings(monkeypatch)
    client = LLMClient()
    fake_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))],
        usage=MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )
    client._client = MagicMock()  # type: ignore[attr-defined]
    client._client.chat.completions.create.return_value = fake_response  # type: ignore[attr-defined]
    return client


def test_complete_parses_content_and_token_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_fake_openai_response(
        monkeypatch, content="hello world", prompt_tokens=1000, completion_tokens=1000
    )
    result = client.complete(system_prompt="sys", user_prompt="user")

    assert result.content == "hello world"
    assert result.input_tokens == 1000
    assert result.output_tokens == 1000


def test_complete_estimates_cost_from_known_model_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_fake_openai_response(
        monkeypatch, content="x", prompt_tokens=1000, completion_tokens=1000
    )
    result = client.complete(system_prompt="sys", user_prompt="user")

    # gpt-4o-mini: $0.00015/1K input + $0.0006/1K output -> 1000 tokens each.
    assert result.cost_usd == pytest.approx(0.00015 + 0.0006)


def test_complete_cost_is_none_for_a_model_without_known_pricing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settings(monkeypatch, openai_model="some-unpriced-model")
    client = LLMClient()
    fake_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content="x"))],
        usage=MagicMock(prompt_tokens=10, completion_tokens=10),
    )
    client._client = MagicMock()  # type: ignore[attr-defined]
    client._client.chat.completions.create.return_value = fake_response  # type: ignore[attr-defined]

    result = client.complete(system_prompt="sys", user_prompt="user")
    assert result.cost_usd is None
