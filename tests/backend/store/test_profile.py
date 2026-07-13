import shutil

import pytest

from stockroom.store.profile import ProfileLibrary, ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _store(tmp_path):
    repo = GitRepo(tmp_path)
    repo.init()
    (tmp_path / "seed.txt").write_text("seed")
    repo.commit("seed", [tmp_path / "seed.txt"])
    return ProfileStore(tmp_path / "libraries", repo)


def test_library_layout_paths(tmp_path):
    lib = ProfileLibrary(tmp_path / "Main")
    assert lib.parts_dir == tmp_path / "Main" / "parts"
    assert lib.symbols_dir == tmp_path / "Main" / "symbols"
    assert lib.symbol_lib_path("ICs") == tmp_path / "Main" / "symbols" / "SR-ICs.kicad_sym"
    assert lib.footprint_lib_path("ICs") == tmp_path / "Main" / "footprints" / "SR-ICs.pretty"


def test_ensure_layout_creates_five_subdirs_with_gitkeep(tmp_path):
    lib = ProfileLibrary(tmp_path / "Main")
    keeps = lib.ensure_layout()
    for sub in ("parts", "symbols", "footprints", "models", "datasheets"):
        assert (tmp_path / "Main" / sub / ".gitkeep").exists()
    assert len(keeps) == 5


def test_create_profile_commits_and_lists(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    assert store.exists("Main")
    assert store.list() == ["Main"]
    assert store.repo.is_clean()  # create committed everything


def test_create_rejects_duplicate(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    with pytest.raises(ValueError):
        store.create("Main")


def test_create_rejects_unsafe_name(tmp_path):
    store = _store(tmp_path)
    for bad in ("../evil", "a/b", "", "."):
        with pytest.raises(ValueError):
            store.create(bad)


def test_delete_removes_folder_in_a_commit(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    store.create("Bench")
    store.delete("Bench")
    assert not store.exists("Bench")
    assert store.list() == ["Main"]
    assert store.repo.is_clean()


def test_delete_refuses_last_profile(tmp_path):
    store = _store(tmp_path)
    store.create("Main")
    with pytest.raises(ValueError):
        store.delete("Main")
