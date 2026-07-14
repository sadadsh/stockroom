import shutil

import pytest

from stockroom.vcs.repo import GitError, GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path):
    r = GitRepo(tmp_path)
    r.init()
    return r


def test_init_and_empty_head(tmp_path):
    r = _repo(tmp_path)
    assert r.is_git_repo()
    assert r.head() == ""


def test_commit_returns_sha_and_advances_head(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    sha = r.commit("Add a", [tmp_path / "a.txt"])
    assert len(sha) == 40
    assert r.head() == sha
    assert r.is_clean()


def test_commit_sets_a_fallback_identity_when_none_is_configured(tmp_path, monkeypatch):
    # The library committed inside the app repo is cloned by the launcher's RAW `git clone` (never
    # GitRepo.init/clone_from, which set the fallback identity), so on a fresh machine with no global
    # git identity its first part commit must still work. Null the global + system config so only a
    # LOCAL identity (which commit() now sets when missing) can satisfy git.
    import subprocess

    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    root = tmp_path / "lib"
    root.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)  # no identity
    (root / "p.json").write_text("{}", encoding="utf-8")
    sha = GitRepo(root).commit("Add p", [root / "p.json"])  # must not raise "who are you"
    assert len(sha) == 40


def test_commit_only_stages_listed_paths(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    r.commit("Add a only", [tmp_path / "a.txt"])
    # b.txt is still untracked => not clean
    assert not r.is_clean()
    assert any("b.txt" in line for line in r.status_porcelain())


def test_commit_rejects_empty_message(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("a")
    with pytest.raises(GitError):
        r.commit("", [tmp_path / "a.txt"])


def test_log_paths(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "a.txt").write_text("1")
    r.commit("first", [tmp_path / "a.txt"])
    (tmp_path / "a.txt").write_text("2")
    r.commit("second", [tmp_path / "a.txt"])
    log = r.log_paths([tmp_path / "a.txt"])
    assert [c.subject for c in log] == ["second", "first"]
    assert all(len(c.sha) == 40 for c in log)


def test_show_file_reads_content_at_a_rev(tmp_path):
    r = _repo(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("v1")
    first = r.commit("first", [f])
    f.write_text("v2")
    r.commit("second", [f])
    # the working tree now holds v2; show_file reads the blob at the old rev
    assert r.show_file(first, f) == "v1"


def test_show_file_accepts_a_subtree_path(tmp_path):
    r = _repo(tmp_path)
    sub = tmp_path / "parts"
    sub.mkdir()
    f = sub / "x.json"
    f.write_text('{"k": 1}\n')
    sha = r.commit("add x", [f])
    assert r.show_file(sha, f) == '{"k": 1}\n'
    # a relative path (repo-relative) resolves identically
    assert r.show_file(sha, "parts/x.json") == '{"k": 1}\n'


def test_show_file_returns_none_when_absent_at_rev(tmp_path):
    r = _repo(tmp_path)
    a = tmp_path / "a.txt"
    a.write_text("a")
    first = r.commit("first", [a])
    b = tmp_path / "b.txt"
    b.write_text("b")
    r.commit("add b", [b])
    # b did not exist at the first rev
    assert r.show_file(first, b) is None


def test_restore_reverts_tracked_modification(tmp_path):
    r = _repo(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("original")
    r.commit("add", [f])
    f.write_text("scribbled")
    r.restore_paths([f])
    assert f.read_text() == "original"
    assert r.is_clean()


def test_restore_deletes_untracked_created_file(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "keep.txt").write_text("keep")
    r.commit("base", [tmp_path / "keep.txt"])
    created = tmp_path / "new.txt"
    created.write_text("scratch")
    r.restore_paths([created])
    assert not created.exists()
    assert r.is_clean()


def test_restore_deletes_untracked_created_dir(tmp_path):
    r = _repo(tmp_path)
    (tmp_path / "keep.txt").write_text("keep")
    r.commit("base", [tmp_path / "keep.txt"])
    d = tmp_path / "sub"
    d.mkdir()
    (d / "x.txt").write_text("x")
    r.restore_paths([d])
    assert not d.exists()


def test_pull_ff_and_push_against_local_bare_remote(tmp_path):
    # origin = bare repo; clone A commits+pushes; clone B pulls ff.
    origin = tmp_path / "origin.git"
    GitRepo(origin).init(bare=True)
    a = GitRepo(tmp_path / "a")
    a.clone_from(origin)
    (a.root / "f.txt").write_text("v1")
    a.commit("v1", [a.root / "f.txt"])
    assert a.push().ok

    b = GitRepo(tmp_path / "b")
    b.clone_from(origin)
    assert (b.root / "f.txt").read_text() == "v1"

    (a.root / "f.txt").write_text("v2")
    a.commit("v2", [a.root / "f.txt"])
    a.push()
    res = b.pull_ff()
    assert res.ok and res.updated
    assert (b.root / "f.txt").read_text() == "v2"


def test_pull_ff_reports_non_fast_forward(tmp_path):
    origin = tmp_path / "origin.git"
    GitRepo(origin).init(bare=True)
    a = GitRepo(tmp_path / "a")
    a.clone_from(origin)
    (a.root / "f.txt").write_text("base")
    a.commit("base", [a.root / "f.txt"])
    a.push()

    b = GitRepo(tmp_path / "b")
    b.clone_from(origin)

    # A advances remote; B makes a divergent local commit.
    (a.root / "f.txt").write_text("remote-change")
    a.commit("remote", [a.root / "f.txt"])
    a.push()
    (b.root / "g.txt").write_text("local-change")
    b.commit("local", [b.root / "g.txt"])

    res = b.pull_ff()
    assert not res.ok
    assert "fast-forward" in res.reason.lower() or "diverg" in res.reason.lower()
