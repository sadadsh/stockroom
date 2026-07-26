"""The library-version pin: a project records WHICH library commit it was last resolved against.

Batch 2 item 2. Without it, two peers sitting on the same PROJECT commit can resolve different
footprints, different symbols and a different BOM, and git will never tell them, because the library
is a separate repository whose HEAD moves independently. The pin is a lockfile: it lives in the
project's OWN repo so it travels with the project commit, and it names the library by identity
(remote + profile) and by commit.

Every case here is exercised against REAL git repositories rather than a stubbed ancestry, because
the whole value of the feature is git's own answer to "does this machine have that commit".
"""

from __future__ import annotations

import json
import shutil

import pytest

from stockroom.projects import library_pin as lp
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path, name, files=None):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    repo.init()
    _commit(repo, root, files or {"seed.txt": "seed\n"}, "seed")
    return root, repo


def _commit(repo, root, files, message):
    written = []
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        written.append(p)
    repo.commit(message, written)
    return repo.head()


# --- the record itself -------------------------------------------------------------------


def test_a_pin_round_trips_through_canonical_json(tmp_path):
    pin = lp.LibraryPin(
        profile="Stockroom",
        remote="https://github.com/sadadsh/stockroom.git",
        commit="a" * 40,
        pinned_at="2026-07-25T06:00:00+00:00",
    )
    text = pin.dumps()
    assert text.endswith("\n")
    # canonical: sorted keys, 2-space indent, so a one-field change is a one-line diff
    assert json.loads(text) == json.loads(json.dumps(json.loads(text), sort_keys=True))
    assert lp.LibraryPin.loads(text) == pin


def test_the_pin_records_the_schema_version_so_an_older_build_can_refuse_a_newer_pin():
    pin = lp.LibraryPin(profile="p", remote="", commit="b" * 40, pinned_at="x")
    assert json.loads(pin.dumps())["schema"] == lp.SCHEMA_VERSION


def test_an_unreadable_pin_is_reported_not_swallowed(tmp_path):
    (tmp_path / lp.PIN_FILENAME).write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        lp.read_pin(tmp_path)


def test_no_pin_file_reads_as_none(tmp_path):
    assert lp.read_pin(tmp_path) is None


# --- evaluation against a real library repo ----------------------------------------------


def test_an_unpinned_project_says_so_and_is_not_an_error(tmp_path):
    _lib_root, lib = _repo(tmp_path, "lib")
    verdict = lp.evaluate(None, lib, profile="Stockroom")
    assert verdict.status == lp.UNPINNED
    assert verdict.severity == "notice"
    assert verdict.remedy


def test_the_same_commit_is_a_match(tmp_path):
    _lib_root, lib = _repo(tmp_path, "lib")
    pin = lp.LibraryPin(profile="Stockroom", remote="", commit=lib.head(), pinned_at="t")
    verdict = lp.evaluate(pin, lib, profile="Stockroom")
    assert verdict.status == lp.MATCH
    assert verdict.severity == "ok"
    assert verdict.ahead == 0 and verdict.behind == 0


def test_a_library_that_moved_on_since_the_pin_is_AHEAD_and_counts_the_commits(tmp_path):
    lib_root, lib = _repo(tmp_path, "lib")
    pinned = lib.head()
    _commit(lib, lib_root, {"a.txt": "1\n"}, "add a")
    _commit(lib, lib_root, {"b.txt": "2\n"}, "add b")
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Stockroom", remote="", commit=pinned, pinned_at="t"),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.LIBRARY_AHEAD
    assert verdict.ahead == 2 and verdict.behind == 0
    assert verdict.severity == "notice"


def test_a_machine_whose_library_is_OLDER_than_the_pin_is_the_dangerous_case(tmp_path):
    """The peer literally does not have the parts the project references. This is the case the
    whole item exists for, so it must be a PROBLEM, never a notice."""
    lib_root, lib = _repo(tmp_path, "lib")
    old = lib.head()
    newer = _commit(lib, lib_root, {"a.txt": "1\n"}, "add a")
    # rewind this machine's library to the older commit
    lib._run("reset", "--hard", old)
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Stockroom", remote="", commit=newer, pinned_at="t"),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.LIBRARY_BEHIND
    assert verdict.behind == 1 and verdict.ahead == 0
    assert verdict.severity == "problem"
    assert "pull" in verdict.remedy.lower()


def test_two_libraries_that_both_moved_are_DIVERGED(tmp_path):
    lib_root, lib = _repo(tmp_path, "lib")
    base = lib.head()
    theirs = _commit(lib, lib_root, {"a.txt": "theirs\n"}, "theirs")
    lib._run("reset", "--hard", base)
    _commit(lib, lib_root, {"b.txt": "ours\n"}, "ours")
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Stockroom", remote="", commit=theirs, pinned_at="t"),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.DIVERGED
    assert verdict.severity == "problem"


