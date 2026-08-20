"""Unit tests for utils.timer.elapsed_timer."""

import time

from multi_agent_research_lab.utils.timer import elapsed_timer


def test_elapsed_timer_reports_increasing_duration() -> None:
    with elapsed_timer() as elapsed:
        first = elapsed()
        time.sleep(0.01)
        second = elapsed()

    assert 0 <= first <= second
    assert second >= 0.01


def test_elapsed_timer_keeps_advancing_after_the_with_block() -> None:
    with elapsed_timer() as elapsed:
        pass
    at_exit = elapsed()
    time.sleep(0.01)
    later = elapsed()
    assert later > at_exit
