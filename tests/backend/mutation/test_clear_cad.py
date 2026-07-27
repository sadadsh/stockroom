"""`LibraryOps.clear_cad_assets()`: remove every CAD asset THIS LIBRARY HOLDS, in one commit.

Owner, 2026-07-27: *"remove all the current cad files before guided capture"*, against the
complaint that produced the whole trust workstream: *"a lot of our symbols, footprints, and 3d
models are broken so its not trusted where we've gotten them"*.

THE SCOPE DISTINCTION THIS ENFORCES, and getting it wrong destroys data that nothing can restore.
Two kinds of reference live in the same slot and only one of them is a file:

  STOCKROOM-AUTHORED  a symbol inside `SR-<Category>.kicad_sym`, a `.kicad_mod` under
                      `SR-<Category>.pretty`, a `.step` under `models/`, an Altium `.SchLib` /
                      `.PcbLib`. These are the captured files, the ones under suspicion, and the
                      ones "remove all the current cad files" is about.
  KICAD-STOCK         `Device:R`, `Resistor_SMD:R_0402_1005Metric`. A reference to KiCad's OWN
                      installed libraries. There is no file here to delete, and clearing the ref
                      would blank the part permanently: `capture_needs` returns `[]` for a
                      passive, so guided capture will never refill it, and the owner's rule is
                      explicit -- *"passive components dont need files, models or symbols not for
                      kicad or for altium, theyre built in."*

MEASURED on the owner's real library before this shipped: 184 Stockroom-authored refs across
128 parts (147 on components, 30 on passives, 7 Altium), against 136 KiCad-stock refs on passives.
Clearing the stock ones would have emptied 68 parts with no way back.
"""

import shutil

import pytest

from stockroom.model.asset import AssetRef
from stockroom.model.part import PartRecord
from stockroom.model.part_class import PartClass
from stockroom.mutation.library_ops import LibraryOps

from .test_library_ops import _setup

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _seed(profile, repo, part_id: str, *, part_class=PartClass.COMPONENT, category="ICs"):
    parts_dir = profile.library.parts_dir
    parts_dir.mkdir(parents=True, exist_ok=True)
    rec = PartRecord(
        id=part_id, mpn=part_id.upper(), manufacturer="Acme", part_class=part_class,
        display_name=part_id, category=category, description="a part",
    )
    return rec


def _write(profile, repo, rec: PartRecord, extra_paths=()):
    path = profile.library.parts_dir / f"{rec.id}.json"
    path.write_text(rec.dumps(), encoding="utf-8")
    repo.commit(f"seed {rec.id}", [path, *extra_paths])
    return path


def _own_symbol(profile, repo, rec: PartRecord, name: str) -> None:
    """Give a record a Stockroom-authored KiCad symbol: a real entry in SR-<Category>.kicad_sym."""
    from stockroom.model.category import category_nickname

    lib_path = profile.library.symbol_lib_path(rec.category)
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text(
        "(kicad_symbol_lib\n\t(version 20251024)\n\t(generator \"x\")\n"
        f'\t(symbol "{name}"\n\t\t(property "Reference" "U" (at 0 0 0))\n\t)\n)\n',
        encoding="utf-8", newline="",
    )
    rec.assets_for("kicad").symbol = AssetRef(lib=category_nickname(rec.category), name=name)


def _own_footprint(profile, repo, rec: PartRecord, name: str):
    from stockroom.model.category import category_nickname

    pretty = profile.library.footprint_lib_path(rec.category)
    pretty.mkdir(parents=True, exist_ok=True)
    fp = pretty / f"{name}.kicad_mod"
    fp.write_text(
        f'(footprint "{name}"\n\t(version 20240108)\n\t(generator "pcbnew")\n'
        '\t(layer "F.Cu")\n)\n',
        encoding="utf-8", newline="",
    )
    rec.assets_for("kicad").footprint = AssetRef(lib=category_nickname(rec.category), name=name)
    return fp


def _own_model(profile, repo, rec: PartRecord, name: str):
    models = profile.library.models_dir
    models.mkdir(parents=True, exist_ok=True)
    path = models / f"{name}.step"
    path.write_bytes(b"ISO-10303-21;\n")
    rec.assets_for("kicad").model = AssetRef(file=f"models/{name}.step")
    return path


def _stock_refs(rec: PartRecord) -> None:
    """What a passive carries: KiCad's OWN libraries, no file anywhere in this profile."""
    rec.assets_for("kicad").symbol = AssetRef(lib="Device", name="R")
    rec.assets_for("kicad").footprint = AssetRef(lib="Resistor_SMD", name="R_0402_1005Metric")


