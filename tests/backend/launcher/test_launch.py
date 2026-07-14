"""M9d: the frozen-once launcher supervisor. The shell-outs (clone / uv sync / spawn the
host) are injected, so the relaunch-on-self-update loop is fully testable on Linux."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from stockroom.host.run import EXIT_RESTART
from stockroom.launcher import launch, splash
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


def test_ensure_clone_clears_a_partial_non_git_dir_then_clones(tmp_path):
    # A leftover / partial dir (e.g. a stray .venv from a failed provision) has no .git; a real
    # git clone refuses a non-empty destination, so ensure_clone must clear it first and recover.
    dest = tmp_path / "app"
    (dest / ".venv").mkdir(parents=True)
    (dest / "leftover.txt").write_text("x", encoding="utf-8")
    calls = []

    def fake_clone(_remote, workdir):
        calls.append(workdir)
        (Path(workdir) / ".git").mkdir(parents=True)  # stand in for the real clone

    ensure_clone(dest, remote="R", clone=fake_clone)
    assert calls == [dest]
    assert not (dest / ".venv").exists()  # the partial contents were cleared before cloning
    assert not (dest / "leftover.txt").exists()


def test_ensure_clone_preserves_added_library_parts_across_a_recovery(tmp_path):
    # review #5: a corrupt checkout (no .git) that carries in-tree library parts must NOT lose them
    # on the re-clone; the part FILES are overlaid back onto the fresh (seed-only) clone.
    dest = tmp_path / "app"
    parts = dest / "libraries" / "Main" / "parts"
    parts.mkdir(parents=True)
    (parts / "myR.json").write_text('{"id":"myR"}', encoding="utf-8")
    (parts / ".gitkeep").write_text("", encoding="utf-8")

    def fake_clone(_remote, workdir):
        p = Path(workdir) / "libraries" / "Main" / "parts"  # a fresh clone ships only the seed
        p.mkdir(parents=True)
        (p / ".gitkeep").write_text("", encoding="utf-8")
        (Path(workdir) / ".git").mkdir(parents=True)

    ensure_clone(dest, remote="R", clone=fake_clone)
    assert (parts / "myR.json").read_text(encoding="utf-8") == '{"id":"myR"}'  # part survived
    assert not (tmp_path / ".stockroom-recovered-library").exists()  # backup cleaned up


def test_reconcile_pull_rebases_local_library_commits_onto_remote_app_updates(tmp_path):
    # review #4 (HIGH): once a part is added locally, a remote app-code update must STILL apply.
    # ff-only would get permanently stuck; the rebase reconcile replays the local library commit
    # (libraries/, a disjoint path) on top of the new app code so BOTH survive.
    git = shutil.which("git")
    if git is None:
        pytest.skip("git not installed")

    def g(repo, *args):
        return subprocess.run([git, "-C", str(repo), *args], capture_output=True, text=True)

    origin = tmp_path / "origin.git"
    subprocess.run([git, "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run([git, "clone", str(origin), str(seed)], check=True, capture_output=True)
    g(seed, "config", "user.email", "t@t"); g(seed, "config", "user.name", "t")
    (seed / "app").mkdir()
    (seed / "app" / "main.py").write_text("v1", encoding="utf-8")
    g(seed, "add", "."); g(seed, "commit", "-m", "app v1"); g(seed, "push", "-u", "origin", "main")

    managed = tmp_path / "A"
    subprocess.run([git, "clone", str(origin), str(managed)], check=True, capture_output=True)
    g(managed, "config", "user.email", "a@a"); g(managed, "config", "user.name", "a")
    (managed / "libraries" / "Main" / "parts").mkdir(parents=True)
    (managed / "libraries" / "Main" / "parts" / "r10k.json").write_text('{"id":"r10k"}', encoding="utf-8")
    g(managed, "add", "."); g(managed, "commit", "-m", "add r10k")

    (seed / "app" / "main.py").write_text("v2", encoding="utf-8")  # a remote app-code update
    g(seed, "add", "."); g(seed, "commit", "-m", "app v2"); g(seed, "push")

    launch._reconcile_pull(managed, git)
    assert (managed / "app" / "main.py").read_text(encoding="utf-8") == "v2"  # remote update applied
    assert (managed / "libraries" / "Main" / "parts" / "r10k.json").exists()  # local part preserved


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


# -- WebView2 runtime guarantee (the last bare-Windows blocker) -----------------


def test_webview2_installed_is_true_off_windows(monkeypatch):
    monkeypatch.setattr(launch.os, "name", "posix")
    assert launch.webview2_installed() is True


def test_ensure_webview2_skips_when_already_installed():
    calls = []
    launch.ensure_webview2(installed=lambda: True, install=lambda: calls.append(1))
    assert calls == []


def test_ensure_webview2_installs_when_absent():
    calls = []
    launch.ensure_webview2(installed=lambda: False, install=lambda: calls.append(1))
    assert calls == [1]


def test_supervise_guarantees_webview2_after_clone_before_sync(tmp_path):
    order = []
    supervise(
        tmp_path,
        ensure=lambda _wd: order.append("ensure"),
        webview2=lambda: order.append("webview2"),
        uv_sync=lambda _wd: order.append("sync"),
        spawn=lambda _wd: (order.append("spawn"), 0)[1],
    )
    assert order == ["ensure", "webview2", "sync", "spawn"]


# -- first-run splash: progress plumbing + safe fallback ------------------------


def test_supervise_emits_progress_phases_in_order(tmp_path):
    phases = []
    supervise(
        tmp_path, ensure=lambda _wd: None, update=lambda _wd: None, webview2=lambda: None,
        uv_sync=lambda _wd: None, spawn=lambda _wd: 0, progress=phases.append,
    )
    assert phases == ["clone", "update", "webview2", "sync", "starting"]


def test_supervise_signals_starting_only_once_across_restarts(tmp_path):
    phases = []
    calls = {"n": 0}

    def spawn(_wd):
        calls["n"] += 1
        return EXIT_RESTART if calls["n"] < 2 else 0  # one self-update restart, then quit

    supervise(
        tmp_path, ensure=lambda _wd: None, update=lambda _wd: None, webview2=lambda: None,
        uv_sync=lambda _wd: None, spawn=spawn, progress=phases.append,
    )
    assert phases.count("starting") == 1  # only before the FIRST spawn
    assert phases == ["clone", "update", "webview2", "sync", "starting", "sync"]


def test_supervise_updates_on_every_launch_after_clone(tmp_path):
    order = []
    supervise(
        tmp_path,
        ensure=lambda _wd: order.append("clone"),
        update=lambda _wd: order.append("update"),
        webview2=lambda: order.append("webview2"),
        uv_sync=lambda _wd: order.append("sync"),
        spawn=lambda _wd: (order.append("spawn"), 0)[1],
    )
    assert order == ["clone", "update", "webview2", "sync", "spawn"]


def test_update_to_latest_pulls_when_a_checkout_exists(tmp_path):
    (tmp_path / ".git").mkdir()
    calls = []
    launch.update_to_latest(tmp_path, pull=lambda wd: calls.append(wd))
    assert calls == [tmp_path]


def test_update_to_latest_skips_before_the_first_clone(tmp_path):
    calls = []
    launch.update_to_latest(tmp_path, pull=lambda wd: calls.append(wd))
    assert calls == []  # no .git yet: the fresh clone in ensure_clone already got latest


def test_splash_run_falls_back_to_plain_run_when_no_display(monkeypatch):
    # If the GUI path fails for any reason, the app must STILL launch (work runs, code returned).
    def boom(_work):
        raise RuntimeError("no display")

    monkeypatch.setattr(splash, "_run_with_splash", boom)
    seen = []

    def work(progress):
        progress("clone")  # the no-op progress in the fallback path
        seen.append("ran")
        return 7

    assert splash.run(work) == 7
    assert seen == ["ran"]


def test_splash_run_uses_the_splash_result_when_available(monkeypatch):
    monkeypatch.setattr(splash, "_run_with_splash", lambda _work: 3)
    ran = []
    assert splash.run(lambda _progress: ran.append(1) or 999) == 3
    assert ran == []  # work is NOT double-run when the splash path handled it


def test_single_instance_lock_blocks_a_second_holder(tmp_path):
    first = launch.acquire_single_instance(tmp_path)
    assert first is not None
    second = launch.acquire_single_instance(tmp_path)
    assert second is None  # the first launch holds the lock; a second must not race it
    first.close()  # first exits -> lock released
    third = launch.acquire_single_instance(tmp_path)
    assert third is not None  # now free again
    third.close()


def test_supervise_ensures_before_first_run(tmp_path):
    order = []
    supervise(
        tmp_path,
        spawn=lambda _wd: (order.append("spawn"), 0)[1],
        uv_sync=lambda _wd: order.append("sync"),
        ensure=lambda _wd: order.append("ensure"),
    )
    assert order == ["ensure", "sync", "spawn"]
