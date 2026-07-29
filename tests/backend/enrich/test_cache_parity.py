from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.enrich.cache import TtlCache
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def test_per_device_cache_never_dirties_the_synced_repository(tmp_path: Path) -> None:
    repo = GitRepo(tmp_path / "library")
    repo.init()
    tracked = repo.root / "README.md"
    tracked.write_text("library\n", encoding="utf-8")
    repo.commit("initialize", [tracked])

    cache = TtlCache(repo.root / ".stockroom-enrich-cache")
    cache.put("TPD6E05U06RVZR", {"source": "device-local"})

    assert repo.status_porcelain() == []
    assert (cache.root / ".gitignore").read_text(encoding="utf-8").endswith("*\n")
