"""M9d: the frozen-once launcher supervisor. The shell-outs (clone / uv sync / spawn the
host) are injected, so the relaunch-on-self-update loop is fully testable on Linux."""

from __future__ import annotations

from pathlib import Path

from stockroom.host.run import EXIT_RESTART
from stockroom.launcher.launch import app_workdir, ensure_clone, supervise


# -- app_workdir ---------------------------------------------------------------


def test_app_workdir_honors_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_APP_DIR", str(tmp_path / "app"))
    assert app_workdir() == tmp_path / "app"


def test_app_workdir_uses_localappdata_on_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_APP_DIR", raising=False)
    monkeypatch.setattr("stockroom.launcher.launch._os_name", lambda: "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert app_workdir() == tmp_path / "Local" / "Stockroom" / "app"


def test_app_workdir_uses_xdg_on_posix(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_APP_DIR", raising=False)
    monkeypatch.setattr("stockroom.launcher.launch._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert app_workdir() == tmp_path / "share" / "stockroom" / "app"


# -- ensure_clone --------------------------------------------------------------


def test_ensure_clone_skips_when_working_copy_present(tmp_path):
    (tmp_path / ".git").mkdir()
    calls = []
    ensure_clone(tmp_path, clone=lambda r, w: calls.append((r, w)))
    assert calls == []  # a present .git is never re-cloned


def test_ensure_clone_clones_when_absent(tmp_path):
    dest = tmp_path / "app"
    calls = []
    ensure_clone(dest, remote="REMOTE", clone=lambda r, w: calls.append((r, w)))
    assert calls == [("REMOTE", dest)]


# -- supervise (the self-update relaunch loop) ---------------------------------


def test_supervise_relaunches_on_restart_then_stops(tmp_path):
    counts = {"ensure": 0, "sync": 0, "spawn": 0}

    def spawn(_wd):
        counts["spawn"] += 1
        return EXIT_RESTART if counts["spawn"] < 3 else 0  # restart twice, then quit clean

    code = supervise(
        tmp_path,
        spawn=spawn,
        uv_sync=lambda _wd: counts.__setitem__("sync", counts["sync"] + 1),
        ensure=lambda _wd: counts.__setitem__("ensure", counts["ensure"] + 1),
    )
    assert code == 0
    assert counts["spawn"] == 3  # ran three times (two self-update restarts + the final)
    assert counts["sync"] == 3  # deps synced before every run
    assert counts["ensure"] == 1  # cloned/ensured exactly once, up front


def test_supervise_returns_the_host_exit_code(tmp_path):
    code = supervise(
        tmp_path, spawn=lambda _wd: 7, uv_sync=lambda _wd: None, ensure=lambda _wd: None
    )
    assert code == 7


def test_supervise_ensures_before_first_run(tmp_path):
    order = []
    supervise(
        tmp_path,
        spawn=lambda _wd: (order.append("spawn"), 0)[1],
        uv_sync=lambda _wd: order.append("sync"),
        ensure=lambda _wd: order.append("ensure"),
    )
    assert order == ["ensure", "sync", "spawn"]
