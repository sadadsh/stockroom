import shutil

import pytest

from stockroom.vcs.repo import GitRepo, PullResult, PushResult
from stockroom.vcs.sync import SyncEngine, SyncState, _classify_failure

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


@pytest.mark.parametrize("reason", [
    "remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found",
    "fatal: Authentication failed for 'https://github.com/x/y.git/'",
    "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
    "git@github.com: Permission denied (publickey).",
    "fatal: unable to access 'https://...': The requested URL returned error: 403 Forbidden",
])
def test_auth_failure_classifies_as_denied_not_diverged_or_offline(reason):
    # An authentication / private-repo failure must be its own honest state, never mislabeled a
    # divergence (the library did not diverge) or an offline outage.
    assert _classify_failure(reason) == SyncState.DENIED


def test_network_failure_still_classifies_as_offline():
    assert _classify_failure("fatal: unable to access '...': Could not resolve host: github.com") \
        == SyncState.OFFLINE


def test_true_conflict_still_classifies_as_diverged():
    assert _classify_failure("fatal: Not possible to fast-forward, aborting.") == SyncState.DIVERGED


class _StubRepo:
    """A minimal repo whose pull/push report a given failure reason, to drive SyncEngine's
    classification without a real remote."""
    def __init__(self, reason):
        self._reason = reason

    def has_remote(self):
        return True

    def has_upstream(self):
        return True

    def pull_ff(self):
        return PullResult(ok=False, updated=False, reason=self._reason)

    def ahead_behind(self):
        return (0, 0)


def test_sync_reports_denied_on_an_auth_pull_failure():
    repo = _StubRepo("remote: Repository not found.\nfatal: repository not found")
    res = SyncEngine(repo).sync()
    assert res.state == SyncState.DENIED
    assert "not found" in res.detail.lower()


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
