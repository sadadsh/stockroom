"""git-lfs adoption, exercised against REAL repositories and the real `git lfs` binary.

Batch 2 item 4. Nothing here mocks the CLI, because every fact this module reports is a fact about
what git and git-lfs actually do, and the two measured surprises behind the design (a `merge=lfs`
pointer merge corrupts the pointer; a `lockable` file is checked out read-only and cannot be
unlocked without a remote) were both invisible to reasoning and obvious to a real run.

PRIOR ART: no test infrastructure is introduced. Real temp repos through `GitRepo`, exactly as
`tests/backend/mutation/test_workspace_hygiene.py` and `test_library_pin.py` already do.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from stockroom.eda.registry import workspace_gitattributes
from stockroom.vcs import lfs
from stockroom.vcs.repo import GitRepo


def _lfs_present() -> bool:
    if shutil.which("git") is None:
        return False
    return subprocess.run(["git", "lfs", "version"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _lfs_present(), reason="git-lfs not installed")


@pytest.fixture
def no_global_lfs(tmp_path, monkeypatch):
    """Run git with EMPTY global and system config.

    Without this the result depends on the machine: `git lfs install` defaults to writing the
    filter into the user's GLOBAL config, so on a developer box every fresh repo already resolves
    `filter.lfs.clean` and the "not adopted yet" and "attributes are inert without the filter"
    cases cannot be reproduced at all, while on a bare CI runner they can. A test whose answer
    depends on who is running it is not testing the code.
    """
    empty = tmp_path / "empty-gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(empty))
    return empty


def _repo(tmp_path, name="lib"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    seed = root / "seed.txt"
    seed.write_text("seed\n", encoding="utf-8")
    repo.commit("seed", [seed])
    return root, repo


def test_a_repo_that_has_never_adopted_lfs_says_so_without_pretending(tmp_path, no_global_lfs):
    _root, repo = _repo(tmp_path)
    st = lfs.status(repo)
    assert st.installed is True
    assert st.enabled is False
    assert st.tracked_patterns == ()
    assert st.objects == 0


def test_enabling_is_repo_local_and_idempotent(tmp_path):
    root, repo = _repo(tmp_path)
    lfs.enable(repo)
    assert lfs.repo_enabled(repo) is True
    lfs.enable(repo)  # again: must not fail
    # --local, never global: Stockroom does not reconfigure somebody's whole git installation
    local = (root / ".git" / "config").read_text(encoding="utf-8")
    assert "filter \"lfs\"" in local or "[filter \"lfs\"]" in local


def test_track_output_parser_preserves_tracked_patterns_and_ignores_exclusions():
    output = """\
Listing tracked patterns
    *.pcblib (.gitattributes)
    assets/(approved)/*.STEP (.gitattributes)
Listing excluded patterns
    vendor/** (.git/info/attributes)
"""

    assert lfs._parse_tracked_patterns(output) == (
        "*.pcblib",
        "assets/(approved)/*.STEP",
    )


def test_a_binary_really_becomes_a_POINTER_once_the_filter_and_rules_are_both_in_place(tmp_path):
    """The end-to-end proof. Attributes ALONE are inert: git happily stores the file normally and
    reports nothing, so a test that only asserted the .gitattributes content would pass while the
    feature did nothing at all."""
    root, repo = _repo(tmp_path)
    lfs.enable(repo)
    (root / ".gitattributes").write_text(
        workspace_gitattributes(["altium"], lfs=True), encoding="utf-8"
    )
    payload = root / "part.PcbLib"
    payload.write_bytes(b"OLE2 compound bytes" * 100)
    repo.commit("add a compound library", [root / ".gitattributes", payload])

    # what git STORES is a pointer, while the working tree still holds the real bytes
    blob = repo._run("cat-file", "-p", "HEAD:part.PcbLib").stdout
    assert blob.startswith("version https://git-lfs.github.com/spec/v1")
    assert "oid sha256:" in blob
    assert payload.read_bytes().startswith(b"OLE2 compound bytes")

    st = lfs.status(repo)
    assert st.enabled is True
    assert st.objects == 1
    assert any("pcblib" in p.casefold() for p in st.tracked_patterns)


def test_attributes_without_the_filter_store_the_file_normally_and_say_nothing(
    tmp_path, no_global_lfs
):
    """The trap this module exists to close. Anyone hand-writing .gitattributes gets this silently
    wrong, which is why enabling the filter is part of applying the rules, never a separate step
    someone has to remember."""
    root, repo = _repo(tmp_path)
    (root / ".gitattributes").write_text(
        workspace_gitattributes(["altium"], lfs=True), encoding="utf-8"
    )
    payload = root / "part.PcbLib"
    payload.write_bytes(b"OLE2 compound bytes" * 100)
    repo.commit("add a compound library", [root / ".gitattributes", payload])

    blob = repo._run("cat-file", "-p", "HEAD:part.PcbLib").stdout
    assert not blob.startswith("version https://git-lfs.github.com/spec/v1")
    assert lfs.status(repo).enabled is False


def test_a_binary_committed_BEFORE_lfs_stays_a_plain_blob_and_is_counted(tmp_path):
    """Adopting LFS does not shrink existing history; only NEW commits become pointers. Converting
    the past needs `git lfs migrate`, which rewrites history and needs a force-push, which this
    project forbids. So the limitation is REPORTED rather than implied away."""
    root, repo = _repo(tmp_path)
    payload = root / "old.PcbLib"
    payload.write_bytes(b"committed before anyone had heard of lfs")
    repo.commit("add a compound library the old way", [payload])

    lfs.enable(repo)
    (root / ".gitattributes").write_text(
        workspace_gitattributes(["altium"], lfs=True), encoding="utf-8"
    )
    repo.commit("adopt lfs", [root / ".gitattributes"])

    st = lfs.status(repo)
    assert st.objects == 0
    assert st.legacy_blobs == 1


def test_locking_is_refused_honestly_on_a_repo_with_no_remote(tmp_path):
    """MEASURED: `git lfs lock` fails with `missing protocol: ""` when there is no remote, so a
    lockable file there is checked out read-only with no way back. The probe has to say so BEFORE
    anyone turns lockable on, not after."""
    _root, repo = _repo(tmp_path)
    lfs.enable(repo)
    ok, reason = lfs.locking_probe(repo)
    assert ok is False
    assert "remote" in reason.lower()


def test_status_on_a_machine_without_git_lfs_is_an_honest_report_not_a_crash(tmp_path, monkeypatch):
    _root, repo = _repo(tmp_path)
    monkeypatch.setattr(lfs, "available", lambda: (False, ""))
    st = lfs.status(repo)
    assert st.installed is False
    assert st.enabled is False
    assert "not installed" in st.reason


def test_enable_refuses_rather_than_half_configuring_when_lfs_is_absent(tmp_path, monkeypatch):
    _root, repo = _repo(tmp_path)
    monkeypatch.setattr(lfs, "available", lambda: (False, ""))
    with pytest.raises(RuntimeError, match="not installed"):
        lfs.enable(repo)
