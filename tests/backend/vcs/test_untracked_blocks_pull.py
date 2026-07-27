"""An update must not be stopped by a file the app itself created on this machine.

THE OWNER'S ACTUAL FAILURE, 2026-07-27, verbatim from their laptop:

    error: The following untracked working tree files would be overwritten by checkout:
    libraries/Stockroom/symbols/SR-Capacitors.kicad_sym
    ... 10 files ...
    Please move or remove them before you switch branches.
    Aborting
    Applied autostash.
    error: could not detach HEAD

WHY IT HAPPENS, and why it is a DEVICE-PARITY bug rather than an annoyance. The app creates
`SR-<Category>.kicad_sym` on demand, on whatever machine first needs that category. It only becomes
TRACKED when that machine happens to commit a part into it. A second machine therefore holds its
own UNTRACKED copy of the same path -- and the moment the tracked version arrives from the remote,
git refuses to clobber it and the whole update aborts. Measured: the 10 files above were added
across commits from 2026-07-25 to 2026-07-27, all of them after that laptop last pulled.

This was logged FOUR separate times as "9 empty SR-*.kicad_sym block every merge" and treated as
scaffolding noise. It is not noise: it is one machine unable to receive updates from another, which
is the owner's *"same update, same files, same info"* rule broken outright.

An update is not allowed to fail for this. The local file is either identical to the incoming one
(nothing to lose) or it is not (so it is preserved, never silently overwritten).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def _two_clones(tmp_path):
    """An `origin` plus two working clones, which is the owner's real shape: a desktop and a
    laptop against one remote."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")

    desk = tmp_path / "desk"
    _git(tmp_path, "clone", str(origin), "desk")
    _git(desk, "config", "user.email", "a@b.c")
    _git(desk, "config", "user.name", "t")
    (desk / "app.py").write_text("v1\n", encoding="utf-8")
    _git(desk, "add", "app.py")
    _git(desk, "commit", "-m", "seed")
    _git(desk, "push", "-u", "origin", "main")

    lap = tmp_path / "lap"
    _git(tmp_path, "clone", str(origin), "lap")
    _git(lap, "config", "user.email", "a@b.c")
    _git(lap, "config", "user.name", "t")
    return origin, desk, lap


