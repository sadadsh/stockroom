"""The per-EDA record: one EdaAssets bundle per tool, keyed by the tool registry.

Replaces the old asymmetry (implicitly-KiCad flat `symbol`/`footprint`/`model` plus
bolted-on `altium_symbol`/`altium_footprint` and no Altium model slot). That asymmetry
is what produced the permanent "CAD Incomplete" bug and the attach-clobber bug, so these
tests lock the shape, not just the round trip.
"""
import json

import pytest

from stockroom.model.part import (
    AssetRef,
    EdaAssets,
    PartRecord,
    asset_present,
    tool_assets_ready,
    tool_place_ready,
)


def _rec(**kw) -> PartRecord:
    return PartRecord(id="x", display_name="n", category="ICs", **kw)


# ---------------------------------------------------------------- shape


def test_a_fresh_record_carries_an_empty_bundle_for_every_registered_tool():
    assert _rec().eda == {"kicad": EdaAssets(), "altium": EdaAssets()}


def test_assets_for_returns_the_LIVE_bundle_so_mutating_it_mutates_the_record():
    # If this returned a fresh throwaway on a miss, `rec.assets_for(t).symbol = x` would
    # silently do nothing -- the exact quiet-failure class this cutover exists to kill.
    r = _rec()
    r.assets_for("altium").symbol = AssetRef(lib="BQ24074RGTT.SchLib", name="BQ24074RGTT")
    assert r.eda["altium"].symbol.name == "BQ24074RGTT"
    assert r.assets_for("altium") is r.eda["altium"]


def test_an_unknown_tool_raises_instead_of_silently_defaulting_to_kicad():
    # A silent fallback to KiCad is exactly what let an Altium attach clobber the KiCad
    # reference (f7d80ac). Unknown tools must be loud.
    with pytest.raises(KeyError):
        _rec().assets_for("eagle")


# ---------------------------------------------------------------- independence


def test_the_two_tools_hold_independent_assets():
    r = _rec()
    r.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="TPS62130RGTR")
    r.assets_for("altium").symbol = AssetRef(lib="TPS62130.SchLib", name="TPS62130RGTR")
    assert r.eda["kicad"].symbol.lib == "SR-ICs"
    assert r.eda["altium"].symbol.lib == "TPS62130.SchLib"


def test_every_tool_has_its_own_model_slot():
    # The old record had ONE model field and no Altium model slot at all, so there was
    # nowhere honest to record an Altium 3D body.
    r = _rec()
    r.assets_for("altium").model = AssetRef(file="models/TPS62130RGTR.step")
    assert r.assets_for("altium").model.file == "models/TPS62130RGTR.step"
    assert r.assets_for("kicad").model is None


# ---------------------------------------------------------------- serialization


def test_round_trip_preserves_every_tool_bundle():
    r = _rec()
    r.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    r.assets_for("kicad").footprint = AssetRef(lib="SR-ICs", name="VQFN-16")
    r.assets_for("kicad").model = AssetRef(file="models/a.step")
    r.assets_for("altium").symbol = AssetRef(lib="a.SchLib", name="A")
    r.assets_for("altium").footprint = AssetRef(lib="a.PcbLib", name="VQFN-16")
    assert PartRecord.loads(r.dumps()).eda == r.eda


def test_the_flat_legacy_fields_are_gone_from_the_wire_format():
    r = _rec()
    r.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    d = json.loads(r.dumps())
    for gone in ("symbol", "footprint", "model", "altium_symbol", "altium_footprint"):
        assert gone not in d, f"{gone} must not survive the cutover"
    assert d["eda"]["kicad"]["symbol"] == {"lib": "SR-ICs", "name": "A", "file": ""}


def test_an_empty_tool_bundle_is_not_persisted():
    # Keeps the JSON minimal so a one-field edit stays a one-line diff.
    assert json.loads(_rec().dumps())["eda"] == {}


def test_a_tool_this_build_does_not_know_survives_a_round_trip():
    # A peer on a newer Stockroom may write an entry for a tool we have never heard of.
    # Dropping it would silently destroy their work on our next write.
    d = json.loads(_rec().dumps())
    d["eda"]["eagle"] = {"symbol": {"lib": "e.lbr", "name": "A", "file": ""},
                         "footprint": None, "model": None}
    assert json.loads(PartRecord.from_dict(d).dumps())["eda"]["eagle"]["symbol"]["lib"] == "e.lbr"


# ------------------------------------------------- legacy read compatibility


