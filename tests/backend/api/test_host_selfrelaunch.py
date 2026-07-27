"""When nothing else will relaunch the host, the host relaunches itself.

THE OWNER'S ACTUAL FAILURE, 2026-07-27: *"my app still wont update even with latest files pulled"*.

The files WERE pulled -- that was never the problem. The update path is
`pull -> uv sync -> request_restart()`, and `request_restart` closes the window and exits with
`EXIT_RESTART` (42). Code 42 means "relaunch me", and the only thing that acts on it is
`launcher/launch.py`, the FROZEN `Stockroom.exe`.

MEASURED on the owner's machine: there is no `Stockroom.exe`, no shortcut, and the app is started
as `python -m stockroom.host.run`. So an update did exactly what it was told -- pulled, then
CLOSED -- and nothing brought it back. From their side that is indistinguishable from "the update
does nothing", and `AppUpdater` cheerfully returned `state=UPDATED, restart_requested=True` the
whole time: a success signal not wired to the fact it claims.

So `main()` stops assuming a supervisor exists. It relaunches itself, and only falls back to
exiting 42 when it genuinely cannot -- which is the case a real launcher is there to handle.
"""

from __future__ import annotations

import sys

import pytest

from stockroom.host import run as host_run
from stockroom.launcher.exit_codes import EXIT_RESTART


def test_a_restart_relaunches_the_host_instead_of_just_exiting(monkeypatch):
    monkeypatch.setattr(host_run, "run_windowed", lambda: True)
    spawned: list[list[str]] = []
    monkeypatch.setattr(host_run, "_spawn_self", lambda: spawned.append(sys.argv) or 0)

    with pytest.raises(SystemExit) as exit_info:
        host_run.main()

    assert spawned, "an update closed the window and nothing brought the app back"
    # The child's own exit code is what this process reports, so a chain of updates still works.
    assert exit_info.value.code == 0


def test_a_normal_quit_does_NOT_relaunch(monkeypatch):
    """NEGATIVE CONTROL, and the one that matters most: closing the window must CLOSE the app.
    A relaunch on every exit would make the app impossible to quit."""
    monkeypatch.setattr(host_run, "run_windowed", lambda: False)
    spawned: list[str] = []
    monkeypatch.setattr(host_run, "_spawn_self", lambda: spawned.append("x") or 0)

    host_run.main()

    assert spawned == []


def test_when_it_cannot_relaunch_it_exits_42_so_a_real_launcher_still_works(monkeypatch):
    """The frozen `Stockroom.exe` supervises the host and relaunches on 42. Self-relaunch must not
    take that away: if spawning fails for any reason, fall back to the contract the launcher
    already speaks rather than dying silently."""
    monkeypatch.setattr(host_run, "run_windowed", lambda: True)

    def _boom() -> int:
        raise OSError("no python to spawn")

    monkeypatch.setattr(host_run, "_spawn_self", _boom)

    with pytest.raises(SystemExit) as exit_info:
        host_run.main()

    assert exit_info.value.code == EXIT_RESTART


def test_the_relaunch_reuses_this_interpreter_and_module(monkeypatch):
    """It must come back as the SAME app: the install's own venv python and the same module.
    Resolving either from PATH would relaunch whatever python happens to be first, which on this
    machine is not the install's."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        host_run.subprocess, "call", lambda cmd, **kw: calls.append((cmd, kw)) or 0
    )

    host_run._spawn_self()

    (cmd, _kw) = calls[0]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "stockroom.host.run"]
