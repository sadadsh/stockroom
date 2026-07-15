import shutil

import pytest

from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.lib_table import LibTable
from stockroom.kicad.wiring import KiCadWiring, auto_wire
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


def _precreate_category_libs(profile) -> None:
    """Valid empty .kicad_sym per category, by hand, so wiring never needs kicad-cli."""
    empty = '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n'
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (profile.library.symbols_dir / category_symbol_lib(cat)).write_text(empty, newline="")


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
    _precreate_category_libs(profile)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    wiring = KiCadWiring(kdir, cli=None, running_detector=lambda: False)
    report = wiring.apply(profile)
    assert report.symbol_rows_added == len(CATEGORIES)
    assert report.libs_created == []  # nothing needed creating


def test_apply_creates_missing_config_dir_and_common_json(tmp_path):
    # KiCad installed but never run: the version config dir and kicad_common.json
    # do not exist yet. apply() materializes both instead of crashing.
    profile = _profile(tmp_path)
    _precreate_category_libs(profile)
    kdir = tmp_path / "fresh-kicad" / "10.0"
    report = KiCadWiring(kdir, cli=None, running_detector=lambda: False).apply(profile)
    assert kdir.is_dir()
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root.resolve())
    assert report.symbol_rows_added == len(CATEGORIES)
    assert LibTable.load(kdir / "sym-lib-table").entries().count("SR-ICs") == 1


def test_auto_wire_skips_without_kicad_evidence(tmp_path):
    # no kicad-cli, no config dir, no kicad config base: KiCad is not on this
    # machine, so auto-wiring must not invent a config tree for it
    profile = _profile(tmp_path)
    kdir = tmp_path / "nokicad" / "10.0"
    report = auto_wire(kdir, profile, cli=None)
    assert report.skipped != ""
    assert report.error == ""
    assert not kdir.exists()


def test_auto_wire_wires_when_config_dir_exists(tmp_path, fixtures_dir):
    profile = _profile(tmp_path)
    _precreate_category_libs(profile)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    report = auto_wire(kdir, profile, cli=None, running_detector=lambda: False)
    assert report.skipped == "" and report.error == ""
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root.resolve())


def test_auto_wire_captures_failure_but_still_repoints_sr_lib(tmp_path, fixtures_dir):
    # no cli and no category libs: creating them fails, and auto_wire must capture
    # that instead of raising - but SR_LIB is already correct, so a switch on a
    # cli-less machine still repoints KiCad at the right library. The table rows
    # are deliberately NOT written (they would be 13 broken libraries in KiCad).
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    report = auto_wire(kdir, profile, cli=None, running_detector=lambda: False)
    assert report.error != ""
    assert report.skipped == ""
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root.resolve())
    assert "SR-ICs" not in LibTable.load(kdir / "sym-lib-table").entries()


def test_apply_flags_restart_when_only_sr_lib_changed(tmp_path, fixtures_dir):
    # the stale-SR_LIB fix scenario: tables and libs already wired, a switch only
    # repoints SR_LIB - a running KiCad still needs a restart to read the new var
    profile = _profile(tmp_path)
    _precreate_category_libs(profile)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    KiCadWiring(kdir, cli=None, running_detector=lambda: False).apply(profile)
    other = ProfileStore(GitRepo(tmp_path / "repo").root / "libraries",
                         GitRepo(tmp_path / "repo")).create("Other")
    _precreate_category_libs(other)
    report = KiCadWiring(kdir, cli=None, running_detector=lambda: True).apply(other)
    assert report.symbol_rows_added == 0  # tables were already wired
    assert report.restart_needed is True  # but SR_LIB changed under a running KiCad


def test_apply_without_cli_skips_rows_for_missing_libs(tmp_path, fixtures_dir):
    # no cli and no category libs: registering 13 rows would leave KiCad showing
    # 13 broken libraries; SR_LIB still repoints, rows wait for a successful wire
    profile = _profile(tmp_path)
    kdir = _kicad_dir(tmp_path, fixtures_dir)
    report = auto_wire(kdir, profile, cli=None, running_detector=lambda: False)
    assert report.error != ""  # the category-lib step still failed honestly
    assert read_env_var(kdir / "kicad_common.json", "SR_LIB") == str(profile.root.resolve())
    assert "SR-ICs" not in LibTable.load(kdir / "sym-lib-table").entries()


class _FakeCli:
    def __init__(self, version_text=None):
        self._version = version_text
        self.available = version_text is not None

    def version(self):
        if self._version is None:
            raise RuntimeError("no cli")
        return self._version


def test_auto_wire_derives_the_version_from_the_cli_instead_of_fabricating_10(tmp_path):
    # KiCad 9 installed but never run: no config dirs exist; wiring must land in
    # 9.0 (the KiCad that will actually read it), not invent a 10.0 dir that
    # poisons version autodetection forever
    profile = _profile(tmp_path)
    _precreate_category_libs(profile)
    base = tmp_path / "cfg" / "kicad"
    base.mkdir(parents=True)
    report = auto_wire(base / "10.0", profile, cli=_FakeCli("9.0.2-release"),
                       running_detector=lambda: False)
    assert report.skipped == "" and report.error == ""
    assert (base / "9.0").is_dir()
    assert not (base / "10.0").exists()
    assert read_env_var(base / "9.0" / "kicad_common.json", "SR_LIB") == str(profile.root.resolve())


def test_auto_wire_skips_when_no_config_dir_and_no_version_source(tmp_path):
    profile = _profile(tmp_path)
    base = tmp_path / "cfg" / "kicad"
    base.mkdir(parents=True)
    report = auto_wire(base / "10.0", profile, cli=None, running_detector=lambda: False)
    assert report.skipped != ""
    assert not (base / "10.0").exists()
