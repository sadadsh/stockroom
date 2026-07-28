from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from stockroom.projects.collaboration import (
    CollaborationError,
    ReviewManager,
    WorkSessionManager,
)
from stockroom.vcs.locks import DocumentLock, LockError
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


class _SharedLocks:
    def __init__(self):
        self.by_path: dict[str, DocumentLock] = {}
        self.available_result = (True, "")
        self.owns_error = ""
        self.next_id = 1

    def available(self):
        return self.available_result

    def acquire(self, path):
        rel = Path(path).as_posix()
        if rel in self.by_path:
            raise LockError(f"{rel} is already locked by {self.by_path[rel].owner}")
        lock = DocumentLock(id=str(self.next_id), path=rel, owner="fixture-user")
        self.next_id += 1
        self.by_path[rel] = lock
        return lock

    def owns(self, expected):
        if self.owns_error:
            raise LockError(self.owns_error)
        return self.by_path.get(expected.path) == expected

    def release(self, lock, *, force=False):
        if self.by_path.get(lock.path) != lock:
            raise LockError(f"{lock.path} is not owned")
        del self.by_path[lock.path]


class _FailSecondLock(_SharedLocks):
    def acquire(self, path):
        if self.next_id == 2:
            raise LockError("second document is already locked")
        return super().acquire(path)


def _two_clones(
    tmp_path,
    *,
    board_name: str = "main.kicad_pcb",
    sheet_name: str = "power.kicad_sch",
):
    origin = tmp_path / "origin.git"
    GitRepo(origin).init(bare=True)
    first = GitRepo(tmp_path / "first")
    first.clone_from(origin)
    (first.root / board_name).write_text("board v1\n", encoding="utf-8")
    (first.root / sheet_name).write_text("power v1\n", encoding="utf-8")
    first.commit(
        "Initial project",
        [first.root / board_name, first.root / sheet_name],
    )
    assert first.push().ok
    second = GitRepo(tmp_path / "second")
    second.clone_from(origin)
    return origin, first, second


def test_two_clones_can_claim_different_documents_but_not_the_same_one(tmp_path):
    _origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    first_manager = WorkSessionManager(first, locks, new_id=lambda: "session-a")
    second_manager = WorkSessionManager(second, locks, new_id=lambda: "session-b")

    first_session = first_manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )

    with pytest.raises(CollaborationError) as conflict:
        second_manager.start(
            owner="Alex",
            branch="work/alex/board",
            documents=["main.kicad_pcb"],
        )
    assert conflict.value.code == "lock_failed"
    assert second.current_branch() == "main"

    second_session = second_manager.start(
        owner="Alex",
        branch="work/alex/power",
        documents=["power.kicad_sch"],
    )

    assert first_session.documents == ("main.kicad_pcb",)
    assert second_session.documents == ("power.kicad_sch",)
    assert set(locks.by_path) == {"main.kicad_pcb", "power.kicad_sch"}


def test_share_commits_only_claimed_documents_and_pushes_the_work_branch(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks, new_id=lambda: "session-a")
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")

    shared = manager.share(session, message="Move power connector")

    assert len(shared.shared_commit) == 40
    assert first.has_upstream()
    assert first.show_file(shared.shared_commit, "main.kicad_pcb") == "board v2\n"
    assert locks.by_path["main.kicad_pcb"] == session.locks[0]


