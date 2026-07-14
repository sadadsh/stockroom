"""M9d: the frozen-once launcher supervisor. The shell-outs (clone / uv sync / spawn the
host) are injected, so the relaunch-on-self-update loop is fully testable on Linux."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stockroom.host.run import EXIT_RESTART
from stockroom.launcher import launch
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


# -- uv resolution (the bundled-uv WinError 2 fix) + git preflight --------------


def test_uv_bin_uses_path_when_not_frozen(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    assert launch._uv_bin() == "uv"


def test_uv_bin_prefers_the_bundled_uv_when_frozen(monkeypatch, tmp_path):
    name = "uv.exe" if os.name == "nt" else "uv"
    (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launch._uv_bin() == str(tmp_path / name)


def test_uv_bin_falls_back_to_path_when_bundle_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)  # empty dir
    assert launch._uv_bin() == "uv"


def test_git_bin_uses_path_when_not_frozen(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    assert launch._git_bin() == "git"


def test_git_bin_prefers_bundled_mingit_when_frozen(monkeypatch, tmp_path):
    name = "git.exe" if os.name == "nt" else "git"
    (tmp_path / "mingit" / "cmd").mkdir(parents=True)
    (tmp_path / "mingit" / "cmd" / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launch._git_bin() == str(tmp_path / "mingit" / "cmd" / name)


def test_git_bin_falls_back_to_path_when_mingit_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launch._git_bin() == "git"


def test_require_git_raises_a_readable_error_when_git_absent(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    monkeypatch.setattr(launch.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="git"):
        launch._require_git()


def test_require_git_passes_when_git_present(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    monkeypatch.setattr(launch.shutil, "which", lambda _name: "/usr/bin/git")
    launch._require_git()  # no raise


def test_require_git_ok_with_bundled_git_even_without_path_git(monkeypatch, tmp_path):
    # a frozen exe carries its own git, so it must NOT require a system git on PATH
    name = "git.exe" if os.name == "nt" else "git"
    (tmp_path / "mingit" / "cmd").mkdir(parents=True)
    (tmp_path / "mingit" / "cmd" / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(launch.shutil, "which", lambda _n: None)
    launch._require_git()  # no raise (bundled git present)


def test_child_env_prepends_bundled_git_dirs_when_frozen(monkeypatch, tmp_path):
    (tmp_path / "mingit" / "cmd").mkdir(parents=True)
    (tmp_path / "mingit" / "bin").mkdir(parents=True)
    monkeypatch.setattr(launch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launch.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PATH", "/orig")
    env = launch._child_env()
    assert str(tmp_path / "mingit" / "cmd") in env["PATH"]
    assert env["PATH"].endswith("/orig")  # the machine PATH is preserved after the bundle dirs


def test_child_env_unchanged_on_a_source_run(monkeypatch):
    monkeypatch.setattr(launch.sys, "frozen", False, raising=False)
    monkeypatch.setenv("PATH", "/orig")
    assert launch._child_env()["PATH"] == "/orig"


def test_supervise_ensures_before_first_run(tmp_path):
    order = []
    supervise(
        tmp_path,
        spawn=lambda _wd: (order.append("spawn"), 0)[1],
        uv_sync=lambda _wd: order.append("sync"),
        ensure=lambda _wd: order.append("ensure"),
    )
    assert order == ["ensure", "sync", "spawn"]