LEGACY = {
    "id": "x",
    "display_name": "n",
    "category": "ICs",
    "symbol": {"lib": "SR-ICs", "name": "TPS62130RGTR", "tool": "kicad"},
    "footprint": {"lib": "SR-ICs", "name": "VQFN-16", "tool": "kicad"},
    "model": {"file": "models/TPS62130RGTR.step", "tool": "kicad"},
    "altium_symbol": {"lib": "a.SchLib", "name": "TPS62130RGTR", "tool": "altium"},
    "altium_footprint": {"lib": "a.PcbLib", "name": "VQFN-16", "tool": "altium"},
}


def test_a_legacy_record_folds_its_flat_fields_into_the_per_tool_map():
    r = PartRecord.from_dict(dict(LEGACY))
    assert r.assets_for("kicad").symbol == AssetRef(lib="SR-ICs", name="TPS62130RGTR")
    assert r.assets_for("kicad").model == AssetRef(file="models/TPS62130RGTR.step")
    assert r.assets_for("altium").footprint == AssetRef(lib="a.PcbLib", name="VQFN-16")


def test_a_legacy_ref_tagged_for_another_tool_folds_under_that_tool():
    # The old LibRef carried a `tool` discriminator; honour it rather than assuming KiCad.
    d = dict(LEGACY)
    d["symbol"] = {"lib": "a.SchLib", "name": "A", "tool": "altium"}
    d.pop("altium_symbol")
    r = PartRecord.from_dict(d)
    assert r.assets_for("kicad").symbol is None
    assert r.assets_for("altium").symbol == AssetRef(lib="a.SchLib", name="A")


def test_a_legacy_record_rewrites_in_the_new_format():
    d = json.loads(PartRecord.from_dict(dict(LEGACY)).dumps())
    assert "altium_symbol" not in d
    assert set(d["eda"]) == {"kicad", "altium"}


def test_the_new_format_wins_when_both_are_present():
    d = dict(LEGACY)
    d["eda"] = {"kicad": {"symbol": {"lib": "NEW", "name": "N", "file": ""}}}
    assert PartRecord.from_dict(d).assets_for("kicad").symbol.lib == "NEW"


# ---------------------------------------------------------------- presence


def test_asset_present_reads_the_field_that_kind_actually_uses():
    assert asset_present(AssetRef(lib="SR-ICs", name="A")) is True
    assert asset_present(AssetRef(file="models/a.step")) is True
    assert asset_present(AssetRef(lib="SR-ICs")) is False  # container but no entry
    assert asset_present(None) is False


def test_missing_assets_is_per_tool():
    r = _rec()
    r.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    assert r.missing_assets("kicad") == ["footprint", "3D model"]
    assert r.missing_assets("altium") == ["symbol", "footprint"]


def test_missing_assets_skips_a_kind_the_tool_cannot_take_by_reference():
    # Altium stores 3D as a body inside the .PcbLib binary, so a 3D model can never be
    # attached by reference. Reporting it as "missing" would be a permanent false gap.
    assert "3D model" not in _rec().missing_assets("altium")


def test_a_passive_needs_no_owned_model():
    r = _rec(passive=True)
    r.assets_for("kicad").symbol = AssetRef(lib="Device", name="R")
    r.assets_for("kicad").footprint = AssetRef(lib="Resistor_SMD", name="R_0603_1608Metric")
    assert r.missing_assets("kicad") == []


def test_missing_assets_by_tool_covers_every_registered_tool():
    by_tool = _rec().missing_assets_by_tool()
    assert set(by_tool) == {"kicad", "altium"}


# ---------------------------------------------------------------- readiness


def test_tool_assets_ready_requires_both_named_refs():
    r = _rec()
    assert tool_assets_ready(r, "altium") is False
    r.assets_for("altium").symbol = AssetRef(lib="a.SchLib", name="A")
    assert tool_assets_ready(r, "altium") is False
    r.assets_for("altium").footprint = AssetRef(lib="a.PcbLib", name="FP")
    assert tool_assets_ready(r, "altium") is True
    r.eda["altium"].footprint = AssetRef(lib="a.PcbLib", name="")
    assert tool_assets_ready(r, "altium") is False


def test_tool_place_ready_also_needs_the_data_fields():
    r = _rec(mpn="M", manufacturer="TI", description="d")
    r.assets_for("altium").symbol = AssetRef(lib="a.SchLib", name="A")
    r.assets_for("altium").footprint = AssetRef(lib="a.PcbLib", name="FP")
    assert tool_place_ready(r, "altium") is True
    r.description = ""
    assert tool_place_ready(r, "altium") is False


def test_readiness_for_one_tool_is_blind_to_the_other():
    r = _rec(mpn="M", manufacturer="TI", description="d")
    r.assets_for("kicad").symbol = AssetRef(lib="SR-ICs", name="A")
    r.assets_for("kicad").footprint = AssetRef(lib="SR-ICs", name="FP")
    assert tool_place_ready(r, "kicad") is True
    assert tool_place_ready(r, "altium") is False
