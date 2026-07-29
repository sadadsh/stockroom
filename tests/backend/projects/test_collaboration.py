from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, datetime
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


def test_persisted_session_can_resume_a_clean_checkout_on_its_work_branch(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    assert first._run("switch", "main").returncode == 0

    status = manager.recovery_status(session)

    assert status["state"] == "resume_available"
    assert status["safe_to_resume"] is True
    assert status["source_preserved"] is True
    assert status["claims"] == {
        "held": ["main.kicad_pcb"],
        "lost": [],
        "unknown": [],
    }

    resumed = manager.resume(session)

    assert resumed == session
    assert first.current_branch() == session.branch


def test_resume_reacquires_a_lost_claim_without_replacing_dirty_native_work(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    del locks.by_path["main.kicad_pcb"]
    (first.root / "main.kicad_pcb").write_text("unsaved native work\n", encoding="utf-8")

    status = manager.recovery_status(session)
    resumed = manager.resume(session)

    assert status["state"] == "resume_available"
    assert status["safe_to_resume"] is True
    assert status["dirty_claimed"] == ["main.kicad_pcb"]
    assert resumed.locks[0].id != session.locks[0].id
    assert locks.by_path["main.kicad_pcb"] == resumed.locks[0]
    assert (first.root / "main.kicad_pcb").read_text(encoding="utf-8") == (
        "unsaved native work\n"
    )


def test_recovery_stays_read_only_when_claim_verification_is_offline(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("preserved\n", encoding="utf-8")
    locks.available_result = (False, "lock server offline")

    status = manager.recovery_status(session)
    with pytest.raises(CollaborationError) as error:
        manager.resume(session)

    assert status["state"] == "offline"
    assert status["safe_to_resume"] is False
    assert status["claims"]["unknown"] == ["main.kicad_pcb"]
    assert error.value.code == "claim_service_offline"
    assert (first.root / "main.kicad_pcb").read_text(encoding="utf-8") == "preserved\n"


def test_recovery_refuses_to_switch_branches_across_unclaimed_changes(tmp_path):
    _origin, first, _second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    assert first._run("switch", "main").returncode == 0
    (first.root / "notes.txt").write_text("unrelated\n", encoding="utf-8")

    status = manager.recovery_status(session)

    assert status["state"] == "attention"
    assert status["safe_to_resume"] is False
    assert status["dirty_unclaimed"] == ["notes.txt"]
    assert first.current_branch() == "main"


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


def test_reviewer_discovers_ready_work_branches_without_changing_the_working_copy(tmp_path):
    _origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = manager.share(session, message="Board work")

    candidates = ReviewManager(second).list_candidates(base_branch="main")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.branch == shared.branch
    assert candidate.commit == shared.shared_commit
    assert candidate.ready is True
    assert candidate.blocked_reason == ""
    assert candidate.changed_paths == ("main.kicad_pcb",)
    assert candidate.commit_count == 1
    assert (second.root / "main.kicad_pcb").read_text(encoding="utf-8") == "board v1\n"
    assert second.current_branch() == "main"


def test_review_listing_keeps_a_stale_work_branch_visible_with_an_exact_blocker(tmp_path):
    origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    manager.share(session, message="Board work")

    third = GitRepo(tmp_path / "third")
    third.clone_from(origin)
    (third.root / "notes.txt").write_text("new main work\n", encoding="utf-8")
    third.commit("Advance main", [third.root / "notes.txt"])
    assert third.push().ok

    candidate = ReviewManager(second).list_candidates(base_branch="main")[0]

    assert candidate.ready is False
    assert candidate.blocked_reason == "main advanced after this work branch started"
    assert candidate.changed_paths == ("main.kicad_pcb",)


@pytest.mark.parametrize(
    ("board_name", "branch"),
    [
        ("main.kicad_pcb", "work/sadad/kicad-board"),
        ("Main.PcbDoc", "work/sadad/altium-board"),
    ],
)
def test_requested_changes_are_repository_backed_and_visible_to_the_author(
    tmp_path,
    board_name,
    branch,
):
    sheet_name = "Power.SchDoc" if board_name.endswith(".PcbDoc") else "power.kicad_sch"
    _origin, first, second = _two_clones(
        tmp_path,
        board_name=board_name,
        sheet_name=sheet_name,
    )
    locks = _SharedLocks()
    author = WorkSessionManager(first, locks)
    session = author.start(owner="Sadad", branch=branch, documents=[board_name])
    (first.root / board_name).write_text("board v2\n", encoding="utf-8")
    shared = author.share(session, message="Board work")

    reviewer = ReviewManager(
        second,
        now=lambda: datetime(2026, 7, 28, 12, 30, tzinfo=UTC),
        new_id=lambda: "event-1",
    )
    candidate = reviewer.discover(branch=shared.branch)
    event = reviewer.request_changes(
        candidate,
        reviewer="Mina",
        message="Confirm the power-stage clearance before integration.",
    )

    assert event.commit == shared.shared_commit
    assert event.base_commit == shared.base_commit
    assert event.created_at == "2026-07-28T12:30:00Z"
    assert second.current_branch() == "main"
    assert second.is_clean()
    assert (second.root / board_name).read_text(encoding="utf-8") == "board v1\n"
    remote_ref = (
        f"refs/tags/stockroom/review/{shared.shared_commit}/event-1"
    )
    assert remote_ref in second._run(
        "ls-remote",
        "--tags",
        "--refs",
        "origin",
        remote_ref,
    ).stdout

    author_listing = ReviewManager(first).list_candidates(base_branch="main")[0]

    assert author_listing.branch == shared.branch
    assert author_listing.events == (event,)
    assert first.current_branch() == shared.branch
    assert first.is_clean()
    assert (first.root / board_name).read_text(encoding="utf-8") == "board v2\n"


def test_request_changes_refuses_when_the_review_commit_moves(tmp_path):
    _origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    manager = WorkSessionManager(first, locks)
    session = manager.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    manager.share(session, message="Board work")
    reviewer = ReviewManager(second, new_id=lambda: "event-1")
    candidate = reviewer.discover(branch=session.branch)

    (first.root / "main.kicad_pcb").write_text("board v3\n", encoding="utf-8")
    first.commit("More board work", [first.root / "main.kicad_pcb"])
    assert first.push().ok

    with pytest.raises(CollaborationError) as changed:
        reviewer.request_changes(
            candidate,
            reviewer="Mina",
            message="This decision must not attach to a stale commit.",
        )

    assert changed.value.code == "review_changed"
    assert (
        second._run(
            "ls-remote",
            "--tags",
            "--refs",
            "origin",
            f"refs/tags/stockroom/review/{candidate.commit}/*",
        ).stdout
        == ""
    )


def test_author_finishes_only_after_remote_integration_and_then_releases_claims(tmp_path):
    _origin, first, second = _two_clones(tmp_path)
    locks = _SharedLocks()
    author = WorkSessionManager(first, locks)
    session = author.start(
        owner="Sadad",
        branch="work/sadad/board",
        documents=["main.kicad_pcb"],
    )
    (first.root / "main.kicad_pcb").write_text("board v2\n", encoding="utf-8")
    shared = author.share(session, message="Board work")

    with pytest.raises(CollaborationError) as pending:
        author.finish_after_remote_integration(shared)
    assert pending.value.code == "not_integrated"
    assert locks.by_path

    review = ReviewManager(second)
    candidate = review.discover(branch=shared.branch)
    integrated = review.approve_fast_forward(candidate)

    assert author.finish_after_remote_integration(shared) == integrated
    assert locks.by_path == {}
    assert first.current_branch() == "main"
    assert first.head() == integrated


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
