import shutil

import pytest

from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo


@pytest.fixture
def library_ops(tmp_path):
    """A clean, git-backed LibraryOps over a fresh temp 'Main' profile (no KiCad assets
    needed). Mirrors the setup in tests/backend/mutation/test_library_ops.py."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    return LibraryOps(profile, repo)
