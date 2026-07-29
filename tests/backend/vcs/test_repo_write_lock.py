"""Two writers to ONE repository serialize instead of colliding on `.git/index.lock`.

Git takes an exclusive `.git/index.lock` for the duration of any index write. Two of Stockroom's
own writes landing at once on the same repo is not exotic: the API runs sync route handlers in a
threadpool, so Prepare, Sync Hygiene, Library Pin and Restore can all be in flight together, and
each of them stages and commits. The Altium router had already met this and solved it locally with
a module `_WRITE_LOCK` (`093d828`) - which fixes exactly the four endpoints someone remembered.

The lock therefore belongs to the thing that OWNS the index: the repository. Keyed by resolved
root, so two `GitRepo` objects for one repo share it and two DIFFERENT repos still run in
parallel; re-entrant, so a `commit` nested inside a `Transaction` on the same thread cannot
deadlock against the transaction that already holds it.
"""
from __future__ import annotations

import threading
from pathlib import Path

from stockroom.mutation.transaction import Transaction
from stockroom.vcs.repo import GitRepo


def _seeded(root: Path) -> GitRepo:
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    (root / "seed.json").write_text("{}", encoding="utf-8")
    repo.commit("seed", [root / "seed.json"])
    return repo


def test_concurrent_commits_to_one_repo_all_succeed(tmp_path):
    """The real symptom: `.git/index.lock` collisions surfacing as a failed mutation."""
    repo = _seeded(tmp_path / "proj")
    errors: list[str] = []
    barrier = threading.Barrier(6)

    def writer(n: int) -> None:
        path = tmp_path / "proj" / f"f{n}.json"
        barrier.wait()  # every thread starts INSIDE the window, not staggered by startup cost
        for i in range(4):
            try:
                path.write_text(f'{{"n": {n}, "i": {i}}}', encoding="utf-8")
                with Transaction(GitRepo(tmp_path / "proj")) as txn:
                    txn.track(path)
                    txn.commit(f"write {n}-{i}")
            except Exception as exc:  # noqa: BLE001 - nothing may escape a serialized write
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"{len(errors)} concurrent write failures, first: {errors[:3]}"
    # And every commit landed: serialization must not mean silently dropping one.
    assert len(repo.log_paths([], max_count=200) or repo.log_paths(
        [Path("seed.json")], max_count=200)) >= 1
    subjects = {c.subject for c in repo.log_paths([], max_count=200)}
    for n in range(6):
        for i in range(4):
            assert f"write {n}-{i}" in subjects, f"commit write {n}-{i} was lost"


def test_writes_that_never_open_a_transaction_are_serialized_too(tmp_path):
    """Not every git write in this app goes through `Transaction`.

    `ProjectOps.restore` calls `repo.revert(...)` directly, and workspace hygiene untracks paths
    the same way. A lock that lived only in `Transaction` would leave those colliding with a
    concurrent Prepare, which is the half of the bug that looks fixed because the common path is
    covered. This exercises `GitRepo`'s own serialization with no transaction anywhere near it.

    Written after TAMPERING: removing the `@_serialized` decorators left the other tests GREEN,
    because the transaction lock masked their absence. A guard nothing can fail is not a guard.
    """
    root = tmp_path / "direct"
    repo = _seeded(root)
    errors: list[str] = []
    barrier = threading.Barrier(6)

    def writer(n: int) -> None:
        path = root / f"d{n}.json"
        barrier.wait()
        for i in range(4):
            try:
                path.write_text(f'{{"n": {n}, "i": {i}}}', encoding="utf-8")
                GitRepo(root).commit(f"direct {n}-{i}", [path])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"{len(errors)} direct-write failures, first: {errors[:2]}"
    subjects = {c.subject for c in repo.log_paths([], max_count=200)}
    missing = [f"direct {n}-{i}" for n in range(6) for i in range(4) if f"direct {n}-{i}" not in subjects]
    assert missing == [], f"commits lost: {missing[:5]}"


def test_two_different_repos_are_not_serialized_against_each_other(tmp_path):
    """A per-repo lock, not a global one: the library and a project must not block each other."""
    a, b = _seeded(tmp_path / "a"), _seeded(tmp_path / "b")
    assert a._write_lock() is a._write_lock()          # same repo -> same lock object
    assert GitRepo(tmp_path / "a")._write_lock() is a._write_lock()  # and across instances
    assert a._write_lock() is not b._write_lock()


def test_root_and_in_repo_library_handles_share_the_same_lock(tmp_path):
    root = GitRepo(tmp_path / "embedded")
    root.init()
    libraries = root.root / "libraries"
    libraries.mkdir()

    assert GitRepo(libraries)._write_lock() is root._write_lock()


def test_a_transaction_holds_the_lock_for_its_WHOLE_window_not_just_its_commit(tmp_path):
    """Locking only `GitRepo.commit` stops two commits colliding and still lets two transactions
    interleave their file WRITES - one staging a file the other had half-rewritten, or rolling
    back paths the other had just committed. Atomicity is per transaction, so the lock has to span
    the transaction.

    Asserted on the lock STATE rather than on an ordering, because an ordering test here would need
    a sleep to make the race probable, and a sleep is not a detector. `acquire(blocking=False)`
    from another thread answers the question outright.
    """
    repo = _seeded(tmp_path / "proj")
    took: list[bool] = []

    def grab() -> None:
        lock = repo._write_lock()
        got = lock.acquire(blocking=False)
        took.append(got)
        if got:
            lock.release()

    with Transaction(repo):
        # Another THREAD, because the lock is re-entrant and this thread already holds it.
        t = threading.Thread(target=grab)
        t.start()
        t.join(timeout=10)

    assert took == [False], (
        "another thread took the repo's write lock while a transaction was open, so two "
        "transactions can interleave their writes"
    )


def test_a_commit_nested_inside_a_transaction_does_not_deadlock(tmp_path):
    """Re-entrancy is the trap to disarm now, not to discover in a hung app: `Transaction` holds
    the lock for its whole window and then calls `repo.commit`, which takes it again."""
    repo = _seeded(tmp_path / "proj")
    path = tmp_path / "proj" / "nested.json"
    path.write_text("{}", encoding="utf-8")
    done = threading.Event()

    def body() -> None:
        with Transaction(repo) as txn:
            txn.track(path)
            txn.commit("nested")
        done.set()

    t = threading.Thread(target=body, daemon=True)
    t.start()
    t.join(timeout=30)
    assert done.is_set(), "a transaction deadlocked against its own commit"
