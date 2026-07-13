import shutil

import pytest

from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.kicad.footprint import Footprint
from stockroom.model.part import PartRecord
from stockroom.mutation.library_ops import LibraryOps, StagedPart
from stockroom.store.profile import ProfileStore
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _setup(tmp_path, fixtures_dir):
    repo = GitRepo(tmp_path / "repo")
    repo.init()
    (repo.root / "seed").write_text("x")
    repo.commit("seed", [repo.root / "seed"])
    store = ProfileStore(repo.root / "libraries", repo)
    profile = store.create("Main")
    # pre-create the ICs category symbol lib by hand (empty, valid, v10 stamp)
    profile.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    (profile.library.symbol_lib_path("ICs")).write_text(
        '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline=""
    )
    profile.library.footprint_lib_path("ICs").mkdir(parents=True, exist_ok=True)
    sym_src = tmp_path / "one_symbol.kicad_sym"
    fp_src = tmp_path / "one_footprint.kicad_mod"
    model_src = tmp_path / "part.step"
    ds_src = tmp_path / "part.pdf"
    shutil.copyfile(fixtures_dir / "one_symbol.kicad_sym", sym_src)
    shutil.copyfile(fixtures_dir / "one_footprint.kicad_mod", fp_src)
    model_src.write_bytes(b"ISO-10303-21;\n")  # a stand-in STEP payload
    ds_src.write_bytes(b"%PDF-1.4\n")
    staged = StagedPart(
        display_name="TPS62130 buck",
        category="ICs",
        mpn="TPS62130RGTR",
        manufacturer="TI",
        description="3A buck",
        tags=["dcdc", "buck"],
        symbol_source=sym_src,
        symbol_source_name="TESTPART",
        footprint_source=fp_src,
        entry_name="TPS62130RGTR",
        model_source=model_src,
        datasheet_source=ds_src,
    )
    return repo, profile, staged


def test_add_part_places_everything_and_commits(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    before_head = repo.head()
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)

    assert record.id == "tps62130rgtr"
    assert record.symbol == PartRecord.from_dict(record.to_dict()).symbol  # round-trips

    lib = profile.library
    # JSON written
    json_path = lib.parts_dir / "tps62130rgtr.json"
    assert json_path.exists()

    # symbol merged and named
    sym_lib = SymbolLib.load(lib.symbol_lib_path("ICs"))
    assert "TPS62130RGTR" in sym_lib.symbol_names
    sym = sym_lib.get_symbol("TPS62130RGTR")
    assert sym.get_property("Footprint") == "SR-ICs:TPS62130RGTR"
    assert sym.get_property("MPN") == "TPS62130RGTR"

    # footprint placed with a model link
    fp_path = lib.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod"
    assert fp_path.exists()
    fp = Footprint.load(fp_path)
    assert fp.model_path == "${SR_LIB}/models/TPS62130RGTR.step"

    # model + datasheet copied
    assert (lib.models_dir / "TPS62130RGTR.step").exists()
    assert (lib.datasheets_dir / "tps62130rgtr.pdf").exists()

    # exactly one new commit, clean tree
    assert repo.head() != before_head
    assert repo.is_clean()
    assert repo.log_paths([json_path])[0].subject.startswith("Add TPS62130RGTR")


def test_add_part_without_model_or_datasheet(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.model_source = None
    staged.datasheet_source = None
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)
    assert record.model is None
    fp = Footprint.load(profile.library.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod")
    assert fp.model_path is None  # no (model ...) block written


def test_add_part_rolls_back_on_duplicate_symbol(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    head_after_first = repo.head()
    # a second add with the SAME entry_name must fail the symbol merge and leave zero trace
    staged2 = StagedPart(**{**staged.__dict__})
    with pytest.raises(Exception):
        ops.add_part(staged2)
    assert repo.head() == head_after_first
    assert repo.is_clean()
    # only one part json exists
    assert len(list(profile.library.parts_dir.glob("*.json"))) == 1


def test_edit_field_updates_json_and_mirror(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    rec = ops.edit_field("tps62130rgtr", "manufacturer", "Texas Instruments")
    assert rec.manufacturer == "Texas Instruments"
    sym = SymbolLib.load(profile.library.symbol_lib_path("ICs")).get_symbol("TPS62130RGTR")
    assert sym.get_property("Manufacturer") == "Texas Instruments"
    assert repo.is_clean()


def test_move_category_relocates_symbol_and_footprint(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    # also pre-create the destination category (Modules) libs
    (profile.library.symbol_lib_path("Modules")).write_text(
        '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline=""
    )
    profile.library.footprint_lib_path("Modules").mkdir(parents=True, exist_ok=True)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    rec = ops.move_category("tps62130rgtr", "Modules")

    assert rec.category == "Modules"
    assert rec.symbol.lib == "SR-Modules"
    # gone from ICs, present in Modules
    assert "TPS62130RGTR" not in SymbolLib.load(profile.library.symbol_lib_path("ICs")).symbol_names
    assert "TPS62130RGTR" in SymbolLib.load(profile.library.symbol_lib_path("Modules")).symbol_names
    assert not (profile.library.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod").exists()
    assert (profile.library.footprint_lib_path("Modules") / "TPS62130RGTR.kicad_mod").exists()
    sym = SymbolLib.load(profile.library.symbol_lib_path("Modules")).get_symbol("TPS62130RGTR")
    assert sym.get_property("Footprint") == "SR-Modules:TPS62130RGTR"
    assert repo.is_clean()


def test_delete_part_removes_everything(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    ops.delete_part("tps62130rgtr")
    lib = profile.library
    assert not (lib.parts_dir / "tps62130rgtr.json").exists()
    assert "TPS62130RGTR" not in SymbolLib.load(lib.symbol_lib_path("ICs")).symbol_names
    assert not (lib.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod").exists()
    assert not (lib.models_dir / "TPS62130RGTR.step").exists()
    assert not (lib.datasheets_dir / "tps62130rgtr.pdf").exists()
    assert repo.is_clean()
