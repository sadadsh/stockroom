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


# ------------------------------------------------- the file a reference actually names
#
# MEASURED on the owner's real library, 2026-07-27, AFTER the first clear ran: the report said
# `altium_symbol: 3, altium_footprint: 3` cleared and the commit touched `altium/` ZERO times.
# Six `.SchLib`/`.PcbLib` files were still tracked and on disk.
#
# Root cause: `_remove_altium_asset` rebuilt the filename from `record.id`, while the file is
# named for the id the part had WHEN IT WAS ATTACHED. The v3 part-id migration (`2966668`)
# renamed every record and left the Altium files alone, so a record with id
# `ina226aidgst-d958` points at `ina226aidgst.PcbLib` -- and the removal looked for
# `ina226aidgst-d958.PcbLib`, found nothing, and said nothing.
#
# The reference already CARRIES the filename (`attach_altium_assets` stores `lib=sch_dst.name`).
# Reading it is both the fix and the general rule: follow the reference, never reconstruct it.


def _altium_pair(profile, rec: PartRecord, stem: str):
    """Attach Altium libraries named for `stem`, which may differ from the record's id -- exactly
    what the v3 id migration produced across the owner's whole library."""
    from stockroom.model.asset import AssetRef

    altium = profile.library.parts_dir.parent / "altium"
    altium.mkdir(parents=True, exist_ok=True)
    sch = altium / f"{stem}.SchLib"
    pcb = altium / f"{stem}.PcbLib"
    sch.write_bytes(b"\xd0\xcf\x11\xe0fake-schlib")
    pcb.write_bytes(b"\xd0\xcf\x11\xe0fake-pcblib")
    rec.assets_for("altium").symbol = AssetRef(lib=sch.name, name="U1")
    rec.assets_for("altium").footprint = AssetRef(lib=pcb.name, name="DGS10")
    return sch, pcb


