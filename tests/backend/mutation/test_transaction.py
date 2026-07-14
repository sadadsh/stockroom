import shutil

import pytest

from stockroom.mutation.transaction import Transaction, TransactionError
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _repo(tmp_path):
    r = GitRepo(tmp_path)
    r.init()
    (tmp_path / "base").write_text("base")
    r.commit("base", [tmp_path / "base"])
    return r


def test_commit_persists_and_advances_head(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with Transaction(repo) as txn:
        f = tmp_path / "a.json"
        f.write_text('{"ok": true}')
        txn.track(f)
        sha = txn.commit("Add a")
    assert sha != before
    assert repo.head() == sha
    assert repo.is_clean()
    assert (tmp_path / "a.json").exists()


def test_uncommitted_block_rolls_back_created_file(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with Transaction(repo) as txn:
        f = tmp_path / "a.json"
        f.write_text('{"ok": true}')
        txn.track(f)
        # no commit
    assert not (tmp_path / "a.json").exists()  # zero trace
    assert repo.head() == before
    assert repo.is_clean()


def test_exception_rolls_back(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with pytest.raises(RuntimeError):
        with Transaction(repo) as txn:
            f = tmp_path / "a.json"
            f.write_text("x")
            txn.track(f)
            raise RuntimeError("boom")
    assert not (tmp_path / "a.json").exists()
    assert repo.head() == before
    assert repo.is_clean()


def test_validate_rejects_broken_kicad_file_and_rolls_back(tmp_path):
    repo = _repo(tmp_path)
    before = repo.head()
    with pytest.raises(TransactionError):
        with Transaction(repo) as txn:
            f = tmp_path / "bad.kicad_sym"
            f.write_text("(kicad_symbol_lib (version 20251024)")  # missing close paren
            txn.track(f)
            txn.commit("should fail validation")
    assert not (tmp_path / "bad.kicad_sym").exists()
    assert repo.head() == before


def test_validate_rejects_broken_json(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(TransactionError):
        with Transaction(repo) as txn:
            f = tmp_path / "bad.json"
            f.write_text("{not json")
            txn.track(f)
            txn.commit("should fail")
    assert not (tmp_path / "bad.json").exists()


def test_validate_rejects_broken_kicad_pro(tmp_path):
    # a .kicad_pro is JSON; a malformed one must abort + roll back like a bad .json.
    repo = _repo(tmp_path)
    with pytest.raises(TransactionError):
        with Transaction(repo) as txn:
            f = tmp_path / "board.kicad_pro"
            f.write_text("{not json")
            txn.track(f)
            txn.commit("should fail")
    assert not (tmp_path / "board.kicad_pro").exists()


def test_validate_accepts_well_formed_kicad_pro(tmp_path):
    repo = _repo(tmp_path)
    with Transaction(repo) as txn:
        f = tmp_path / "board.kicad_pro"
        f.write_text('{"meta": {"version": 1}}')
        txn.track(f)
        txn.commit("add project file")
    assert (tmp_path / "board.kicad_pro").exists()


def test_rollback_restores_edited_tracked_file(tmp_path):
    repo = _repo(tmp_path)
    tracked = tmp_path / "keep.kicad_sym"
    tracked.write_text("(kicad_symbol_lib (version 20251024))")
    repo.commit("add keep", [tracked])
    with Transaction(repo) as txn:
        tracked.write_text("(kicad_symbol_lib (version 20251024) (symbol \"X\"))")
        txn.track(tracked)
        # no commit -> rollback restores original content
    assert tracked.read_text() == "(kicad_symbol_lib (version 20251024))"