def test_an_untracked_file_the_update_wants_to_add_does_NOT_abort_the_update(tmp_path):
    origin, desk, lap = _two_clones(tmp_path)
    # The desktop commits a category library and pushes it.
    libs = desk / "libraries"
    libs.mkdir()
    (libs / "SR-Capacitors.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    _git(desk, "add", "libraries/SR-Capacitors.kicad_sym")
    _git(desk, "commit", "-m", "add a category library")
    _git(desk, "push")
    # The LAPTOP's own app created the same path locally, untracked. This is the exact state.
    (lap / "libraries").mkdir()
    (lap / "libraries" / "SR-Capacitors.kicad_sym").write_text(
        "(kicad_symbol_lib)\n", encoding="utf-8"
    )

    result = GitRepo(lap).pull_rebase()

    assert result.ok, f"the update must not abort: {result.reason}"
    assert result.updated
    assert (lap / "libraries" / "SR-Capacitors.kicad_sym").exists()


def test_a_local_file_that_DIFFERS_is_preserved_not_silently_overwritten(tmp_path):
    """The load-bearing half. Unblocking an update must never cost the user data: if the local copy
    is not the incoming one, it is kept beside it and the person can see both."""
    origin, desk, lap = _two_clones(tmp_path)
    libs = desk / "libraries"
    libs.mkdir()
    (libs / "SR-Capacitors.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    _git(desk, "add", "libraries/SR-Capacitors.kicad_sym")
    _git(desk, "commit", "-m", "add a category library")
    _git(desk, "push")
    (lap / "libraries").mkdir()
    mine = lap / "libraries" / "SR-Capacitors.kicad_sym"
    mine.write_text('(kicad_symbol_lib (symbol "MY_REAL_SYMBOL"))\n', encoding="utf-8")

    result = GitRepo(lap).pull_rebase()

    assert result.ok, result.reason
    # The incoming version is in place...
    assert "MY_REAL_SYMBOL" not in mine.read_text(encoding="utf-8")
    # ...and MINE still exists somewhere, with its content intact.
    kept = list(lap.rglob("*SR-Capacitors*"))
    assert any(
        "MY_REAL_SYMBOL" in p.read_text(encoding="utf-8")
        for p in kept
        if p.is_file() and p != mine
    ), f"the local copy was destroyed; only found {[p.name for p in kept]}"


def test_an_identical_local_file_is_just_removed_with_no_backup_clutter(tmp_path):
    """NEGATIVE CONTROL for the case above: when the bytes match there is nothing to preserve, so
    a backup would be pure clutter in the user's library."""
    origin, desk, lap = _two_clones(tmp_path)
    libs = desk / "libraries"
    libs.mkdir()
    (libs / "SR-Capacitors.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    _git(desk, "add", "libraries/SR-Capacitors.kicad_sym")
    _git(desk, "commit", "-m", "add a category library")
    _git(desk, "push")
    (lap / "libraries").mkdir()
    (lap / "libraries" / "SR-Capacitors.kicad_sym").write_text(
        "(kicad_symbol_lib)\n", encoding="utf-8"
    )

    assert GitRepo(lap).pull_rebase().ok
    assert [p.name for p in (lap / "libraries").iterdir()] == ["SR-Capacitors.kicad_sym"]


def test_a_REAL_conflict_still_reports_honestly_and_is_not_swallowed(tmp_path):
    """NEGATIVE CONTROL for the whole feature. Clearing the way for untracked adds must not turn a
    genuine divergence into a silent success -- that would be a green signal not wired to the fact
    it claims, which is the failure this repo bans."""
    origin, desk, lap = _two_clones(tmp_path)
    (desk / "app.py").write_text("theirs\n", encoding="utf-8")
    _git(desk, "add", "app.py")
    _git(desk, "commit", "-m", "their edit")
    _git(desk, "push")
    (lap / "app.py").write_text("mine\n", encoding="utf-8")
    _git(lap, "add", "app.py")
    _git(lap, "commit", "-m", "my edit")

    result = GitRepo(lap).pull_rebase()

    assert not result.ok
    assert not result.updated


def test_an_untracked_file_the_update_does_NOT_touch_is_left_completely_alone(tmp_path):
    """THE NARROWNESS GUARANTEE. Clearing blockers must only ever touch paths the incoming commits
    actually ADD. A user's library is full of untracked working files -- scratch exports, a
    half-finished footprint, a downloaded zip -- and an update that tidied any of them away would
    be far worse than the abort it is fixing.

    Added because a tamper that widened the path filter beyond `--diff-filter=A` broke NOTHING in
    51 tests: the behaviour changed and no test noticed, which means the narrowness was asserted
    nowhere.
    """
    origin, desk, lap = _two_clones(tmp_path)
    libs = desk / "libraries"
    libs.mkdir()
    (libs / "SR-Capacitors.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    _git(desk, "add", "libraries/SR-Capacitors.kicad_sym")
    _git(desk, "commit", "-m", "add a category library")
    _git(desk, "push")

    (lap / "libraries").mkdir()
    # The blocker...
    (lap / "libraries" / "SR-Capacitors.kicad_sym").write_text(
        "(kicad_symbol_lib)\n", encoding="utf-8"
    )
    # ...and a bystander the update has no opinion about whatsoever.
    bystander = lap / "libraries" / "my-scratch-work.kicad_mod"
    bystander.write_text("do not touch me\n", encoding="utf-8")

    assert GitRepo(lap).pull_rebase().ok

    assert bystander.is_file()
    assert bystander.read_text(encoding="utf-8") == "do not touch me\n"
    assert not (lap / GitRepo(lap)._RESCUE_DIR).exists()