def test_an_altium_library_is_removed_by_the_name_its_REFERENCE_carries(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    # id and filename DISAGREE, which is the real state of every Altium part in the owner's
    # library after the v3 id migration.
    rec = _seed(profile, repo, "ina226aidgst-d958")
    sch, pcb = _altium_pair(profile, rec, "ina226aidgst")
    _write(profile, repo, rec, [sch, pcb])

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 2
    assert not sch.exists(), "the .SchLib the reference named is still on disk"
    assert not pcb.exists(), "the .PcbLib the reference named is still on disk"
    assert report["missing_files"] == []


def test_a_reference_whose_FILE_IS_GONE_is_reported_not_silently_counted(tmp_path, fixtures_dir):
    """The honesty half. A dangling reference is a real state, so clearing it is right -- but the
    report must not imply a file was deleted when none was there. Reporting a number that cannot
    be wrong is exactly how the Altium miss above went unnoticed."""
    from stockroom.model.asset import AssetRef

    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _seed(profile, repo, "aaa-1111")
    rec.assets_for("altium").symbol = AssetRef(lib="nowhere.SchLib", name="U1")
    _write(profile, repo, rec)

    report = ops.clear_cad_assets(dry_run=False)

    assert report["cleared"] == 1
    assert report["missing_files"] == [
        {"part_id": "aaa-1111", "asset": "altium_symbol", "expected": "altium/nowhere.SchLib"}
    ]
    assert ops.load_record("aaa-1111").assets_for("altium").symbol is None


# --------------------------------------------------------------- files nothing references
#
# "Remove all the current cad files" includes the ORPHANS. Measured on the owner's library after
# the first clear: 6 Altium libraries and 2 KiCad files sat on disk with no record pointing at
# them -- some left by the v3 id migration, some by an MPN whose spelling drifted
# (`TPD6E05U06RVZR.stp` against a record referencing `models/TPD6E05U06RVZ.step`). Clearing only
# what is REFERENCED would leave the library still holding CAD files while reporting none.
#
# What is deliberately NOT swept, because it is not a captured asset:
#   symbols/SR-*.kicad_sym   the CATEGORY LIBRARIES themselves. Entries inside them are removed
#                            one at a time; the container is library scaffolding `rebuild_part`
#                            writes into, and deleting it would break the next passive add.
#   altium/Stockroom.DbLib, stockroom-parts.db, .xlsx   the DERIVED Altium data source.
#   any .gitkeep             layout scaffolding.


def test_an_orphaned_cad_file_is_swept_too(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _write(profile, repo, _seed(profile, repo, "aaa-1111"))
    lib = profile.library
    (lib.models_dir).mkdir(parents=True, exist_ok=True)
    orphan_model = lib.models_dir / "NOBODY.step"
    orphan_model.write_bytes(b"ISO-10303-21;\n")
    pretty = lib.footprint_lib_path("ICs")
    pretty.mkdir(parents=True, exist_ok=True)
    orphan_fp = pretty / "NOBODY.kicad_mod"
    orphan_fp.write_text('(footprint "NOBODY")\n', encoding="utf-8", newline="")
    altium = lib.parts_dir.parent / "altium"
    altium.mkdir(parents=True, exist_ok=True)
    orphan_lib = altium / "nobody.PcbLib"
    orphan_lib.write_bytes(b"\xd0\xcf\x11\xe0")
    repo.commit("seed orphans", [orphan_model, orphan_fp, orphan_lib])

    report = ops.clear_cad_assets(dry_run=False)

    assert report["orphans"] == 3
    assert not orphan_model.exists()
    assert not orphan_fp.exists()
    assert not orphan_lib.exists()


def test_the_category_libraries_and_the_altium_data_source_are_NOT_swept(tmp_path, fixtures_dir):
    """NEGATIVE CONTROL. An `SR-*.kicad_sym` is the container entries live in, not an asset, and
    the Altium `.DbLib`/`.db` are derived from the records. Sweeping either would break the next
    add and the Altium handoff respectively."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    _write(profile, repo, _seed(profile, repo, "aaa-1111"))
    lib = profile.library
    sym_lib = lib.symbol_lib_path("ICs")
    altium = lib.parts_dir.parent / "altium"
    altium.mkdir(parents=True, exist_ok=True)
    dblib = altium / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    db = altium / "stockroom-parts.db"
    db.write_bytes(b"SQLite format 3\x00")
    repo.commit("seed the derived altium data source", [dblib, db])

    ops.clear_cad_assets(dry_run=False)

    assert sym_lib.exists()
    assert dblib.exists()
    assert db.exists()


def test_a_file_a_record_STILL_references_is_never_swept_as_an_orphan(tmp_path, fixtures_dir):
    """The sweep keys on what the records reference RIGHT NOW, so a file still pointed at is never
    counted as an orphan.

    Driven as a DRY RUN deliberately, because that is the state in which the distinction is real:
    nothing has been dereferenced yet, so a sweep that ignored `_referenced_files` would report
    every referenced model and footprint as an orphan. A passive would NOT exercise this -- its
    `Device:R` names no file under the profile, so there would be nothing to protect and the test
    would pass however the sweep behaved. That vacuous first version was caught by a tamper."""
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    keeper = _seed(profile, repo, "keep-1111")
    kept_fp = _own_footprint(profile, repo, keeper, "KEEP")
    kept_model = _own_model(profile, repo, keeper, "KEEP")
    _write(profile, repo, keeper, [kept_fp, kept_model])
    orphan = profile.library.models_dir / "NOBODY.step"
    orphan.write_bytes(b"x")
    repo.commit("seed an orphan", [orphan])

    report = ops.clear_cad_assets(dry_run=True)

    # Exactly ONE orphan: the two files `keep-1111` still points at are not orphans.
    assert report["orphan_files"] == ["models/NOBODY.step"]
    assert report["orphans"] == 1
    assert orphan.exists() and kept_fp.exists() and kept_model.exists()  # dry run
