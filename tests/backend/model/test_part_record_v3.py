"""The v3 foundation and its v4 active-CAD-selection extension.

The shape is drawn in `docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 9
and is not re-litigated here. What IS tested here is that the shape holds:

  - identity (`id`, `mpn`, `manufacturer`, `part_class`) is never rewritten by a re-derive;
  - `derived` is disposable by construction - drop it, put it back, get the same record;
  - `sources` is an INDEX, never the payloads (those live in `sourced/`, per decision D1);
  - every asset carries `origin` and `checks`, and no verdict is ever stored (decision D2);
  - a v1/v2 record is MIGRATED, not relabelled. That bug is the reason this file exists:
    `from_dict` did `max(SCHEMA_VERSION, ...)`, which stamped a v1 record as current while
    leaving its data at v1, so a stale record silently claimed to be understood.
"""

import json

import pytest

from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.derived import DERIVED_BY, DERIVED_FIELDS, Derived
from stockroom.model.part import (
    SCHEMA_VERSION,
    PartRecord,
    UnmigratableRecord,
    migrate_record,
)
from stockroom.model.part_class import PartClass, RequirementOverride
from stockroom.model.sourced import SourceEntry


def _rec(**kw) -> PartRecord:
    return PartRecord(id="tps62130rgtr-8c1d", display_name="n", category="ICs", **kw)


# ------------------------------------------------- the persisted shape


def test_the_schema_version_is_four():
    assert SCHEMA_VERSION == 4
    assert json.loads(_rec().dumps())["schema_version"] == 4


def test_the_top_level_keys_are_identity_derived_sources_and_assets():
    blob = json.loads(_rec().dumps())
    assert {"id", "mpn", "manufacturer", "part_class", "derived", "sources", "assets"} <= set(blob)
    # The derived fields are no longer flat: that boundary is the whole point of the schema.
    for moved in ("display_name", "category", "description", "value", "specs"):
        assert moved not in blob, f"{moved} belongs in the derived block"
    assert "passive" not in blob, "the two-valued part class is replaced by part_class"
    assert "eda" not in blob, "the asset map is `assets` at v3"


def test_the_derived_block_holds_exactly_the_derived_fields():
    blob = json.loads(_rec(description="d", value="v", specs={"Package": "QFN-16"}).dumps())
    assert set(blob["derived"]) == set(DERIVED_FIELDS)
    assert blob["derived"]["display_name"] == "n"
    assert blob["derived"]["category"] == "ICs"
    assert blob["derived"]["description"] == "d"
    assert blob["derived"]["value"] == "v"
    assert blob["derived"]["specs"] == {"Package": "QFN-16"}


def test_the_python_attributes_and_the_derived_block_cannot_drift():
    # A field added to Derived and forgotten on the record (or the reverse) is exactly the
    # schema drift the owner asked to be gated rather than remembered.
    rec = _rec()
    assert set(DERIVED_FIELDS) == set(Derived().to_dict())
    for name in DERIVED_FIELDS:
        assert hasattr(rec, name), f"PartRecord is missing the derived field {name}"


def test_a_default_record_carries_the_ruleset_that_derived_it():
    rec = _rec()
    rec.stamp_derived(at="2026-07-27T21:04:00Z")
    assert rec.derived_by == DERIVED_BY
    assert rec.derived_at == "2026-07-27T21:04:00Z"
    assert json.loads(rec.dumps())["derived"]["derived_by"] == DERIVED_BY


# ------------------------------------------------- derived is disposable


def test_the_derived_block_can_be_swapped_wholesale():
    rec = _rec()
    rec.derived = Derived(display_name="Buck Converter 3A 17V QFN-16", category="ICs", value="")
    assert rec.display_name == "Buck Converter 3A 17V QFN-16"
    assert json.loads(rec.dumps())["derived"]["display_name"] == "Buck Converter 3A 17V QFN-16"


def test_dropping_the_derived_block_and_putting_it_back_reproduces_the_record():
    # "Deleting the whole block and recomputing must reproduce it byte-for-byte."
    rec = _rec(description="d", value="v", specs={"Package": "QFN-16"}, mpn="TPS62130RGTR")
    before = rec.dumps()
    keep = rec.derived
    rec.clear_derived()
    assert rec.display_name == "" and rec.specs == {}
    rec.derived = keep
    assert rec.dumps() == before


