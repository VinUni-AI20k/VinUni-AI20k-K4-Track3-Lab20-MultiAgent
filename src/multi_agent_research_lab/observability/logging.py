"""Logging setup."""

import logging


def configure_logging(level: str = "INFO") -> None:
    # force=True: without it, logging.basicConfig() is a silent no-op on every
    # call after the first one in a process (e.g. re-running a notebook cell
    # with a different level, or a test suite calling this more than once).
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        force=True,
    )
