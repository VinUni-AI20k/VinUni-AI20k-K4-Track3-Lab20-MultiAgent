"""Unit tests for observability.logging.configure_logging."""

import logging

from multi_agent_research_lab.observability.logging import configure_logging


def test_configure_logging_sets_root_level() -> None:
    original_level = logging.getLogger().level
    try:
        configure_logging("WARNING")
        assert logging.getLogger().level == logging.WARNING
    finally:
        configure_logging(
            "INFO" if original_level == logging.NOTSET else logging.getLevelName(original_level)
        )


def test_configure_logging_can_be_called_more_than_once_in_the_same_process() -> None:
    # Regression test: logging.basicConfig() is a silent no-op on every call
    # after the first one *unless* force=True is passed, since the root logger
    # already has a handler by then. Without force=True this would still show
    # the level from the first call (see docs/solution_walkthrough.md).
    original_level = logging.getLogger().level
    try:
        configure_logging("WARNING")
        assert logging.getLogger().level == logging.WARNING
        configure_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG
    finally:
        configure_logging(
            "INFO" if original_level == logging.NOTSET else logging.getLevelName(original_level)
        )


def test_configure_logging_defaults_to_info_for_an_unknown_level_name() -> None:
    original_level = logging.getLogger().level
    try:
        configure_logging("NOT_A_REAL_LEVEL")
        assert logging.getLogger().level == logging.INFO
    finally:
        configure_logging(
            "INFO" if original_level == logging.NOTSET else logging.getLevelName(original_level)
        )
