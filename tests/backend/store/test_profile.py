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


def test_create_commits_the_profile_even_when_a_gitignore_covers_its_keepfiles(tmp_path):
    # The phantom-profile bug: a library .gitignore that covers the profile's structural keepfiles
    # made `git add` skip them, so the folder landed on disk but never entered git (the app then
    # listed it, sync read 0/0 "synced", yet it never reached the remote). create must FORCE-commit
    # its own scaffold so a profile can never be a phantom.
    repo = GitRepo(tmp_path)
    repo.init()
    (tmp_path / "libraries").mkdir()
    (tmp_path / "libraries" / ".gitignore").write_text(".gitkeep\n")
    repo.commit("seed a keepfile-ignoring gitignore", [tmp_path / "libraries" / ".gitignore"])
    store = ProfileStore(tmp_path / "libraries", repo)

    store.create("Stockroom")

    assert store.exists("Stockroom")
    # the scaffold is actually IN GIT, not merely on disk, and nothing is left uncommitted
    assert repo._is_tracked(tmp_path / "libraries" / "Stockroom" / "parts" / ".gitkeep")
    assert repo.is_clean()


def test_a_failed_create_leaves_no_phantom_profile_on_disk(tmp_path, monkeypatch):
    # create writes the folder to disk BEFORE committing; if the commit cannot happen, the folder
    # must be rolled back so the app never lists a directory that is not a real committed profile.
    from stockroom.vcs.repo import GitError

    store = _store(tmp_path)

    def boom(*a, **k):
        raise GitError("commit failed")

    monkeypatch.setattr(store.repo, "commit", boom)
    with pytest.raises(GitError):
        store.create("Ghost")
    assert not (store.libraries_root / "Ghost").exists()  # rolled back: no phantom


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