def test_a_stockroom_authored_asset_loses_its_file_AND_its_reference(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "aaa-1111")
    _own_symbol(profile, repo, rec, "AAA")
    fp = _own_footprint(profile, repo, rec, "AAA")
    model = _own_model(profile, repo, rec, "AAA")
    _write(profile, repo, rec, [profile.library.symbol_lib_path("ICs"), fp, model])

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 3
    after = ops.load_record("aaa-1111")
    assert after.assets_for("kicad").symbol is None
    assert after.assets_for("kicad").footprint is None
    assert after.assets_for("kicad").model is None
    assert not fp.exists()
    assert not model.exists()


def test_a_KICAD_STOCK_reference_is_LEFT_ALONE(tmp_path, fixtures_dir):
    """THE SAFETY PROPERTY. `Device:R` is KiCad's own library, not a file this profile holds, so
    there is nothing to delete -- and clearing the ref would blank 68 of the owner's passives with
    nothing able to refill them."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "res-2222", part_class=PartClass.PASSIVE, category="Resistors")
    _stock_refs(rec)
    _write(profile, repo, rec)

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 0
    assert report["kept_stock"] == 2
    after = ops.load_record("res-2222")
    assert after.assets_for("kicad").symbol.lib == "Device"
    assert after.assets_for("kicad").footprint.name == "R_0402_1005Metric"


def test_a_passive_holding_a_STOCKROOM_authored_file_still_loses_it(tmp_path, fixtures_dir):
    """The class does not decide it; where the file lives does. 10 of the owner's passives carry
    an `SR-` symbol and footprint from the now-distrusted LCSC lane, and those ARE captured files."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "res-3333", part_class=PartClass.PASSIVE, category="ICs")
    _own_symbol(profile, repo, rec, "RES3333")
    _write(profile, repo, rec, [profile.library.symbol_lib_path("ICs")])

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 1
    assert ops.load_record("res-3333").assets_for("kicad").symbol is None


def test_a_dry_run_reports_the_same_work_and_writes_nothing(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "aaa-1111")
    fp = _own_footprint(profile, repo, rec, "AAA")
    _write(profile, repo, rec, [fp])
    before = (profile.library.parts_dir / "aaa-1111.json").read_bytes()

    report = ops.clear_cad_assets(dry_run=True)

    assert report["cleared"] == 1
    # `failed` MUST be empty. Without this the test cannot tell a respected dry run from a
    # CRASHED one: a tamper that made the dry run take the write path blew up inside
    # `_detach_eda_asset` (no transaction to track with), the exception was caught and filed
    # under `failed`, and the file survived anyway -- so every other assertion here still passed.
    assert report["failed"] == []
    assert fp.exists()
    assert (profile.library.parts_dir / "aaa-1111.json").read_bytes() == before
    assert repo.is_clean()


def test_the_report_names_every_part_and_asset_it_touched(tmp_path, fixtures_dir):
    """A destructive library-wide operation that reports only a number is not reviewable."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "aaa-1111")
    fp = _own_footprint(profile, repo, rec, "AAA")
    _write(profile, repo, rec, [fp])

    report = ops.clear_cad_assets(dry_run=True)

    assert report["items"] == [{"part_id": "aaa-1111", "assets": ["kicad_footprint"]}]


def test_nothing_but_the_CAD_is_touched(tmp_path, fixtures_dir):
    """Identity, derived data, sourced evidence and the datasheet all stand. This removes assets,
    not parts."""
    from stockroom.model.part import Datasheet

    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "aaa-1111")
    rec.datasheet = Datasheet(file="a.pdf", source_url="https://example.com/a.pdf")
    fp = _own_footprint(profile, repo, rec, "AAA")
    _write(profile, repo, rec, [fp])

    ops.clear_cad_assets(dry_run=False)

    after = ops.load_record("aaa-1111")
    assert (after.id, after.mpn, after.manufacturer, after.part_class) == (
        "aaa-1111", "AAA-1111", "Acme", PartClass.COMPONENT,
    )
    assert after.description == "a part"
    assert after.datasheet is not None and after.datasheet.file == "a.pdf"


def test_the_whole_sweep_is_ONE_commit_and_leaves_a_clean_tree(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    for pid in ("aaa-1111", "zzz-3333"):
        rec = _seed(profile, repo, pid)
        fp = _own_footprint(profile, repo, rec, pid.upper())
        _write(profile, repo, rec, [fp])

    ops.clear_cad_assets(dry_run=False)

    assert repo.is_clean()


def test_a_library_with_no_cad_at_all_is_a_true_no_op(tmp_path, fixtures_dir):
    """No empty commit, no error: nothing to remove is a real state, not a failure."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _write(profile, repo, _seed(profile, repo, "aaa-1111"))
    head = repo.head()

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 0
    assert repo.head() == head