def test_a_commit_this_machine_has_never_seen_is_reported_as_unknown_not_as_diverged(tmp_path):
    """A pin naming a commit that is simply not fetched yet has a different remedy from a real
    divergence, so collapsing the two would send the user to the wrong action."""
    _lib_root, lib = _repo(tmp_path, "lib")
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Stockroom", remote="", commit="c" * 40, pinned_at="t"),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.UNKNOWN_COMMIT
    assert verdict.severity == "problem"
    assert "fetch" in verdict.remedy.lower()


def test_a_pin_naming_a_different_library_wins_over_every_commit_comparison(tmp_path):
    """Comparing commits across two unrelated repos is meaningless, so identity is checked FIRST."""
    _lib_root, lib = _repo(tmp_path, "lib")
    lib.add_remote("origin", "https://github.com/someone/other-library.git")
    verdict = lp.evaluate(
        lp.LibraryPin(
            profile="Stockroom",
            remote="https://github.com/sadadsh/stockroom.git",
            commit=lib.head(),
            pinned_at="t",
        ),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.DIFFERENT_LIBRARY
    assert verdict.severity == "problem"


def test_remote_identity_ignores_the_dot_git_suffix_and_case(tmp_path):
    """The same GitHub repo cloned over https with and without `.git` is ONE library; reporting it
    as a different library would be a false alarm on the most ordinary setup there is."""
    _lib_root, lib = _repo(tmp_path, "lib")
    lib.add_remote("origin", "https://github.com/SadadSH/Stockroom.git")
    verdict = lp.evaluate(
        lp.LibraryPin(
            profile="Stockroom",
            remote="https://github.com/sadadsh/stockroom",
            commit=lib.head(),
            pinned_at="t",
        ),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.MATCH


def test_remote_identity_treats_a_windows_drive_letter_as_a_path_not_an_scp_host(tmp_path):
    """`C:\\libs\\stockroom` is a local path, but it looks exactly like scp-style `host:path`. Parsed
    as scp it would collapse the drive letter into a hostname, and two different drives could then
    normalize onto each other. The owner runs Windows, so this is the ordinary case, not an edge."""
    assert lp.normalize_remote(r"C:\libs\stockroom") != lp.normalize_remote(r"D:\libs\stockroom")
    assert "c/" not in lp.normalize_remote(r"C:\libs\stockroom")
    # and the real scp form still parses as scp
    assert lp.normalize_remote("git@github.com:sadadsh/stockroom.git") == "github.com/sadadsh/stockroom"


def test_remote_identity_is_stable_across_the_forms_of_one_url():
    same = {
        lp.normalize_remote("https://github.com/sadadsh/stockroom.git"),
        lp.normalize_remote("https://github.com/sadadsh/stockroom"),
        lp.normalize_remote("https://github.com/sadadsh/stockroom/"),
        lp.normalize_remote("git@github.com:sadadsh/stockroom.git"),
        lp.normalize_remote("ssh://git@github.com/sadadsh/stockroom.git"),
        lp.normalize_remote("https://token:x@github.com/sadadsh/stockroom.git"),
    }
    assert same == {"github.com/sadadsh/stockroom"}
    assert lp.normalize_remote("") == ""


def test_a_pin_taken_against_another_profile_is_reported(tmp_path):
    _lib_root, lib = _repo(tmp_path, "lib")
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Archive", remote="", commit=lib.head(), pinned_at="t"),
        lib, profile="Stockroom",
    )
    assert verdict.status == lp.DIFFERENT_PROFILE
    assert verdict.severity == "problem"


def test_a_library_with_no_git_cannot_be_compared_and_says_that_honestly(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    repo = GitRepo(root)
    verdict = lp.evaluate(
        lp.LibraryPin(profile="Stockroom", remote="", commit="d" * 40, pinned_at="t"),
        repo, profile="Stockroom",
    )
    assert verdict.status == lp.LIBRARY_NOT_GIT
    assert verdict.severity == "problem"


def test_every_status_carries_a_detail_and_a_remedy(tmp_path):
    """A status the UI cannot explain is a status that gets rendered as a bare word. Guards against
    a future status being added with no sentence behind it."""
    for status in lp.ALL_STATUSES:
        assert lp.STATUS_TEXT[status].detail
        assert lp.STATUS_TEXT[status].remedy
        assert lp.STATUS_TEXT[status].severity in ("ok", "notice", "problem")
