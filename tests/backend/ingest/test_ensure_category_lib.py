import shutil

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.mutation.library_ops import LibraryOps, StagedPart
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = [
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
    requires_kicad_cli,
]


def _staged(tmp_path, fixtures_dir):
    sym = tmp_path / "one_symbol.kicad_sym"
    fp = tmp_path / "one_footprint.kicad_mod"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp)
    return StagedPart(
        display_name="Part",
        category="Diodes",
        symbol_source=sym,
        symbol_source_name="TESTPART",
        footprint_source=fp,
        entry_name="MYDIODE",
    )


def test_add_part_creates_missing_category_lib(tmp_path, fixtures_dir):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    # Deliberately do NOT pre-create the Diodes symbol lib.
    ops = LibraryOps(profile, repo, cli=KiCadCli())
    ops.add_part(_staged(tmp_path, fixtures_dir), require_complete=False)
    sym_lib_path = profile.library.symbol_lib_path("Diodes")
    assert sym_lib_path.exists()
    assert "MYDIODE" in SymbolLib.load(sym_lib_path).symbol_names