def test_share_refuses_unclaimed_changes_without_staging_them(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    (first.root / "notes.txt").write_text("unrelated\n", encoding="utf-8")

    with pytest.raises(CollaborationError) as error:
        manager.share(session, message="Board work")

    assert error.value.code == "unclaimed_changes"
    assert "notes.txt" in error.value.detail
    assert first._run("diff", "--cached", "--name-only").stdout == ""


def test_share_refuses_when_the_remote_lock_was_lost(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    del locks.by_path["main.kicad_pcb"]
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")

    with pytest.raises(CollaborationError) as error:
        manager.share(session, message="Board work")
    assert error.value.code == "lock_lost"
    assert first.head() == session.base_commit


def test_share_preserves_work_when_lock_verification_is_offline(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    locks.owns_error = "could not resolve lock server"

    with pytest.raises(CollaborationError) as error:
        manager.share(session, message="Board work")

    assert error.value.code == "lock_status_failed"
    assert (first.root / "main.kicad_pcb").read_text(encoding="utf-8") == "board v2\n"
    assert first.head() == session.base_commit


def test_locks_release_only_after_the_shared_commit_is_integrated(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = manager.share(session, message="Board work")

    with pytest.raises(CollaborationError) as error:
        manager.release_after_integration(shared, integrated_commit=shared.base_commit)
    assert error.value.code == "not_integrated"
    assert "main.kicad_pcb" in locks.by_path

    manager.release_after_integration(shared, integrated_commit=shared.shared_commit)
    assert locks.by_path == {}


def test_start_requires_a_clean_synced_base_and_locking_service(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    (first.root / "notes.txt").write_text("local\n", encoding="utf-8")
    with pytest.raises(CollaborationError) as dirty:
        manager.start(owner="Sadad", branch="work/sadad/a", documents=["main.kicad_pcb"])
    assert dirty.value.code == "dirty_tree"

    (first.root / "notes.txt").unlink()
    locks.available_result = (False, "remote does not support locks")
    with pytest.raises(CollaborationError) as unavailable:
        manager.start(owner="Sadad", branch="work/sadad/b", documents=["main.kicad_pcb"])
    assert unavailable.value.code == "locking_unavailable"


def test_partial_lock_failure_releases_every_lock_already_acquired(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _FailSecondLock()
    manager = WorkSessionManager(first, locks)

    with pytest.raises(CollaborationError) as failed:
        manager.start(
            owner="Sadad",
            branch="work/sadad/two-files",
            documents=["main.kicad_pcb", "power.kicad_sch"],
        )

    assert failed.value.code == "lock_failed"
    assert locks.by_path == {}
    assert first.current_branch() == "main"


def test_session_is_immutable_when_share_records_the_commit(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = manager.share(session, message="Board work")

    assert session.shared_commit == ""
    assert replace(session, shared_commit=shared.shared_commit) == shared


@pytest.mark.parametrize(
    ("board_name", "branch"),
    [
        ("main.kicad_pcb", "work/sadad/kicad-board"),
        ("Main.PcbDoc", "work/sadad/altium-board"),
    ],
)
def test_second_clone_reviews_in_an_isolated_worktree_then_fast_forwards_main(
    tmp_path, board_name, branch
):
    sheet_name = "Power.SchDoc" if board_name.endswith(".PcbDoc") else "power.kicad_sch"
    _origin, first, second = _two_clones(tmp_path, board_name=board_name, sheet_name=sheet_name)
    locks = _SharedLocks()
    first_manager = WorkSessionManager(first, locks)
    session = first_manager.start(
        owner="Sadad",
        branch=branch,
        documents=[board_name],
    )
    (first.root / board_name).write_text("board v2\n", encoding="utf-8")
    shared = first_manager.share(session, message="Board work")

    review_manager = ReviewManager(second)
    candidate = review_manager.discover(branch=shared.branch)
    seen = {}

    def inspect(worktree):
        seen["review"] = (worktree / board_name).read_text(encoding="utf-8")
        seen["working"] = (second.root / board_name).read_text(encoding="utf-8")

    review_manager.inspect(candidate, inspect)
    integrated = review_manager.approve_fast_forward(candidate)

    assert seen == {"review": "board v2\n", "working": "board v1\n"}
    assert integrated == shared.shared_commit
    assert (second.root / board_name).read_text(encoding="utf-8") == "board v2\n"

    assert first.fetch()[0]
    first_manager.release_after_integration(shared, integrated_commit=integrated)
    assert locks.by_path == {}


def test_approval_refuses_when_the_reviewed_branch_changes(tmp_path):
    _origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    first_manager = WorkSessionManager(first, locks)
    session = first_manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = first_manager.share(session, message="Board work")

    review_manager = ReviewManager(second)
    candidate = review_manager.discover(branch=shared.branch)

    (first.root / "main.kicad_pcb").write_text("board v3\n", encoding="utf-8")
    first.commit("More board work", [first.root / "main.kicad_pcb"])
    assert first.push().ok

    with pytest.raises(CollaborationError) as changed:
        review_manager.approve_fast_forward(candidate)
    assert changed.value.code == "review_changed"
    assert second.head() == candidate.base_commit


def test_approval_refuses_when_main_advances_and_preserves_both_histories(tmp_path):
    origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    first_manager = WorkSessionManager(first, locks)
    session = first_manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = first_manager.share(session, message="Board work")

    review_manager = ReviewManager(second)
    candidate = review_manager.discover(branch=shared.branch)

    third = GitRepo(tmp_path / "third")
    third.clone_from(origin)
    (third.root / "notes.txt").write_text("remote main work\n", encoding="utf-8")
    advanced_main = third.commit("Advance main", [third.root / "notes.txt"])
    assert third.push().ok

    with pytest.raises(CollaborationError) as changed:
        review_manager.approve_fast_forward(candidate)

    assert changed.value.code == "base_changed"
    assert second.head() == candidate.base_commit
    assert second.has_commit(advanced_main)
    assert second.has_commit(shared.shared_commit)
