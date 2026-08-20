"""Tracing hooks.

`trace_span` is a minimal, provider-agnostic span: it always works, even with no
tracing backend configured. `configure_tracing` layers a real backend (LangSmith)
on top when a key is available, without requiring any change inside `agents/` or
`graph/` — LangGraph's nodes are LangChain Runnables under the hood, so they pick
up the standard LANGCHAIN_* environment variables automatically.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Any

from multi_agent_research_lab.core.config import Settings

logger = logging.getLogger(__name__)


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Minimal span: records wall-clock duration around the wrapped block."""

    started = perf_counter()
    span: dict[str, Any] = {"name": name, "attributes": attributes or {}, "duration_seconds": None}
    try:
        yield span
    finally:
        span["duration_seconds"] = perf_counter() - started


def configure_tracing(settings: Settings) -> bool:
    """Enable LangSmith tracing for the LangGraph workflow, if a key is configured.

    Returns True if tracing was enabled, False if there is no LangSmith key (in
    which case only the local `trace_span`/`state.trace` mechanism is active).
    """

    if not settings.langsmith_api_key:
        logger.info("tracing.langsmith_disabled reason=no_api_key")
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    logger.info("tracing.langsmith_enabled project=%s", settings.langsmith_project)
    return True
