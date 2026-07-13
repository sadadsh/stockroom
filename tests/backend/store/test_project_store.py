import shutil

import pytest

from stockroom.model.project import ProjectRecord
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _store(tmp_path):
    # The library git repo lives at <tmp>/repo so <tmp> itself is NOT under git;
    # external project dirs created elsewhere under <tmp> then resolve git_root to
    # None (nothing above them holds .git) unless we plant a .git ourselves.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo = GitRepo(repo_root)
    repo.init()
    (repo_root / "seed.txt").write_text("seed", encoding="utf-8")
    repo.commit("seed", [repo_root / "seed.txt"])
    return ProjectStore(repo_root / "projects", repo)


def _make_project(dir_path, name="board"):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{name}.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / f"{name}.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    (dir_path / f"{name}.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    (dir_path / "power.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")
    return dir_path


def test_register_discovers_files_and_commits(tmp_path):
    store = _store(tmp_path)
    proj_dir = _make_project(tmp_path / "ext" / "board")
    rec = store.register(proj_dir)
    assert isinstance(rec, ProjectRecord)
    assert rec.name == "board"
    assert rec.root == proj_dir.as_posix()
    assert rec.pro_path == "board.kicad_pro"
    assert rec.board_paths == ["board.kicad_pcb"]
    # sheets are relative to root, sorted; both the top sheet and the sub-sheet.
    assert rec.sheet_paths == ["board.kicad_sch", "power.kicad_sch"]
    assert rec.registered_at  # a provenance timestamp was stamped
    # the record JSON was written under projects/ and the write was committed
    assert (store.projects_root / f"{rec.id}.json").exists()
    assert store.repo.is_clean()


def test_register_resolves_git_root_by_walking_up(tmp_path):
    store = _store(tmp_path)
    # a project two levels under a dir that holds .git
    workspace = tmp_path / "ws"
    (workspace / ".git").mkdir(parents=True)
    proj_dir = _make_project(workspace / "boards" / "board")
    rec = store.register(proj_dir)
    assert rec.git_root == workspace.as_posix()


def test_register_reports_no_git_root_when_not_under_git(tmp_path):
    store = _store(tmp_path)
    proj_dir = _make_project(tmp_path / "loose" / "board")
    rec = store.register(proj_dir)
    assert rec.git_root is None


def test_register_rejects_a_dir_with_no_kicad_files(tmp_path):
    store = _store(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        store.register(empty)


def test_register_rejects_a_nonexistent_dir(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.register(tmp_path / "does" / "not" / "exist")


def test_register_rejects_the_same_root_twice(tmp_path):
    store = _store(tmp_path)
    proj_dir = _make_project(tmp_path / "ext" / "board")
    store.register(proj_dir)
    with pytest.raises(ValueError):
        store.register(proj_dir)


def test_register_dedups_ids_for_same_name_different_roots(tmp_path):
    store = _store(tmp_path)
    a = store.register(_make_project(tmp_path / "a" / "board", name="board"))
    b = store.register(_make_project(tmp_path / "b" / "board", name="board"))
    assert a.id == "board"
    assert b.id == "board-2"


def test_list_returns_records_sorted_by_name(tmp_path):
    store = _store(tmp_path)
    store.register(_make_project(tmp_path / "z" / "zeta", name="zeta"))
    store.register(_make_project(tmp_path / "a" / "alpha", name="alpha"))
    names = [r.name for r in store.list()]
    assert names == ["alpha", "zeta"]


def test_get_returns_the_record_or_none(tmp_path):
    store = _store(tmp_path)
    rec = store.register(_make_project(tmp_path / "ext" / "board"))
    assert store.get(rec.id) == rec
    assert store.get("nope") is None


def test_delete_removes_the_record_never_the_external_files(tmp_path):
    store = _store(tmp_path)
    proj_dir = _make_project(tmp_path / "ext" / "board")
    rec = store.register(proj_dir)
    store.delete(rec.id)
    assert store.get(rec.id) is None
    assert not (store.projects_root / f"{rec.id}.json").exists()
    assert store.repo.is_clean()
    # the external KiCad files are untouched: Stockroom never owns them.
    assert (proj_dir / "board.kicad_pcb").exists()


def test_delete_missing_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(FileNotFoundError):
        store.delete("nope")
