from stockroom.capture.requirements import (
    Requirement,
    capture_needs,
    requirement,
    split_requirement,
)
from stockroom.model.part import AssetRef, PartRecord


def _rec(**kw) -> PartRecord:
    return PartRecord(id="x", display_name="n", category="ICs", **kw)


def test_requirement_values_match_contract():
    # The five wire values the TypeScript Requirement union mirrors. The enum is generated
    # from the EDA registry, so this pins the generation against the frontend contract: a
    # registry edit that would rename or drop one of these fails HERE, not in the UI.
    assert Requirement.KICAD_SYMBOL.value == "kicad_symbol"
    assert Requirement.KICAD_FOOTPRINT.value == "kicad_footprint"
    assert Requirement.KICAD_MODEL.value == "kicad_model"
    assert Requirement.ALTIUM_SYMBOL.value == "altium_symbol"
    assert Requirement.ALTIUM_FOOTPRINT.value == "altium_footprint"


def test_no_requirement_exists_for_an_asset_a_tool_cannot_take_by_reference():
    # Altium stores 3D inside the footprint's .PcbLib binary. A capture session asked for
    # "altium_model" would be chasing a file that can never arrive.
    assert "altium_model" not in {r.value for r in Requirement}


def test_the_enum_covers_exactly_the_registry():
    from stockroom.eda.registry import all_tools

    expected = {
        f"{t.key}_{k}"
        for t in all_tools()
        for k in t.asset_kinds
        if k not in t.unsupported_assets
    }
    assert {r.value for r in Requirement} == expected


def test_split_requirement_round_trips():
    assert split_requirement(Requirement.ALTIUM_FOOTPRINT) == ("altium", "footprint")
    assert requirement("altium", "footprint") is Requirement.ALTIUM_FOOTPRINT


def test_a_bare_record_needs_everything_capturable():
    # Registry declaration order: KiCad first (the library Stockroom itself writes).
    assert capture_needs(_rec()) == [
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    ]


def test_needs_reports_only_the_gaps_of_each_tool():
    rec = _rec()
    rec.assets_for("kicad").footprint = AssetRef(lib="SR-ICs", name="VQFN-16")
    rec.assets_for("altium").symbol = AssetRef(lib="a.SchLib", name="U1")
    needs = capture_needs(rec)
    assert Requirement.KICAD_FOOTPRINT not in needs
    assert Requirement.ALTIUM_SYMBOL not in needs
    assert Requirement.KICAD_SYMBOL in needs
    assert Requirement.KICAD_MODEL in needs
    assert Requirement.ALTIUM_FOOTPRINT in needs


def test_a_full_kicad_set_does_not_mark_altium_satisfied():
    # The bug this cutover exists to kill ran the other way too: one tool's assets must
    # never be read as another tool's.
    rec = _rec()
    k = rec.assets_for("kicad")
    k.symbol = AssetRef(lib="SR-ICs", name="U1")
    k.footprint = AssetRef(lib="SR-ICs", name="VQFN-16")
    k.model = AssetRef(file="models/u1.step")
    assert capture_needs(rec) == [Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT]


def test_a_ref_with_a_blank_name_is_not_satisfied():
    rec = _rec()
    rec.assets_for("altium").symbol = AssetRef(lib="a.SchLib", name="")
    assert Requirement.ALTIUM_SYMBOL in capture_needs(rec)


def test_a_passive_needs_no_owned_3d_model():
    rec = _rec(passive=True)
    assert Requirement.KICAD_MODEL not in capture_needs(rec)
