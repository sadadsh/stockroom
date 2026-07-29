from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.projects.collaboration import WorkSession
from stockroom.projects.collaboration_store import WorkSessionStore
from stockroom.vcs.locks import DocumentLock


def _session(session_id: str = "session-a", *, shared_commit: str = "") -> WorkSession:
    return WorkSession(
        id=session_id,
        owner="Sadad",
        branch="work/sadad/power",
        base_branch="main",
        base_commit="a" * 40,
        documents=("Power.SchDoc", "Main.PcbDoc"),
        locks=(
            DocumentLock(
                id="lock-1",
                path="Power.SchDoc",
                owner="Sadad",
                locked_at="2026-07-28T12:00:00Z",
            ),
            DocumentLock(
                id="lock-2",
                path="Main.PcbDoc",
                owner="Sadad",
                locked_at="2026-07-28T12:00:01Z",
            ),
        ),
        started_at="2026-07-28T12:00:00Z",
        shared_commit=shared_commit,
    )


def test_active_session_survives_store_reopen(tmp_path: Path) -> None:
    store = WorkSessionStore(tmp_path / "sessions")
    store.save("amp", _session())

    reopened = WorkSessionStore(tmp_path / "sessions").active("amp")
    assert reopened == _session()
    assert reopened is not None
    assert reopened.locks[1].path == "Main.PcbDoc"


def test_same_session_can_advance_to_a_shared_commit(tmp_path: Path) -> None:
    store = WorkSessionStore(tmp_path / "sessions")
    store.save("amp", _session())
    store.save("amp", _session(shared_commit="b" * 40))
    assert store.active("amp") == _session(shared_commit="b" * 40)


def test_different_active_session_is_refused_and_clear_checks_identity(tmp_path: Path) -> None:
    store = WorkSessionStore(tmp_path / "sessions")
    store.save("amp", _session())
    with pytest.raises(ValueError, match="already has"):
        store.save("amp", _session("session-b"))
    with pytest.raises(ValueError, match="changed"):
        store.clear("amp", "session-b")

    store.clear("amp", "session-a")
    assert store.active("amp") is None