def test_a_re_derive_never_touches_identity():
    rec = _rec(mpn="TPS62130RGTR", manufacturer="Texas Instruments", part_class=PartClass.MECHANICAL)
    rec.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    rec.clear_derived()
    assert rec.id == "tps62130rgtr-8c1d"
    assert rec.mpn == "TPS62130RGTR"
    assert rec.manufacturer == "Texas Instruments"
    assert rec.part_class is PartClass.MECHANICAL
    assert rec.assets_for("kicad").symbol.ref.name == "A"


# ------------------------------------------------- part class


def test_the_part_class_defaults_to_component_and_round_trips():
    assert _rec().part_class is PartClass.COMPONENT
    for cls in PartClass:
        back = PartRecord.loads(_rec(part_class=cls).dumps())
        assert back.part_class is cls
    assert json.loads(_rec(part_class=PartClass.PASSIVE).dumps())["part_class"] == "passive"


def test_passive_reads_off_the_part_class():
    assert _rec(part_class=PartClass.PASSIVE).passive is True
    assert _rec(part_class=PartClass.MECHANICAL).passive is False


def test_the_requires_override_defaults_to_null_and_round_trips():
    assert json.loads(_rec().dumps())["requires_override"] is None
    ov = RequirementOverride(needs=("footprint",), reason="ring LED integral to the button")
    assert PartRecord.loads(_rec(requires_override=ov).dumps()).requires_override == ov


# ------------------------------------------------- the sources index


def test_sources_is_an_INDEX_and_never_the_payload():
    rec = _rec()
    rec.record_source("mouser", file="sourced/tps62130rgtr-8c1d/mouser.json", fetched_at="t")
    blob = json.loads(rec.dumps())
    assert blob["sources"] == {
        "mouser": {"fetched_at": "t", "file": "sourced/tps62130rgtr-8c1d/mouser.json"}
    }
    back = PartRecord.loads(rec.dumps())
    assert back.sources["mouser"] == SourceEntry(
        fetched_at="t", file="sourced/tps62130rgtr-8c1d/mouser.json"
    )


def test_the_source_file_path_is_derived_from_the_part_id_when_not_given():
    rec = _rec()
    rec.record_source("digikey", fetched_at="t")
    assert rec.sources["digikey"].file == "sourced/tps62130rgtr-8c1d/digikey.json"


# ------------------------------------------------- assets: ref + origin + checks


def test_an_asset_carries_its_ref_its_origin_and_its_checks():
    rec = _rec()
    rec.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-ICs", name="TPS62130RGTR"),
        origin=AssetOrigin(
            vendor="ultralibrarian", url="https://x", captured_at="2026-07-27T21:04:00Z"
        ),
    )
    blob = json.loads(rec.dumps())["assets"]["kicad"]["symbol"]
    assert blob["ref"] == {"lib": "SR-ICs", "name": "TPS62130RGTR", "file": ""}
    assert blob["origin"] == {
        "vendor": "ultralibrarian",
        "url": "https://x",
        "captured_at": "2026-07-27T21:04:00Z",
    }
    # An empty `checks` list is OMITTED, like every other empty block on this record: a
    # library adopting the schema must not have every part rewritten to carry `[]`.
    assert "checks" not in blob


def test_a_bare_reference_becomes_an_asset_with_no_provenance_yet():
    # Attaching a reference is allowed before anyone knows where it came from; what is not
    # allowed is pretending an unattributed asset has an origin.
    rec = _rec()
    rec.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    sym = rec.assets_for("kicad").symbol
    assert isinstance(sym, Asset)
    assert sym.origin is None and sym.checks == []
    assert PartRecord.loads(rec.dumps()).assets_for("kicad").symbol.ref.name == "A"


def test_every_registered_tool_gets_a_live_bundle():
    rec = _rec()
    rec.assets_for("altium").footprint = AssetRef(lib="a.PcbLib", name="A")
    assert rec.assets["altium"].footprint.ref.lib == "a.PcbLib"
    assert "kicad" in rec.assets and "altium" in rec.assets


