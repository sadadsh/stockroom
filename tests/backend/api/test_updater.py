import shutil

import pytest

from stockroom.api.updater import AppUpdater, UpdateState
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _rmtree_force(path):
    """rmtree that tolerates Windows read-only .git object files: git marks packed/loose objects
    read-only, so a plain rmtree raises WinError 5 (Access is denied) on Windows. Make every entry
    writable first, then remove. A no-op difference on POSIX."""
    import os
    import stat

    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            p = os.path.join(root, name)
            try:
                # ADD write (never replace the mode): a bare S_IWRITE on a directory drops its
                # read/execute bits and makes it non-traversable, so deletion then fails.
                os.chmod(p, os.stat(p).st_mode | stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path)


def _origin_and_clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    o = GitRepo(origin)
    o.init()
    (origin / "app.py").write_text("v1\n", encoding="utf-8")
    o.commit("v1", [origin / "app.py"])
    clone = tmp_path / "clone"
    c = GitRepo(clone)
    c.clone_from(origin)
    return o, origin, c, clone


def test_update_pulls_a_fast_forward_and_requests_restart(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    # advance origin so the clone is behind by a fast-forwardable commit
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    o.commit("v2", [origin / "app.py"])

    ran = {"uv": False, "restart": False}
    updater = AppUpdater(
        c,
        uv_runner=lambda: ran.__setitem__("uv", True),
        restart=lambda: ran.__setitem__("restart", True),
    )
    result = updater.update()
    assert result.state == UpdateState.UPDATED
    assert result.updated is True
    assert result.restart_requested is True
    assert ran["uv"] is True
    assert ran["restart"] is True
    assert (clone / "app.py").read_text() == "v2\n"


def test_update_up_to_date_does_not_run_uv_or_restart(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    ran = {"uv": False}
    updater = AppUpdater(c, uv_runner=lambda: ran.__setitem__("uv", True), restart=lambda: None)
    result = updater.update()
    assert result.state == UpdateState.UP_TO_DATE
    assert result.updated is False
    assert ran["uv"] is False


def test_update_diverged_is_surfaced_not_guessed(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    # make the clone diverge: a local commit AND a different origin commit
    (clone / "app.py").write_text("local\n", encoding="utf-8")
    c.commit("local change", [clone / "app.py"])
    (origin / "app.py").write_text("remote\n", encoding="utf-8")
    o.commit("remote change", [origin / "app.py"])

    updater = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None)
    result = updater.update()
    assert result.state == UpdateState.DIVERGED
    assert result.restart_requested is False


def test_update_reconciles_a_disjoint_local_commit_by_rebase(tmp_path):
    # The in-repo library case (the whole reason self-update was stuck): a LOCAL part commit
    # (libraries/, added on this machine) plus a REMOTE app-code commit (app/) touch DISJOINT
    # paths. A plain ff-only pull refuses this divergence forever, so once a part is added the app
    # can never self-update and the user is forced to re-download a release. The updater must
    # REBASE the local part commit onto the app update and still succeed, keeping the part.
    o, origin, c, clone = _origin_and_clone(tmp_path)
    (clone / "part.json").write_text("{}\n", encoding="utf-8")  # local: add a part (disjoint)
    c.commit("add a part", [clone / "part.json"])
    (origin / "app.py").write_text("v2\n", encoding="utf-8")  # remote: advance app code
    o.commit("v2 app code", [origin / "app.py"])

    ran = {"uv": False, "restart": False}
    updater = AppUpdater(
        c,
        uv_runner=lambda: ran.__setitem__("uv", True),
        restart=lambda: ran.__setitem__("restart", True),
    )
    result = updater.update()
    assert result.state == UpdateState.UPDATED and result.restart_requested is True
    assert (clone / "app.py").read_text() == "v2\n"  # got the app update
    assert (clone / "part.json").exists()  # kept the local part
    assert ran["uv"] and ran["restart"]


def test_check_fetches_so_a_fresh_remote_commit_is_seen(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    o.commit("v2", [origin / "app.py"])
    # NO manual fetch here: check() itself must fetch, or the running app can
    # never learn a new release exists and the Apply button never appears (the
    # owner's "update button does not work, must relaunch" bug).
    info = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None).check()
    assert info["update_available"] is True
    assert info["behind"] == 1
    assert info["state"] == "update_available"
    assert info["current_revision"] == c.head()[:12]
    assert info["target_revision"] == o.head()[:12]
    assert info["channel"] == c.current_branch()
    assert info["automatic_on_launch"] is True
    assert info["check_interval_seconds"] == 120


def test_check_proves_current_against_the_exact_upstream_revision(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)

    info = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None).check()

    expected = o.head()[:12]
    assert info["state"] == UpdateState.UP_TO_DATE
    assert info["update_available"] is False
    assert info["behind"] == 0
    assert info["current_revision"] == expected
    assert info["target_revision"] == expected


def test_check_reports_an_unreachable_remote_honestly(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    _rmtree_force(origin)  # the remote cannot be fetched anymore (Windows-safe: git objects are RO)
    info = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None).check()
    assert info["update_available"] is False
    assert info["state"] == UpdateState.OFFLINE
    assert info["detail"]  # the reason is carried, never a silent Up To Date
    assert info["current_revision"] == c.head()[:12]
    assert info["target_revision"] == ""
    assert info["channel"] == c.current_branch()


def test_check_reports_an_unmanaged_checkout_instead_of_calling_it_current(tmp_path):
    repo_path = tmp_path / "standalone"
    repo_path.mkdir()
    repo = GitRepo(repo_path)
    repo.init()
    tracked = repo_path / "app.py"
    tracked.write_text("v1\n", encoding="utf-8")
    repo.commit("v1", [tracked])

    info = AppUpdater(repo, uv_runner=lambda: None, restart=lambda: None).check()

    assert info["update_available"] is False
    assert info["state"] == UpdateState.NO_REMOTE
    assert info["detail"] == "no application remote is configured"
    assert info["current_revision"] == repo.head()[:12]
    assert info["target_revision"] == ""
    assert info["automatic_on_launch"] is True


def test_check_never_calls_a_remote_without_an_upstream_current(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    remote = GitRepo(origin)
    remote.init()
    tracked = origin / "app.py"
    tracked.write_text("v1\n", encoding="utf-8")
    remote.commit("v1", [tracked])

    local_path = tmp_path / "local"
    local_path.mkdir()
    local = GitRepo(local_path)
    local.init()
    local_file = local_path / "app.py"
    local_file.write_text("v1\n", encoding="utf-8")
    local.commit("v1", [local_file])
    local.add_remote("origin", str(origin))

    info = AppUpdater(local).check()

    assert info["state"] == UpdateState.UNVERIFIED
    assert info["update_available"] is False
    assert info["target_revision"] == ""
    assert "no verifiable upstream" in info["detail"]
