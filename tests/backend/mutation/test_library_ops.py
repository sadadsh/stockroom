import shutil

import pytest

from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.kicad.footprint import Footprint
from stockroom.model.part import Datasheet, PartRecord, Purchase
from stockroom.mutation.library_ops import (
    IncompleteError,
    LibraryOps,
    StagedPart,
    staged_missing_fields,
)
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
    # commit the seeded category lib so the fixture leaves a CLEAN repo (a real profile's
    # category libs are committed at wiring time); this makes repo.is_clean() a valid
    # zero-trace invariant for the gate-rejection tests below.
    repo.commit("seed ICs category lib", [profile.library.symbol_lib_path("ICs")])
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
        purchase=[Purchase(vendor="Mouser", url="https://www.mouser.com/ProductDetail/595-TPS62130RGTR")],
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


def test_add_part_rejects_incomplete_and_leaves_zero_trace(tmp_path, fixtures_dir):
    """The complete-to-add gate: a part missing a REQUIRED field (identity/datasheet/
    purchase) is refused BEFORE any file write, so the reject leaves zero trace (spec
    section 6). Assets (symbol/footprint/3D) no longer gate (owner 2026-07-16)."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.model_source = None       # no longer gates
    staged.datasheet_source = None   # still gates (no datasheet URL either)
    ops = LibraryOps(profile, repo)
    before = repo.head()
    with pytest.raises(IncompleteError) as ei:
        ops.add_part(staged)
    assert "datasheet" in ei.value.missing
    assert "3D model" not in ei.value.missing  # assets are attached after entry now
    # zero trace: no commit, clean tree, nothing written
    assert repo.head() == before
    assert repo.is_clean()
    assert not list(profile.library.parts_dir.glob("*.json"))


def test_add_part_partial_allowed_when_gate_bypassed(tmp_path, fixtures_dir):
    """The archive-import path (require_complete=False) grandfathers a part with no
    model or datasheet; placement still succeeds."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.model_source = None
    staged.datasheet_source = None
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged, require_complete=False)
    assert record.model is None
    fp = Footprint.load(profile.library.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod")
    assert fp.model_path is None  # no (model ...) block written


@pytest.mark.parametrize(
    "field_attr,label",
    [
        ("display_name", "name"),
        ("mpn", "MPN"),
        ("manufacturer", "manufacturer"),
        ("description", "value/description"),
    ],
)
def test_add_part_rejects_each_missing_identity_field(tmp_path, fixtures_dir, field_attr, label):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    setattr(staged, field_attr, "")
    ops = LibraryOps(profile, repo)
    with pytest.raises(IncompleteError) as ei:
        ops.add_part(staged)
    assert label in ei.value.missing
    assert repo.is_clean()


def test_add_part_rejects_missing_purchase_link(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.purchase = []
    ops = LibraryOps(profile, repo)
    with pytest.raises(IncompleteError) as ei:
        ops.add_part(staged)
    assert "purchase link" in ei.value.missing


def test_datasheet_url_alone_satisfies_the_gate_and_lands_on_the_record(tmp_path, fixtures_dir):
    """A pulled datasheet LINK (no downloaded PDF) satisfies the datasheet passport
    field, the same way PartRecord.is_complete accepts a URL. So a non-passive part
    whose vendor ZIP carried no datasheet but whose product page gave a link is
    addable, and the link lands on the committed record."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.datasheet_source = None
    staged.datasheet_meta = Datasheet(source_url="https://www.analog.com/MAX4995B/datasheet")
    # the gate no longer reports datasheet missing when only the URL is known
    assert "datasheet" not in staged_missing_fields(staged)
    record = LibraryOps(profile, repo).add_part(staged)
    assert record.datasheet is not None
    assert record.datasheet.source_url == "https://www.analog.com/MAX4995B/datasheet"
    assert record.datasheet.file == ""  # no PDF was downloaded, just the link
    assert record.is_complete


def test_staged_missing_fields_lists_all_gaps_in_passport_order(tmp_path, fixtures_dir):
    _, _, staged = _setup(tmp_path, fixtures_dir)
    staged.mpn = ""
    staged.model_source = None  # assets no longer gate (owner 2026-07-16)
    staged.purchase = []
    assert staged_missing_fields(staged) == ["MPN", "purchase link"]


def _refless_record() -> PartRecord:
    # a complete-by-the-new-gate record with NO KiCad assets: identity + datasheet URL +
    # purchase link, no symbol/footprint/model. This is the whole-BOM import shape.
    return PartRecord(
        id="",
        display_name="STM32H753ZIT6",
        category="ICs",
        description="MCU, Cortex-M7, LQFP144",
        mpn="STM32H753ZIT6",
        manufacturer="STMicroelectronics",
        datasheet=Datasheet(source_url="https://mouser.com/x.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://www.mouser.com/ProductDetail/511-STM32H753ZIT6")],
    )


def test_add_reference_part_lands_asset_less_record_json_only(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    before = repo.head()
    rec = ops.add_reference_part(_refless_record())
    assert rec.id == "stm32h753zit6"
    jp = profile.library.parts_dir / "stm32h753zit6.json"
    assert jp.exists()
    saved = PartRecord.loads(jp.read_text(encoding="utf-8"))
    assert saved.symbol is None and saved.footprint is None and saved.model is None
    assert saved.is_complete()  # complete without assets under the new gate
    assert saved.missing_assets() == ["symbol", "footprint", "3D model"]
    # no symbol lib / .pretty file was created (reference-only, no assets)
    assert repo.head() != before and repo.is_clean()


def test_add_reference_part_still_gates_on_purchase(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    rec = _refless_record()
    rec.purchase = []
    with pytest.raises(IncompleteError) as ei:
        ops.add_reference_part(rec)
    assert "purchase link" in ei.value.missing
    assert repo.is_clean()


def test_edit_datasheet_coerces_a_url_string_into_a_datasheet_ref(tmp_path, fixtures_dir):
    # the Complete-Part window edits the datasheet as a bare URL; edit_field must wrap it in a
    # Datasheet so the record stays well-formed, and a blank clears it.
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_reference_part(_refless_record())
    edited = ops.edit_field("stm32h753zit6", "datasheet", "https://example.com/ds.pdf")
    assert edited.datasheet is not None
    assert edited.datasheet.source_url == "https://example.com/ds.pdf"
    # round-trips through disk as a real Datasheet, not a bare string
    saved = PartRecord.loads(
        (profile.library.parts_dir / "stm32h753zit6.json").read_text(encoding="utf-8")
    )
    assert saved.datasheet.source_url == "https://example.com/ds.pdf"
    assert ops.edit_field("stm32h753zit6", "datasheet", "  ").datasheet is None


def test_attach_symbol_and_footprint_tag_the_tool_and_commit(tmp_path, fixtures_dir):
    repo, profile, _ = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_reference_part(_refless_record())
    rec = ops.attach_symbol("stm32h753zit6", "SR-ICs", "STM32H753ZIT6")
    assert rec.symbol.lib == "SR-ICs" and rec.symbol.name == "STM32H753ZIT6"
    assert rec.symbol.tool == "kicad"  # default EDA tool tag, ready for altium later
    rec = ops.attach_footprint("stm32h753zit6", "SR-ICs", "LQFP-144", tool="kicad")
    assert rec.footprint.name == "LQFP-144" and rec.footprint.tool == "kicad"
    # persisted + still just the JSON touched, tree clean after each atomic commit
    saved = PartRecord.loads((profile.library.parts_dir / "stm32h753zit6.json").read_text())
    assert saved.symbol.tool == "kicad" and saved.footprint.tool == "kicad"
    assert saved.missing_assets() == ["3D model"]
    assert repo.is_clean()


def test_archive_profile_grandfathers_incomplete_parts(tmp_path, fixtures_dir):
    """An archive profile (spec section 7) bypasses the gate automatically, so a very
    incomplete legacy part imports fine even at the default require_complete=True, while
    the same part is refused by a primary profile."""
    from stockroom.store.profile import ProfileStore

    repo, primary, staged = _setup(tmp_path, fixtures_dir)  # primary "Main"
    staged.model_source = None
    staged.datasheet_source = None
    staged.purchase = []  # deeply incomplete legacy part

    # a primary profile refuses it
    with pytest.raises(IncompleteError):
        LibraryOps(primary, repo).add_part(staged)

    # an archive profile grandfathers it
    store = ProfileStore(repo.root / "libraries", repo)
    archive = store.create("Archive", archive=True)
    assert archive.is_archive
    archive.library.symbols_dir.mkdir(parents=True, exist_ok=True)
    (archive.library.symbol_lib_path("ICs")).write_text(
        '(kicad_symbol_lib\r\n\t(version 20251024)\r\n\t(generator "x")\r\n)\r\n', newline=""
    )
    archive.library.footprint_lib_path("ICs").mkdir(parents=True, exist_ok=True)
    record = LibraryOps(archive, repo).add_part(staged)
    assert record.id == "tps62130rgtr"
    assert not record.is_complete()  # grandfathered, intentionally incomplete
    assert repo.is_clean()


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


def test_set_specs_persists_value_and_provenance(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    before = repo.head()
    pins = [{"pin": "1", "name": "VIN"}, {"pin": "2", "name": "GND"}]
    rec = ops.set_specs(
        "tps62130rgtr",
        {"pinout": {"value": pins, "source": "datasheet", "confidence": "high"}},
    )
    # the value lands in record.specs; its provenance lands in record.enrichment
    assert rec.specs["pinout"] == pins
    assert rec.enrichment["pinout"].source == "datasheet"
    assert rec.enrichment["pinout"].confidence == "high"
    # persisted to disk (reload proves it) and committed atomically
    assert ops.load_record("tps62130rgtr").specs["pinout"] == pins
    assert repo.head() != before
    assert repo.is_clean()


def test_set_specs_does_not_clobber_without_overwrite(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    first = [{"pin": "1", "name": "VIN"}]
    ops.set_specs("tps62130rgtr", {"pinout": {"value": first, "source": "datasheet"}})
    second = [{"pin": "1", "name": "WRONG"}]
    # merge (default): an existing key is kept, never silently overwritten
    rec = ops.set_specs("tps62130rgtr", {"pinout": {"value": second, "source": "scrape"}})
    assert rec.specs["pinout"] == first
    # overwrite=True replaces it
    rec = ops.set_specs(
        "tps62130rgtr", {"pinout": {"value": second, "source": "scrape"}}, overwrite=True
    )
    assert rec.specs["pinout"] == second


def test_set_specs_normalizes_a_duplicated_label_key_onto_the_clean_key(tmp_path, fixtures_dir):
    # F2 review regression: after the migration a record holds the CLEAN key, but the
    # Mouser scraper can still emit the raw duplicated-label twin. set_specs must key its
    # guard/no-op/merge off the NORMALIZED form so it updates the clean key - not add a
    # twin the persistence layer then silently collapses (dropping a value) and not leave
    # an orphan enrichment key.
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    ops.set_specs("tps62130rgtr", {"Factory Pack Quantity": {"value": "100", "source": "mouser_web"}})
    twin = "Factory Pack Quantity: Factory Pack Quantity"
    # overwrite=True with the raw twin + a different value updates the CLEAN key
    rec = ops.set_specs("tps62130rgtr", {twin: {"value": "999", "source": "mouser_web"}}, overwrite=True)
    assert rec.specs["Factory Pack Quantity"] == "999"  # updated, not silently dropped
    assert twin not in rec.specs  # no twin
    assert twin not in rec.enrichment  # no orphan provenance
    assert rec.enrichment["Factory Pack Quantity"].source == "mouser_web"
    # overwrite=False keeps the existing clean value and still never adds a twin
    rec2 = ops.set_specs("tps62130rgtr", {twin: {"value": "777", "source": "x"}})
    assert rec2.specs["Factory Pack Quantity"] == "999"
    assert twin not in rec2.specs
    # persisted
    reloaded = ops.load_record("tps62130rgtr")
    assert reloaded.specs["Factory Pack Quantity"] == "999"
    assert twin not in reloaded.specs


def test_set_specs_noop_writes_no_commit(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    pins = [{"pin": "1", "name": "VIN"}]
    ops.set_specs("tps62130rgtr", {"pinout": {"value": pins, "source": "datasheet"}})
    head_after_first = repo.head()
    # re-applying the same specs without overwrite changes nothing -> no empty commit
    ops.set_specs("tps62130rgtr", {"pinout": {"value": pins, "source": "datasheet"}})
    assert repo.head() == head_after_first
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


def test_detect_drift_clean_after_add(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    report = ops.detect_drift()
    assert report.items == []
    assert report.missing_symbol == []


def test_detect_drift_finds_behind_the_back_edit(tmp_path, fixtures_dir):
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    # scribble the symbol property directly, as if KiCad edited it
    sym_lib_path = profile.library.symbol_lib_path("ICs")
    lib = SymbolLib.load(sym_lib_path)
    lib.get_symbol("TPS62130RGTR").set_property("Manufacturer", "WRONG")
    lib.save(sym_lib_path)

    report = ops.detect_drift()
    assert len(report.items) == 1
    item = report.items[0]
    assert item.part_id == "tps62130rgtr"
    assert item.property == "Manufacturer"
    assert item.json_value == "TI"
    assert item.symbol_value == "WRONG"


def test_refresh_procurement_writes_atomically_and_no_ops_when_unchanged(tmp_path, fixtures_dir):
    from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced

    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)  # creates part "tps62130rgtr" with a Mouser purchase

    def result(stock):
        r = EnrichmentResult()
        r.stock = Sourced(stock, "mouser", "high")
        r.price_breaks = [PriceBreak(1, 0.5)]
        return r

    before = repo.head()
    rec = ops.refresh_procurement(
        "tps62130rgtr", [("Mouser", result(99))], "2026-07-18T00:00:00+00:00")
    assert any(p.vendor == "Mouser" and p.stock == 99 for p in rec.purchase)
    assert repo.head() != before                                              # a commit happened
    assert any(p.stock == 99 for p in ops.load_record("tps62130rgtr").purchase)  # persisted

    head = repo.head()
    # identical data but a LATER timestamp - as the live endpoint always passes (a fresh
    # microsecond now_iso every call). fetched_at means "when the data last CHANGED", so an
    # advancing clock alone must NOT manufacture a commit.
    ops.refresh_procurement(
        "tps62130rgtr", [("Mouser", result(99))], "2026-07-18T09:59:59+00:00")
    assert repo.head() == head                                                # no empty commit


def test_rebuild_part_renames_to_the_spec_aware_name_atomically(tmp_path, fixtures_dir):
    """A full rebuild re-derives the spec-aware display name and commits it atomically; a second
    identical rebuild is a true no-op (no empty commit), mirroring refresh_procurement/set_specs."""
    from datetime import datetime, timezone

    from stockroom.ingest.component_naming import propose_component_name_from_record

    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    ops = LibraryOps(profile, repo)
    ops.add_part(staged)
    rec0 = ops.load_record("tps62130rgtr")
    expected = propose_component_name_from_record(rec0)
    before = repo.head()
    rec = ops.rebuild_part("tps62130rgtr", [], datetime.now(timezone.utc).isoformat())
    assert rec.display_name == expected
    if expected != rec0.display_name:
        assert repo.head() != before  # renamed -> one atomic commit
        assert ops.load_record("tps62130rgtr").display_name == expected
    mid = repo.head()
    ops.rebuild_part("tps62130rgtr", [], datetime.now(timezone.utc).isoformat())
    assert repo.head() == mid  # no-op second pass


def test_add_part_lands_file_less_on_identity_alone(tmp_path, fixtures_dir):
    """The primary add flow (owner 2026-07-24): a part pulled from a purchase link lands
    with NO symbol/footprint/3D at all - the guided capture attaches both EDA formats
    right after. The record carries None asset refs (never a dangling LibRef) and no
    category asset files appear."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.symbol_source = None
    staged.symbol_source_name = ""
    staged.footprint_source = None
    staged.model_source = None
    staged.entry_name = ""
    ops = LibraryOps(profile, repo)
    record = ops.add_part(staged)

    assert record.symbol is None
    assert record.footprint is None
    assert record.model is None
    # identity + sourcing landed intact
    assert record.mpn == "TPS62130RGTR"
    assert record.purchase and record.purchase[0].vendor == "Mouser"
    # no asset files were fabricated
    lib = profile.library
    sym_lib = SymbolLib.load(lib.symbol_lib_path("ICs"))
    assert "TPS62130RGTR" not in sym_lib.symbol_names
    assert not (lib.footprint_lib_path("ICs") / "TPS62130RGTR.kicad_mod").exists()
    # one clean commit
    assert repo.is_clean()
    # the JSON round-trips with null assets
    again = PartRecord.loads((lib.parts_dir / f"{record.id}.json").read_text(encoding="utf-8"))
    assert again.symbol is None and again.footprint is None


def test_add_part_with_symbol_but_no_entry_name_fails_loud(tmp_path, fixtures_dir):
    """A symbol source with no entry name would merge a symbol named "" into the
    category lib - refuse honestly instead."""
    repo, profile, staged = _setup(tmp_path, fixtures_dir)
    staged.entry_name = ""
    ops = LibraryOps(profile, repo)
    with pytest.raises(ValueError):
        ops.add_part(staged)
    assert repo.is_clean()