def test_empty_bundles_are_omitted_so_a_one_field_edit_stays_a_one_line_diff():
    assert json.loads(_rec().dumps())["assets"] == {}


# ------------------------------------------------- MIGRATION, not relabelling


V1 = {
    "id": "x-0000",
    "display_name": "n",
    "category": "ICs",
    "mpn": "TPS62130RGTR",
    "passive": True,
    "symbol": {"lib": "SR-ICs", "name": "A"},
    "altium_symbol": {"lib": "a.SchLib", "name": "A"},
    "specs": {"Package": "QFN-16"},
}

V2 = {
    "schema_version": 2,
    "id": "x-0000",
    "display_name": "n",
    "category": "ICs",
    "description": "d",
    "value": "v",
    "mpn": "TPS62130RGTR",
    "manufacturer": "TI",
    "passive": False,
    "specs": {"Package": "QFN-16"},
    "eda": {"kicad": {"symbol": {"lib": "SR-ICs", "name": "A"}, "footprint": None, "model": None}},
}


def test_a_v1_record_is_MIGRATED_not_merely_restamped():
    rec = PartRecord.from_dict(dict(V1))
    assert rec.schema_version == SCHEMA_VERSION
    # The relabel bug: the stamp moved and the DATA did not. Every one of these is data.
    assert rec.display_name == "n" and rec.category == "ICs"
    assert rec.specs == {"Package": "QFN-16"}
    assert rec.part_class is PartClass.PASSIVE
    assert rec.assets_for("kicad").symbol.ref.name == "A"
    assert rec.assets_for("altium").symbol.ref.lib == "a.SchLib"
    blob = json.loads(rec.dumps())
    assert blob["derived"]["display_name"] == "n"
    assert "passive" not in blob and "symbol" not in blob and "eda" not in blob


def test_a_v2_record_is_migrated_field_by_field():
    rec = PartRecord.from_dict(dict(V2))
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.description == "d" and rec.value == "v"
    assert rec.manufacturer == "TI"
    assert rec.part_class is PartClass.COMPONENT
    assert rec.assets_for("kicad").symbol.ref == AssetRef(lib="SR-ICs", name="A")
    assert rec.assets_for("kicad").symbol.origin is None, "a legacy asset has no known origin"


def test_migration_is_a_pure_function_that_leaves_the_input_alone():
    src = dict(V2)
    migrate_record(src)
    assert src == V2, "migrating must not mutate the caller's dict"


def test_a_version_we_cannot_upgrade_is_REFUSED_rather_than_restamped():
    # The exact failure the old `max(SCHEMA_VERSION, ...)` produced: a record whose data we
    # cannot upgrade must never be handed on wearing the current version.
    with pytest.raises(UnmigratableRecord):
        migrate_record({"id": "x-0000", "schema_version": 0})


def test_a_FUTURE_record_keeps_its_own_version_and_is_flagged():
    future = {
        "schema_version": SCHEMA_VERSION + 7,
        "id": "x-0000",
        "mpn": "M",
        "derived": {"display_name": "n", "category": "ICs"},
        "lifecycle": {"status": "active"},
    }
    rec = PartRecord.from_dict(dict(future))
    assert rec.schema_version == SCHEMA_VERSION + 7
    assert rec.is_future_schema() is True
    out = json.loads(rec.dumps())
    assert out["schema_version"] == SCHEMA_VERSION + 7
    assert out["lifecycle"] == {"status": "active"}, "an unknown field must survive an edit"


def test_a_record_written_by_this_build_round_trips_unchanged():
    rec = _rec(
        mpn="TPS62130RGTR",
        manufacturer="Texas Instruments",
        description="d",
        value="v",
        specs={"Package": "QFN-16"},
        part_class=PartClass.COMPONENT,
    )
    rec.record_source("mouser", fetched_at="t")
    rec.assets_for("kicad").symbol = Asset(
        ref=AssetRef(lib="SR-ICs", name="A"),
        origin=AssetOrigin(vendor="samacsys", url="u", captured_at="t"),
    )
    assert PartRecord.loads(rec.dumps()).dumps() == rec.dumps()
