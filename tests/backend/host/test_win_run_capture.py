"""Regression guard for the guided-capture host-pipeline proof (win_run_capture.main).

The scenarios drive the REAL host capture functions (session + widened watch + poll loop +
classify + Altium extract + stop/replace + timeout), so keeping main() green here guards the
whole pipeline on Linux; running the same module under real Windows Python (uv run python -m
stockroom.host.win_run_capture) is the Windows proof (plan Task 2.5)."""

from stockroom.host.win_run_capture import main


def test_win_run_capture_all_scenarios_pass():
    assert main() == 0
