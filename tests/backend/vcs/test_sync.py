import shutil

import pytest

from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine, SyncState

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _origin_and_clone(tmp_path, name):
    origin = tmp_path / "origin.git"
    if not origin.exists():
        GitRepo(origin).init(bare=True)
    clone = GitRepo(tmp_path / name)
    clone.clone_from(origin)
    return origin, clone


def test_no_remote_reported(tmp_path):
    r = GitRepo(tmp_path / "local")
    r.init()
    (r.root / "f").write_text("x")
    r.commit("x", [r.root / "f"])
    res = SyncEngine(r).sync()
    assert res.state == SyncState.NO_REMOTE


def test_push_when_ahead(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    res = SyncEngine(a).sync()
    assert res.pushed is True
    assert res.state in (SyncState.PUSHED, SyncState.SYNCED)

    # a second clone sees it after pull
    _, b = _origin_and_clone(tmp_path, "b")
    assert (b.root / "f").read_text() == "v1"


def test_pull_when_behind(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    SyncEngine(a).sync()

    _, b = _origin_and_clone(tmp_path, "b")
    (a.root / "f").write_text("v2")
    a.commit("v2", [a.root / "f"])
    SyncEngine(a).sync()

    res = SyncEngine(b).sync()
    assert res.pulled is True
    assert (b.root / "f").read_text() == "v2"


def test_divergence_is_surfaced_not_clobbered(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("base")
    a.commit("base", [a.root / "f"])
    SyncEngine(a).sync()

    _, b = _origin_and_clone(tmp_path, "b")
    (a.root / "f").write_text("remote")
    a.commit("remote", [a.root / "f"])
    SyncEngine(a).sync()
    (b.root / "g").write_text("local")
    b.commit("local", [b.root / "g"])

    res = SyncEngine(b).sync()
    assert res.state == SyncState.DIVERGED
    # local work intact, remote not merged over it
    assert (b.root / "g").read_text() == "local"


def test_already_in_sync_is_idempotent(tmp_path):
    origin, a = _origin_and_clone(tmp_path, "a")
    (a.root / "f").write_text("v1")
    a.commit("v1", [a.root / "f"])
    SyncEngine(a).sync()
    res = SyncEngine(a).sync()
    assert res.state == SyncState.SYNCED
    assert res.pulled is False and res.pushed is False
