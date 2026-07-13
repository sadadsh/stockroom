import shutil

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.lib_table import LibTable
from stockroom.kicad.wiring import KiCadWiring
from stockroom.model.category import CATEGORIES, category_symbol_lib
from stockroom.kicad.common_json import read_env_var
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo
from tests.backend.conftest import requires_kicad_cli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _profile(tmp_path):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    return store.create("Main")


def _kicad_dir(tmp_path, fixtures_dir):
    kdir = tmp_path / "kicad" / "10.0"
    kdir.mkdir(parents=True)
    shutil.copyfile(fixtures_dir / "sym-lib-table.sample", kdir / "sym-lib-table")
    shutil.copyfile(fixtures_dir / "fp-lib-table.sample", kdir / "fp-lib-table")
    shutil.copyfile(fixtures_dir / "kicad_common.sample.json", kdir / "kicad_common.json")
    return kdir


@requires_kicad_cli
def test_apply_registers_all_categories_and_sets_sr_lib(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: False)
    report = wiring.apply(profile)

    assert report.symbol_rows_added == len(CATEGORIES)
    assert report.footprint_rows_added == len(CATEGORIES)
    assert report.restart_needed is False

    sym = LibTable.load(kdir / "sym-lib-table")
    # existing rows preserved, all SR- rows added
    assert "MySymbols" in sym.entries()
    assert "SR-ICs" in sym.entries()
    assert sym.entries().count("SR-Resistors") == 1

    # SR_LIB points at the profile folder
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root)

    # category libs were created on disk
    assert profile.library.symbol_lib_path("ICs").exists()
    assert profile.library.footprint_lib_path("ICs").is_dir()


@requires_kicad_cli
def test_apply_is_idempotent(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: False)
    wiring.apply(profile)
    sym_before = (kdir / "sym-lib-table").read_bytes()
    report2 = wiring.apply(profile)
    assert report2.symbol_rows_added == 0
    assert report2.footprint_rows_added == 0
    assert (kdir / "sym-lib-table").read_bytes() == sym_before


@requires_kicad_cli
def test_apply_flags_restart_when_kicad_running(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=KiCadCli(), running_detector=lambda: True)
    report = wiring.apply(profile)
    assert report.kicad_running is True
    assert report.restart_needed is True


def test_apply_without_cli_and_precreated_libs_is_pure_python(tmp_path, fixtures_dir):
    # exercise the wiring logic without kicad-cli by pre-creating empty category
    # libs by hand (valid empty .kicad_sym) so create_empty_symbol_lib is a no-op.
    profile = _profile(tmp_path)
    empty = '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n'
    for cat in CATEGORIES:
        (profile.library.symbols_dir / category_symbol_lib(cat)).write_text(empty, newline="")
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=None, running_detector=lambda: False)
    report = wiring.apply(profile)
    assert report.symbol_rows_added == len(CATEGORIES)
    assert report.libs_created == []  # nothing needed creating
