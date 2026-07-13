import shutil

import pytest

from stockroom.mutation.project_ops import ProjectOps
from stockroom.store.project_store import ProjectStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _ops(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repo = GitRepo(repo_root)
    repo.init()
    (repo_root / "seed.txt").write_text("seed", encoding="utf-8")
    repo.commit("seed", [repo_root / "seed.txt"])
    store = ProjectStore(repo_root / ".projects", repo)
    return ProjectOps(store)


def _make_project(dir_path, sheet_body):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text("(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8")
    return dir_path


_UNANNOTATED = (
    '  (symbol\n'
    '    (lib_id "Device:R")\n'
    '    (property "Reference" "R?" (at 0 0 0))\n'
    '    (property "Value" "10k" (at 0 0 0))\n'
    '    (property "Footprint" "" (at 0 0 0))\n'
    '  )\n'
)


def test_register_list_get_delete_delegate_to_the_store(tmp_path):
    ops = _ops(tmp_path)
    proj = _make_project(tmp_path / "ext" / "board", _UNANNOTATED)
    rec = ops.register(proj)
    assert rec.name == "board"
    assert [r.id for r in ops.list()] == [rec.id]
    assert ops.get(rec.id) == rec
    ops.delete(rec.id)
    assert ops.get(rec.id) is None


def test_audit_reads_the_registered_sheets(tmp_path):
    ops = _ops(tmp_path)
    rec = ops.register(_make_project(tmp_path / "ext" / "board", _UNANNOTATED))
    au = ops.audit(rec.id)
    assert au["project"] == "board"  # named for the record, not the sheet stem
    assert au["components"] == 1
    kinds = {(f["ref"], f["kind"]) for f in au["findings"]}
    assert ("R?", "unannotated") in kinds
    assert ("R?", "no_footprint") in kinds


def test_audit_missing_project_raises(tmp_path):
    ops = _ops(tmp_path)
    with pytest.raises(FileNotFoundError):
        ops.audit("nope")
