from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine, SyncState

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _devices(tmp_path: Path) -> tuple[GitRepo, GitRepo]:
    origin = GitRepo(tmp_path / "origin.git")
    origin.init(bare=True)
    seed = GitRepo(tmp_path / "seed")
    seed.clone_from(origin.root)
    marker = seed.root / "README.md"
    marker.write_text("library\n", encoding="utf-8")
    seed.commit("initialize", [marker])
    assert SyncEngine(seed).sync().pushed
    first = GitRepo(tmp_path / "first")
    second = GitRepo(tmp_path / "second")
    first.clone_from(origin.root)
    second.clone_from(origin.root)
    return first, second


def test_two_devices_adding_different_parts_converge_without_manual_git(
    tmp_path: Path,
) -> None:
    first, second = _devices(tmp_path)
    first_part = first.root / "libraries" / "Stockroom" / "parts" / "first.json"
    first_part.parent.mkdir(parents=True)
    first_part.write_text('{"id":"first"}\n', encoding="utf-8")
    first.commit("add first", [first_part])
    assert SyncEngine(first).sync().pushed

    second_part = second.root / "libraries" / "Stockroom" / "parts" / "second.json"
    second_part.parent.mkdir(parents=True)
    second_part.write_text('{"id":"second"}\n', encoding="utf-8")
    second.commit("add second", [second_part])
    result = SyncEngine(second).sync()

    assert result.state == SyncState.CONVERGED
    assert result.converged and result.pulled and result.pushed
    assert SyncEngine(first).sync().pulled
    assert (first.root / second_part.relative_to(second.root)).read_bytes() == second_part.read_bytes()
    assert (second.root / first_part.relative_to(first.root)).read_bytes() == first_part.read_bytes()


def test_true_same_file_conflict_stays_diverged_and_preserves_local_bytes(
    tmp_path: Path,
) -> None:
    first, second = _devices(tmp_path)
    first_file = first.root / "README.md"
    first_file.write_text("remote\n", encoding="utf-8")
    first.commit("remote edit", [first_file])
    assert SyncEngine(first).sync().pushed

    second_file = second.root / "README.md"
    second_file.write_text("local\n", encoding="utf-8")
    second.commit("local edit", [second_file])
    result = SyncEngine(second).sync()

    assert result.state == SyncState.DIVERGED
    assert not result.converged
    assert second_file.read_text(encoding="utf-8") == "local\n"


def test_automatic_rebase_refuses_uncommitted_tracked_work(tmp_path: Path) -> None:
    first, second = _devices(tmp_path)
    remote = first.root / "remote.txt"
    remote.write_text("remote\n", encoding="utf-8")
    first.commit("remote", [remote])
    assert SyncEngine(first).sync().pushed

    local = second.root / "local.txt"
    local.write_text("local\n", encoding="utf-8")
    second.commit("local", [local])
    in_progress = second.root / "README.md"
    in_progress.write_text("work in progress\n", encoding="utf-8")

    result = SyncEngine(second).sync()

    assert result.state == SyncState.DIVERGED
    assert "uncommitted local changes" in result.detail
    assert in_progress.read_text(encoding="utf-8") == "work in progress\n"
