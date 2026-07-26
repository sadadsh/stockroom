"""Pinning a project to a library version, as a real operation on two real git repos.

The pure comparison lives in `tests/backend/projects/test_library_pin.py`. This file covers the part
that touches the world: the pin is written into the PROJECT's own repo (not the library's), as one
atomic commit, and every refusal is honest rather than a silent no-op.
"""

from __future__ import annotations

import shutil

import pytest

from stockroom.mutation.project_ops import ProjectOps
from stockroom.projects import library_pin as lp
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _library(tmp_path):
    root = tmp_path / "lib"
    (root / ".projects").mkdir(parents=True)
    repo = GitRepo(root)
    repo.init()
    keep = root / ".projects" / ".gitkeep"
    keep.write_text("", encoding="utf-8")
    repo.commit("seed library", [keep])
    return root, repo


def _project(tmp_path, name="board", under_git=True):
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / f"{name}.kicad_pro").write_text("{}\n", encoding="utf-8")
    (root / f"{name}.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")
    if not under_git:
        return root, None
    repo = GitRepo(root)
    repo.init()
    repo.commit("seed project", [root / f"{name}.kicad_pro", root / f"{name}.kicad_sch"])
    return root, repo


def _ops(lib_root, lib_repo):
    return ProjectOps(ProjectStore(lib_root / ".projects", lib_repo))


def test_reading_an_unpinned_project_reports_unpinned_with_the_library_it_would_pin(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)

    read = ops.library_pin_read(rec.id, profile="Stockroom")
    assert read["status"] == lp.UNPINNED
    assert read["pinned"] is None
    assert read["library_commit"] == lib_repo.head()
    assert read["under_git"] is True


def test_the_pin_lands_in_the_projects_own_repo_and_nowhere_else(tmp_path):
    """The whole point: it must travel with the PROJECT commit, so a peer checking out that commit
    receives it. A pin recorded in the library repo would not."""
    lib_root, lib_repo = _library(tmp_path)
    proj_root, proj_repo = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    library_head_before = lib_repo.head()

    result = ops.library_pin_apply(rec.id, profile="Stockroom")

    assert (proj_root / lp.PIN_FILENAME).exists()
    assert lp.PIN_FILENAME in proj_repo._run("ls-files").stdout.split()
    assert result["committed"] == proj_repo.head()
    # The library repo is untouched by a pin. `library_head_before` is read AFTER registration, so
    # this is a real equality, not the `... or True` I first wrote here, which could never fail.
    assert lib_repo.head() == library_head_before
    assert lp.PIN_FILENAME not in lib_repo._run("ls-files").stdout.split()


def test_the_written_pin_names_the_library_commit_profile_and_remote(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    lib_repo.add_remote("origin", "https://github.com/sadadsh/stockroom.git")
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)

    ops.library_pin_apply(rec.id, profile="Stockroom")
    pin = lp.read_pin(proj_root)
    assert pin.commit == lib_repo.head()
    assert pin.profile == "Stockroom"
    assert pin.remote == "https://github.com/sadadsh/stockroom.git"
    assert pin.pinned_at


def test_pinning_then_reading_reports_a_match(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    ops.library_pin_apply(rec.id, profile="Stockroom")
    assert ops.library_pin_read(rec.id, profile="Stockroom")["status"] == lp.MATCH


def test_a_library_that_moves_after_the_pin_is_reported_as_ahead(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    ops.library_pin_apply(rec.id, profile="Stockroom")

    moved = lib_root / "parts" / "new.json"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("{}\n", encoding="utf-8")
    lib_repo.commit("add a part", [moved])

    read = ops.library_pin_read(rec.id, profile="Stockroom")
    assert read["status"] == lp.LIBRARY_AHEAD
    assert read["ahead"] == 1


def test_re_pinning_moves_the_pin_forward_in_one_new_commit(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, proj_repo = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    ops.library_pin_apply(rec.id, profile="Stockroom")
    first = proj_repo.head()

    moved = lib_root / "parts" / "new.json"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("{}\n", encoding="utf-8")
    lib_repo.commit("add a part", [moved])
    ops.library_pin_apply(rec.id, profile="Stockroom")

    assert proj_repo.head() != first
    assert lp.read_pin(proj_root).commit == lib_repo.head()
    assert ops.library_pin_read(rec.id, profile="Stockroom")["status"] == lp.MATCH


def test_re_pinning_an_unchanged_library_commits_nothing(tmp_path):
    """Re-running must not churn the project's history, the same rule workspace hygiene follows."""
    lib_root, lib_repo = _library(tmp_path)
    proj_root, proj_repo = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    ops.library_pin_apply(rec.id, profile="Stockroom")
    head = proj_repo.head()

    result = ops.library_pin_apply(rec.id, profile="Stockroom")
    assert result["committed"] is None
    assert proj_repo.head() == head


def test_a_project_with_no_git_refuses_because_the_pin_could_never_reach_a_peer(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path, name="loose", under_git=False)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)

    with pytest.raises(ValueError, match="git"):
        ops.library_pin_apply(rec.id, profile="Stockroom")
    assert not (proj_root / lp.PIN_FILENAME).exists()
    # and the READ still answers honestly instead of raising
    assert ops.library_pin_read(rec.id, profile="Stockroom")["under_git"] is False


def test_a_pin_written_by_a_newer_build_is_never_silently_overwritten(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    future = lp.LibraryPin(
        profile="Stockroom", remote="", commit="f" * 40, pinned_at="t",
        schema=lp.SCHEMA_VERSION + 1,
    )
    (proj_root / lp.PIN_FILENAME).write_text(future.dumps(), encoding="utf-8")

    with pytest.raises(ValueError, match="newer"):
        ops.library_pin_apply(rec.id, profile="Stockroom")
    assert lp.read_pin(proj_root).commit == "f" * 40


def test_the_read_carries_the_tools_path_contract_so_the_surface_never_hardcodes_SR_LIB(tmp_path):
    lib_root, lib_repo = _library(tmp_path)
    proj_root, _ = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)

    read = ops.library_pin_read(rec.id, profile="Stockroom")
    assert read["eda"] == "kicad"
    assert read["path_contract"]["kind"] == "env_var"
    assert read["path_contract"]["variable"] == "SR_LIB"
    assert read["path_contract"]["description"]


def test_a_failed_pin_leaves_no_trace(tmp_path):
    """The atomicity guarantee. A write that cannot be committed must restore the file, never leave
    a pin on disk that git does not know about."""
    lib_root, lib_repo = _library(tmp_path)
    proj_root, proj_repo = _project(tmp_path)
    ops = _ops(lib_root, lib_repo)
    rec = ops.register(proj_root)
    head = proj_repo.head()

    class Boom(GitRepo):
        def commit(self, message, paths, force=False):
            raise RuntimeError("commit exploded")

    exploding = Boom(proj_root)
    with pytest.raises(RuntimeError):
        ops.library_pin_apply(rec.id, profile="Stockroom", project_repo=exploding)
    assert not (proj_root / lp.PIN_FILENAME).exists()
    assert proj_repo.head() == head
