"""Unit tests for observability.tracing (span timing + LangSmith wiring)."""

import os
import time

import pytest

from multi_agent_research_lab.core.config import Settings
from multi_agent_research_lab.observability.tracing import configure_tracing, trace_span


def test_trace_span_records_duration_and_attributes() -> None:
    with trace_span("unit-test", {"k": "v"}) as span:
        time.sleep(0.01)

    assert span["name"] == "unit-test"
    assert span["attributes"] == {"k": "v"}
    assert span["duration_seconds"] is not None
    assert span["duration_seconds"] >= 0.01


def test_trace_span_records_duration_even_on_exception() -> None:
    span_ref: dict[str, object] = {}
    with pytest.raises(ValueError), trace_span("boom") as span:
        span_ref = span
        raise ValueError("simulated failure")

    assert span_ref["duration_seconds"] is not None


def test_configure_tracing_sets_langchain_env_when_key_present() -> None:
    # `configure_tracing` writes to `os.environ` directly (that's the point --
    # LangGraph/LangChain runnables read it at call time). `monkeypatch.delenv`
    # only registers teardown for variables it *finds already set*, so a var
    # that starts absent and gets set by the code under test (not by
    # monkeypatch itself) would otherwise leak into every later test in the
    # same pytest process -- including ones that build a real LangGraph graph,
    # which then tries to report to LangSmith using this test's fake key and
    # fails with a 403. Save/restore by hand instead of trusting monkeypatch.
    tracked_vars = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")
    saved = {name: os.environ.pop(name, None) for name in tracked_vars}
    try:
        settings = Settings(
            _env_file=None, langsmith_api_key="test-key", langsmith_project="test-proj"
        )
        enabled = configure_tracing(settings)

        assert enabled is True
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "test-key"
        assert os.environ["LANGCHAIN_PROJECT"] == "test-proj"
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_configure_tracing_is_noop_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    settings = Settings(_env_file=None, langsmith_api_key=None)
    enabled = configure_tracing(settings)

    assert enabled is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ
