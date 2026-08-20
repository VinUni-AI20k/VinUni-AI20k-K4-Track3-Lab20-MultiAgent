"""LLM client abstraction.

Production note: agents should depend on this interface instead of importing an SDK directly.
"""

import logging
from dataclasses import dataclass

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.errors import AgentExecutionError

logger = logging.getLogger(__name__)

# Reference pricing (USD per 1K tokens). Kept separate from call logic so it is easy
# to update without touching retry/timeout behavior. Extend as new models are used.
_PRICE_PER_1K_USD: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
}


@dataclass(frozen=True)
class LLMResponse:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMClient:
    """Provider-agnostic LLM client backed by the OpenAI Chat Completions API."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise AgentExecutionError(
                "OPENAI_API_KEY is not set. Add it to .env before calling LLMClient.complete."
            )
        self._model = settings.openai_model
        self._timeout_seconds = settings.timeout_seconds
        self._client = OpenAI(api_key=settings.openai_api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Call the chat completion endpoint once, with retry/timeout/cost handling."""

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self._timeout_seconds,
        )

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage

        input_tokens = usage.prompt_tokens if usage else None
        output_tokens = usage.completion_tokens if usage else None
        cost_usd = self._estimate_cost(input_tokens, output_tokens)

        logger.info(
            "llm.complete model=%s input_tokens=%s output_tokens=%s cost_usd=%s",
            self._model,
            input_tokens,
            output_tokens,
            cost_usd,
        )

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )

    def _estimate_cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        price = _PRICE_PER_1K_USD.get(self._model)
        if price is None or input_tokens is None or output_tokens is None:
            return None
        return (input_tokens / 1000) * price["input"] + (output_tokens / 1000) * price["output"]
