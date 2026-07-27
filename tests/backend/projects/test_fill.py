"""M7f-D projects/fill compute + byte-preserving writers: annotate references (both the display
property and the instances-path reference), match placed components against the Stockroom library,
build a fill plan, fill identity fields onto placed instances only (never the lib_symbols cache),
and roll up the completion passport. Verified against self-contained KiCad-10 fixtures AND, where
present, a real NETDECK sheet."""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.model.part import AssetRef, Datasheet, EdaAssets, PartRecord
from stockroom.model.part_class import PartClass
from stockroom.projects import binding, fill
from stockroom.sexp.document import SexpDocument
from stockroom.verify.semdiff import assert_only_changed

_REAL_SCH = Path("/home/sadad/git/NETDECK/Master/Power_Supply.kicad_sch")


def _symbol(*, lib_id, ref, value="10k", footprint="Resistor_SMD:R_0402",
            datasheet="~", extra_props="", inst_ref=None, uuid="u-0000", unit="1",
            extra_instances=""):
    """A structurally-real KiCad-10 placed symbol instance: a (lib_id), the standard properties, and
    an (instances (project (path (reference ...)))) block. `inst_ref` defaults to `ref` (KiCad keeps
    the two in sync). `extra_instances` appends more (path (reference ...)) atoms (repeated hierarchy)."""
    inst_ref = ref if inst_ref is None else inst_ref
    return "".join([
        "\t(symbol\n",
        f'\t\t(lib_id "{lib_id}")\n',
        "\t\t(at 10 10 0)\n",
        f"\t\t(unit {unit})\n",
        "\t\t(in_bom yes)\n",
        "\t\t(dnp no)\n",
        f'\t\t(uuid "{uuid}")\n',
        f'\t\t(property "Reference" "{ref}"\n\t\t\t(at 10 8 0)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Value" "{value}"\n\t\t\t(at 12 10 0)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Footprint" "{footprint}"\n\t\t\t(at 10 10 0)\n\t\t\t(hide yes)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        f'\t\t(property "Datasheet" "{datasheet}"\n\t\t\t(at 10 10 0)\n\t\t\t(hide yes)\n',
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n",
        extra_props,
        '\t\t(instances\n\t\t\t(project "proj"\n',
        '\t\t\t\t(path "/root-uuid"\n',
        f'\t\t\t\t\t(reference "{inst_ref}")\n\t\t\t\t\t(unit {unit})\n\t\t\t\t)\n',
        extra_instances,
        "\t\t\t)\n\t\t)\n",
        "\t)\n",
    ])


# A KiCad-10 sheet: a lib_symbols cache (a "Device:R" whose cache Reference "R" must never be touched),
# an unannotated resistor R? (missing MPN/Manufacturer/Description, blank Datasheet), an annotated U1
# already linked to a library symbol, an unannotated capacitor C?, and a power flag #PWR? (never
# annotated). The cache carries a (reference "R?")-free graphic so the walk cannot mistake it.
def _sheet():
    cache = (
        "\t(lib_symbols\n"
        '\t\t(symbol "Device:R"\n'
        '\t\t\t(property "Reference" "R"\n\t\t\t\t(at 0 0 0)\n'
        "\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n"
        '\t\t\t(property "Value" "R"\n\t\t\t\t(at 0 0 0)\n'
        "\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
    )
    r = _symbol(lib_id="Device:R", ref="R?", value="10k",
                footprint="Resistor_SMD:R_0402", datasheet="~", uuid="u-r")
    u = _symbol(lib_id="SR-ICs:LM358", ref="U1", value="LM358",
                footprint="Package_SO:SOIC-8", datasheet="~", uuid="u-u")
    c = _symbol(lib_id="Device:C", ref="C?", value="100nF",
                footprint="Capacitor_SMD:C_0402", datasheet="~", uuid="u-c")
    pwr = _symbol(lib_id="power:GND", ref="#PWR?", value="GND",
                  footprint="", datasheet="~", uuid="u-pwr")
    return "(kicad_sch\n\t(version 20260306)\n" + cache + r + u + c + pwr + ")\n"


def _parts():
    """A small Stockroom library: an op-amp whose symbol name matches U1's lib_id, and a resistor whose
    MPN matches (nothing matches by symbol for the generic Device:R placed part)."""
    opamp = PartRecord(
        id="lm358", display_name="LM358 Op-Amp", category="ICs",
        description="Dual op-amp", mpn="LM358DR", manufacturer="TI",
        assets={"kicad": EdaAssets(
            symbol=AssetRef(lib="SR-ICs", name="LM358"),
            footprint=AssetRef(lib="SR-ICs", name="SOIC-8"),
        )},
        datasheet=Datasheet(file="lm358.pdf", source_url="https://ti.com/lm358.pdf"),
    )
    res = PartRecord(
        id="r10k", display_name="10k 0402", category="Resistors",
        description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo",
        assets={"kicad": EdaAssets(
            symbol=AssetRef(lib="SR-Resistors", name="R_10k"),
            footprint=AssetRef(lib="SR-Resistors", name="R_0402"),
        )},
        datasheet=Datasheet(file="r.pdf", source_url="https://yageo.com/r.pdf"),
    )
    return [opamp, res]


# -- read_components -----------------------------------------------------------


def test_read_components_returns_placed_only_and_skips_power_and_cache():
    doc = SexpDocument.parse(_sheet())
    comps = fill.read_components(doc)
    refs = {c["ref"] for c in comps}
    assert refs == {"R?", "U1", "C?"}  # cache symbol + #PWR? power flag excluded
    r = next(c for c in comps if c["ref"] == "R?")
    assert r["lib_id"] == "Device:R" and r["value"] == "10k"
    assert r["footprint"] == "Resistor_SMD:R_0402"


def test_read_components_include_power_flag():
    doc = SexpDocument.parse(_sheet())
    comps = fill.read_components(doc, include_power=True)
    assert "#PWR?" in {c["ref"] for c in comps}


# -- match_component -----------------------------------------------------------


def test_match_by_symbol_name():
    index = fill.library_match_records(_parts())
    comp = {"ref": "U1", "lib_id": "SR-ICs:LM358", "props": {"Reference": "U1"}}
    m = fill.match_component(comp, index)
    assert m["confidence"] == "symbol" and m["part"]["id"] == "lm358"


def test_match_by_mpn_when_symbol_misses():
    index = fill.library_match_records(_parts())
    comp = {"ref": "R5", "lib_id": "Device:R",
            "props": {"Reference": "R5", "MPN": "RC0402FR-0710KL"}}
    m = fill.match_component(comp, index)
    assert m["confidence"] == "mpn" and m["part"]["id"] == "r10k"


def test_match_none_for_unknown():
    index = fill.library_match_records(_parts())
    comp = {"ref": "R9", "lib_id": "Device:R", "props": {"Reference": "R9", "Value": "47k"}}
    assert fill.match_component(comp, index)["part"] is None


# -- proposed_changes / plan ---------------------------------------------------


def test_proposed_changes_fills_blanks_and_flags_overwrites():
    part = fill.library_match_records(_parts())[0]  # the op-amp
    props = {"MPN": "", "Manufacturer": "", "Datasheet": "~", "Description": "old desc",
             "Footprint": "Package_SO:SOIC-8"}
    changes = {c["prop"]: c for c in fill.proposed_changes(part, props)}
    assert changes["MPN"]["new"] == "LM358DR" and changes["MPN"]["kind"] == "fill"
    assert changes["Datasheet"]["new"] == "https://ti.com/lm358.pdf"
    assert changes["Description"]["kind"] == "overwrite"  # a non-blank value differs
    # Footprint qualifies to SR-<slug>:<stem>; the placed value differs so it is proposed.
    assert changes["Footprint"]["new"] == "SR-ICs:SOIC-8"


def test_build_fill_plan_default_selects_all_fill_items():
    index = fill.library_match_records(_parts())
    comps = [
        {"ref": "U1", "lib_id": "SR-ICs:LM358",
         "props": {"Reference": "U1", "Footprint": "SR-ICs:SOIC-8"}},  # all fills (blank identity)
        {"ref": "R9", "lib_id": "Device:R", "props": {"Reference": "R9", "Value": "47k"}},  # no match
    ]
    plan = fill.build_fill_plan(comps, index, {"U1": "root.kicad_sch"})
    assert plan["summary"]["no_match"] == 1
    u = next(i for i in plan["items"] if i["ref"] == "U1")
    assert u["default_selected"] is True and u["sheet"] == "root.kicad_sch"
    assert u["part_id"] == "lm358"


# -- completion passport -------------------------------------------------------


def test_component_completion_counts_present_identity():
    complete = {"ref": "U1", "footprint": "SR:x", "props": {
        "MPN": "LM358", "Manufacturer": "TI", "Datasheet": "http://x", "Description": "d",
        "Footprint": "SR:x"}}
    assert fill.component_completion(complete)["is_complete"] is True
    bare = {"ref": "R1", "footprint": "", "props": {"Value": "10k"}}
    p = fill.component_completion(bare)
    assert p["is_complete"] is False and set(p["missing"]) == {
        "Footprint", "MPN", "Manufacturer", "Datasheet", "Description"}


def test_project_completion_rolls_up_missing_counts():
    comps = [
        {"ref": "R1", "footprint": "", "props": {}},
        {"ref": "U1", "footprint": "x", "props": {
            "MPN": "m", "Manufacturer": "t", "Datasheet": "d", "Description": "z", "Footprint": "x"}},
    ]
    roll = fill.project_completion(comps)
    assert roll["total"] == 2 and roll["complete"] == 1
    assert roll["incomplete_refs"] == ["R1"]
    assert roll["missing_counts"]["MPN"] == 1


def test_project_readiness_adds_unannotated_and_missing_footprint():
    # M7g: the buildability verdict gates on the physical-board signals (annotation + footprint),
    # so project_readiness extends the completion roll-up with those two counts.
    comps = [
        {"ref": "R?", "footprint": "", "props": {"Reference": "R?"}},  # unannotated + no footprint
        {"ref": "U1", "footprint": "SR:x", "props": {
            "MPN": "m", "Manufacturer": "t", "Datasheet": "d", "Description": "z", "Footprint": "SR:x"}},
    ]
    r = fill.project_readiness(comps)
    assert r["total"] == 2 and r["complete"] == 1
    assert r["unannotated"] == 1  # R?
    assert r["missing_footprint"] == 1  # R? carries no footprint


def test_project_readiness_clean_when_annotated_and_footprinted():
    comps = [{"ref": "U1", "footprint": "SR:x", "props": {
        "MPN": "m", "Manufacturer": "t", "Datasheet": "d", "Description": "z", "Footprint": "SR:x"}}]
    r = fill.project_readiness(comps)
    assert r["unannotated"] == 0 and r["missing_footprint"] == 0


def test_project_readiness_empty_project():
    r = fill.project_readiness([])
    assert r["total"] == 0 and r["unannotated"] == 0 and r["missing_footprint"] == 0


# -- annotation (byte-preserving, both forms) ----------------------------------


def test_annotate_numbers_both_reference_forms_byte_preservingly():
    text = _sheet()
    doc = SexpDocument.parse(text)
    used = fill.used_references([text])
    assert "U1" in used  # the annotated instance seeds the used set
    n = fill.annotate_document(doc, used)
    assert n == 2  # R? and C? (not U1, not #PWR?)
    out = doc.serialize()
    # R? -> R1 (U1 already taken so R gets 1), C? -> C1; both the property and instances forms move.
    assert out.count('(property "Reference" "R1"') == 1
    assert out.count('(reference "R1")') == 1
    assert out.count('(property "Reference" "C1"') == 1
    assert out.count('(reference "C1")') == 1
    # the two unannotated designators are gone in both forms (guard the substring against #PWR?)
    assert '"R?"' not in out and '"C?"' not in out
    assert '"#PWR?"' in out  # power ref untouched
    # exactly 2 atoms per annotated instance changed (property value + instances reference)
    assert_only_changed(text, out, allowed_changes=4)


def test_annotate_is_idempotent():
    text = _sheet()
    doc = SexpDocument.parse(text)
    used = fill.used_references([text])
    fill.annotate_document(doc, used)
    once = doc.serialize()
    doc2 = SexpDocument.parse(once)
    assert fill.annotate_document(doc2, fill.used_references([once])) == 0
    assert doc2.serialize() == once


def test_annotate_defers_multi_unit_to_kicad():
    # Two units of ONE multi-unit part (same lib_id, unit 1 + unit 2, both "U?") are ambiguous to pack
    # from the file alone, so annotate leaves them "?" for KiCad rather than assign U1/U2 (which would
    # split one component into two).
    a = _symbol(lib_id="Amp:LM358", ref="U?", value="LM358", unit="1", uuid="ua")
    b = _symbol(lib_id="Amp:LM358", ref="U?", value="LM358", unit="2", uuid="ub")
    text = "(kicad_sch\n" + a + b + ")\n"
    doc = SexpDocument.parse(text)
    assert fill.annotate_document(doc, fill.used_references([text])) == 0
    assert doc.serialize() == text  # untouched: both remain "U?"


def test_annotate_still_numbers_two_single_unit_parts_of_same_lib_id():
    # Two separate single-unit resistors of the same lib_id (both unit 1) ARE distinct components and
    # must still be numbered R1 / R2 (a multi-unit part needs >1 DISTINCT unit to be deferred).
    a = _symbol(lib_id="Device:R", ref="R?", unit="1", uuid="ra")
    b = _symbol(lib_id="Device:R", ref="R?", unit="1", uuid="rb")
    text = "(kicad_sch\n" + a + b + ")\n"
    doc = SexpDocument.parse(text)
    assert fill.annotate_document(doc, fill.used_references([text])) == 2
    out = doc.serialize()
    assert '(property "Reference" "R1"' in out and '(property "Reference" "R2"' in out


def test_annotate_defers_repeated_hierarchy_instance_to_kicad():
    # A symbol whose (instances ...) carries more than one "R?" path (a sub-sheet used N times) must
    # get a DISTINCT designator per instance; annotate leaves it for KiCad rather than collapse them.
    extra = '\t\t\t\t(path "/root-uuid-2"\n\t\t\t\t\t(reference "R?")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n'
    sym = _symbol(lib_id="Device:R", ref="R?", uuid="rp", extra_instances=extra)
    text = "(kicad_sch\n" + sym + ")\n"
    doc = SexpDocument.parse(text)
    assert fill.annotate_document(doc, fill.used_references([text])) == 0
    assert doc.serialize() == text


def test_proposed_changes_does_not_re_add_mpn_under_an_alternate_key():
    # A component whose part number lives under "Manufacturer Part Number" (not "MPN") already has an
    # MPN by the strict rule, so Complete-All must not propose a FILL (which would insert a duplicate
    # "MPN" property); the difference is an overwrite the conservative auto pass skips.
    part = fill.library_match_records(_parts())[0]  # op-amp, mpn LM358DR
    props = {"Manufacturer Part Number": "EXISTING-MPN"}
    mpn = next((c for c in fill.proposed_changes(part, props) if c["prop"] == "MPN"), None)
    assert mpn is not None and mpn["kind"] == "overwrite"  # never a fill -> auto pass leaves it alone


def test_datasheet_falls_back_to_file_when_no_source_url():
    part = PartRecord(
        id="d", display_name="D", category="ICs", description="x", mpn="M1", manufacturer="ACME",
        assets={"kicad": EdaAssets(symbol=AssetRef(lib="SR-ICs", name="D"))},
        datasheet=Datasheet(file="datasheets/d.pdf", source_url=""),  # file present, URL empty
    )
    rec = fill.library_match_records([part])[0]
    assert rec["datasheet"] == "datasheets/d.pdf"


def test_bad_category_part_keeps_its_references_but_forfeits_the_symbol_tier():
    # A category outside the taxonomy has no Stockroom library, so the part cannot OWN its symbol and
    # must not be reachable at the identity tier. Its stored references are still carried verbatim
    # (they do not depend on the category), so a manual fill still lands a resolvable link, and its
    # identity fields still fill.
    part = PartRecord(
        id="w", display_name="Widget", category="Widgets",  # not in the taxonomy
        description="x", mpn="WMPN", manufacturer="ACME",
        assets={"kicad": EdaAssets(symbol=AssetRef(lib="X", name="WSYM"), footprint=AssetRef(lib="X", name="WFP"))},
    )
    rec = fill.library_match_records([part])
    assert len(rec) == 1  # not dropped
    r = rec[0]
    assert r["mpn"] == "WMPN" and r["nickname"] == ""
    assert r["symbol_is_identity"] is False
    assert r["symbol_lib_id"] == "X:WSYM" and r["footprint_lib_id"] == "X:WFP"
    # ...and the untaxonomised category can no longer reach the identity tier through its symbol name.
    m = fill.match_component({"ref": "W1", "lib_id": "X:WSYM", "props": {}}, rec)
    assert m["confidence"] == "none"


# -- generic stock symbols must never identify a library part -------------------
#
# A Stockroom passive does NOT own copied symbol/footprint files: `resolve_passive_assets` files it
# against the INSTALLED KiCad stock libraries ("Device:R", "Resistor_SMD:R_0402_1005Metric"), which is
# why `previews.py` resolves a passive's symbol out of the KiCad share directory. So every Stockroom
# resistor carries the same symbol name "R", and a project's generic `Device:R` cannot possibly
# identify one of them.


def _passive_parts():
    """Two Stockroom resistors exactly as `add_passive_part` files them: the symbol and footprint are
    KiCad STOCK references, not Stockroom-owned entries."""
    def res(pid, mpn, value, package, metric):
        return PartRecord(
            id=pid, display_name=f"{value} {package}", category="Resistors",
            description=f"{value} 1% {package}", mpn=mpn, manufacturer="Yageo", part_class=PartClass.PASSIVE,
            assets={"kicad": EdaAssets(
                symbol=AssetRef(lib="Device", name="R"),
                footprint=AssetRef(lib="Resistor_SMD", name=f"R_{package}_{metric}"),
            )},
            specs={"Resistance": value, "Package": package},
        )
    return [res("r10k", "RC0402FR-0710KL", "10 kOhm", "0402", "1005Metric"),
            res("r47k", "RC0603FR-0747KL", "47 kOhm", "0603", "1608Metric")]


def test_generic_stock_symbol_is_never_an_identity_match():
    # The owner's scenario: a project full of default-library passives. A placed "Device:R" whose Value
    # is 47k must NOT be handed the FIRST resistor in the index at the highest confidence tier, which
    # is what silently wrote a wrong MPN into the schematic.
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "lib_id": "Device:R", "props": {"Reference": "R5", "Value": "47k"}}
    m = fill.match_component(comp, index)
    assert m["confidence"] != "symbol", "a generic stock symbol name is not a part identity"
    assert m["part"] is None or m["part"]["id"] != "r10k", "must not pick the first index entry"


def test_generic_stock_symbol_contributes_no_plan_item():
    # Asserted positively (items == [], no_match == 1) rather than by looping over items and checking
    # `default_selected`, which would pass vacuously the moment the plan is empty. A headless
    # Complete-All must propose NOTHING for a generic placement it cannot identify. When the
    # value+package tier lands, this becomes an assertion that the item is present and NOT preselected.
    index = fill.library_match_records(_passive_parts())
    comps = [{"ref": "R5", "lib_id": "Device:R", "props": {"Reference": "R5", "Value": "47k"}}]
    plan = fill.build_fill_plan(comps, index, {"R5": "root.kicad_sch"})
    assert plan["items"] == []
    assert plan["summary"]["no_match"] == 1


def test_fill_writes_the_records_own_lib_id_not_a_requalified_one():
    # A fill/manual-fill repoints the placed instance's (lib_id ...) and writes the Footprint link. Both
    # must be the reference the record ACTUALLY holds. Re-qualifying a passive's stock reference to
    # "SR-Resistors:..." points the schematic at the Stockroom category library, which does not contain
    # the stock symbol or footprint, so KiCad can no longer resolve either.
    part = next(p for p in fill.library_match_records(_passive_parts()) if p["id"] == "r10k")
    assert fill.lib_id_for(part) == "Device:R"
    fp = {c["prop"]: c["new"] for c in fill.proposed_changes(part, {})}
    assert fp["Footprint"] == "Resistor_SMD:R_0402_1005Metric"


# -- candidate tier: value-matched picks for a generic placement ----------------


def test_candidates_are_value_matched_parts_carrying_the_same_symbol():
    # The owner's scenario made safe: a placed Device:R valued 47k offers the 47k part as a CANDIDATE
    # (not an auto-assignment). Candidates are restricted to records carrying the SAME symbol
    # reference, so accepting one never repoints the schematic's symbol, it only fills fields.
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "lib_id": "Device:R",
            "props": {"Reference": "R5", "Value": "47k",
                      "Footprint": "Resistor_SMD:R_0603_1608Metric"}}
    cands = fill.candidate_matches(comp, index)
    assert [c["part_id"] for c in cands] == ["r47k"]
    assert cands[0]["confidence"] == "value+footprint"


def test_candidate_value_notations_match_across_spellings():
    # The schematic's terse form against the record's spelled-out spec, through the one shared parser.
    index = fill.library_match_records(_passive_parts())
    for value in ("10k", "10K", "10 kOhm", "10k 1%"):
        comp = {"ref": "R1", "lib_id": "Device:R", "props": {"Value": value}}
        assert [c["part_id"] for c in fill.candidate_matches(comp, index)] == ["r10k"], value


def test_candidate_ranks_footprint_agreement_above_value_alone():
    index = fill.library_match_records(_passive_parts())
    # Both library parts are 10k in this variant, differing only in package.
    index[1]["value"] = "10 kOhm"
    comp = {"ref": "R1", "lib_id": "Device:R",
            "props": {"Value": "10k", "Footprint": "Resistor_SMD:R_0402_1005Metric"}}
    cands = fill.candidate_matches(comp, index)
    assert [c["part_id"] for c in cands] == ["r10k", "r47k"]
    assert cands[0]["confidence"] == "value+footprint" and cands[1]["confidence"] == "value"


def test_candidate_matches_package_when_the_footprint_variant_differs():
    # A schematic often carries a pad-variant footprint the library does not use verbatim. The EIA case
    # still agrees, which is a real (weaker) signal, and must rank between exact and value-only.
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R1", "lib_id": "Device:R",
            "props": {"Value": "10k",
                      "Footprint": "Resistor_SMD:R_0402_1005Metric_Pad0.72x0.64mm_HandSolder"}}
    cands = fill.candidate_matches(comp, index)
    assert [c["part_id"] for c in cands] == ["r10k"]
    assert cands[0]["confidence"] == "value+package"


def test_candidates_surface_only_the_ratings_that_differ_between_them():
    # Two library parts that are BOTH genuinely "10k 0402" and differ only in tolerance. The evidence
    # tier is identical on both rows, so the tier alone tells the user nothing; what makes the choice
    # possible is seeing the rating that actually differs. A rating they SHARE is noise and is omitted.
    def res(pid, mpn, tol):
        return PartRecord(
            id=pid, display_name="10k 0402 Thick Film", category="Resistors",
            description=f"10k {tol} 0402", mpn=mpn, manufacturer="Yageo", part_class=PartClass.PASSIVE,
            assets={"kicad": EdaAssets(
                symbol=AssetRef(lib="Device", name="R"),
                footprint=AssetRef(lib="Resistor_SMD", name="R_0402_1005Metric"),
            )},
            specs={"Resistance": "10 kOhm", "Package": "0402",
                   "Tolerance": tol, "Power": "1/16 W"},
        )
    index = fill.library_match_records([res("a", "RC-1", "1%"), res("b", "RC-5", "5%")])
    comp = {"ref": "R1", "lib_id": "Device:R",
            "props": {"Value": "10k", "Footprint": "Resistor_SMD:R_0402_1005Metric"}}
    cands = fill.candidate_matches(comp, index)
    assert [c["confidence"] for c in cands] == ["value+footprint", "value+footprint"]
    assert [c["distinguish"] for c in cands] == [["1%"], ["5%"]]  # Power is shared, so it is omitted


def test_a_rating_the_name_already_states_is_not_repeated():
    # A row reading "10k 0402 1%" beside a separate "1%" chip says the same thing twice. Suppression is
    # by whole TOKEN, never substring, so an "11%" part does not swallow a "1%" rating.
    def res(pid, mpn, tol, name):
        return PartRecord(
            id=pid, display_name=name, category="Resistors", description="10k",
            mpn=mpn, manufacturer="Yageo", part_class=PartClass.PASSIVE,
            assets={"kicad": EdaAssets(
                symbol=AssetRef(lib="Device", name="R"),
                footprint=AssetRef(lib="Resistor_SMD", name="R_0402_1005Metric"),
            )},
            specs={"Resistance": "10 kOhm", "Package": "0402", "Tolerance": tol},
        )
    comp = {"ref": "R1", "lib_id": "Device:R", "props": {"Value": "10k"}}

    named = fill.library_match_records([res("a", "RC-1", "1%", "10k 0402 1%"),
                                       res("b", "RC-5", "5%", "10k 0402 5%")])
    assert [c["distinguish"] for c in fill.candidate_matches(comp, named)] == [[], []]

    # The near-miss that a substring test would get wrong: "11%" as a name token must NOT suppress a
    # "1%" rating on the OTHER candidate.
    tricky = fill.library_match_records([res("a", "RC-1", "1%", "10k 0402 11% marked"),
                                        res("b", "RC-5", "5%", "10k 0402 Thick Film")])
    assert [c["distinguish"] for c in fill.candidate_matches(comp, tricky)] == [["1%"], ["5%"]]


def test_a_lone_candidate_has_nothing_to_distinguish_it_from():
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R1", "lib_id": "Device:R", "props": {"Value": "10k"}}
    assert fill.candidate_matches(comp, index)[0]["distinguish"] == []


def test_no_candidates_for_an_unreadable_value():
    index = fill.library_match_records(_passive_parts())
    for value in ("", "DNP", "~", "10k 0402"):
        comp = {"ref": "R1", "lib_id": "Device:R", "props": {"Value": value}}
        assert fill.candidate_matches(comp, index) == [], value


def test_candidates_exclude_a_part_whose_symbol_is_a_different_reference():
    # A capacitor record must never be a candidate for a placed resistor symbol, whatever the numbers
    # say. The symbol reference is the hard filter.
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "C1", "lib_id": "Device:C", "props": {"Value": "10k"}}
    assert fill.candidate_matches(comp, index) == []


def test_candidates_are_never_offered_for_an_identified_component():
    # A component the identity tiers already matched is not a guessing problem.
    index = fill.library_match_records(_parts())
    comp = {"ref": "U1", "lib_id": "SR-ICs:LM358", "props": {"Reference": "U1"}}
    assert fill.candidate_matches(comp, index) == []


# -- grouping: "a bunch of passives" is ONE decision ---------------------------


def test_group_placements_collapses_identical_placements():
    comps = [
        {"ref": "R1", "lib_id": "Device:R", "props": {"Value": "10k", "Footprint": "F:R_0402"}},
        {"ref": "R2", "lib_id": "Device:R", "props": {"Value": "10k", "Footprint": "F:R_0402"}},
        {"ref": "R3", "lib_id": "Device:R", "props": {"Value": "47k", "Footprint": "F:R_0402"}},
        {"ref": "C1", "lib_id": "Device:C", "props": {"Value": "100n", "Footprint": "F:C_0402"}},
    ]
    groups = fill.group_placements(comps)
    assert [(g["value"], g["refs"]) for g in groups] == [
        ("100n", ["C1"]), ("10k", ["R1", "R2"]), ("47k", ["R3"]),
    ]
    tenk = next(g for g in groups if g["value"] == "10k")
    assert tenk["count"] == 2 and tenk["lib_id"] == "Device:R"


def test_group_placements_keeps_differing_footprints_apart():
    comps = [
        {"ref": "R1", "lib_id": "Device:R", "props": {"Value": "10k", "Footprint": "F:R_0402"}},
        {"ref": "R2", "lib_id": "Device:R", "props": {"Value": "10k", "Footprint": "F:R_0603"}},
    ]
    assert [g["refs"] for g in fill.group_placements(comps)] == [["R1"], ["R2"]]


def test_group_placements_is_deterministic_and_sorts_refs_naturally():
    # R10 must sort after R9, not between R1 and R2: the group's ref list is shown to the user and
    # written into a commit message, so a lexicographic order would read as scrambled.
    comps = [{"ref": r, "lib_id": "Device:R", "props": {"Value": "10k", "Footprint": "F:R_0402"}}
             for r in ("R10", "R2", "R1", "R9")]
    assert fill.group_placements(comps)[0]["refs"] == ["R1", "R2", "R9", "R10"]


def test_owned_symbol_still_identifies_its_part():
    # The guard must not cost the real case: a part that OWNS its symbol in its Stockroom category
    # library is still an identity match at the "symbol" tier.
    index = fill.library_match_records(_parts())
    comp = {"ref": "U1", "lib_id": "SR-ICs:LM358", "props": {"Reference": "U1"}}
    m = fill.match_component(comp, index)
    assert m["confidence"] == "symbol" and m["part"]["id"] == "lm358"


def test_annotate_is_project_wide_unique_across_sheets():
    a = "(kicad_sch\n" + _symbol(lib_id="Device:R", ref="R?", uuid="a") + ")\n"
    b = "(kicad_sch\n" + _symbol(lib_id="Device:R", ref="R?", uuid="b") + ")\n"
    used = fill.used_references([a, b])
    da, db = SexpDocument.parse(a), SexpDocument.parse(b)
    fill.annotate_document(da, used)
    fill.annotate_document(db, used)
    assert '(property "Reference" "R1"' in da.serialize()
    assert '(property "Reference" "R2"' in db.serialize()  # no collision


# -- fill (byte-preserving) ----------------------------------------------------


def test_fill_sets_existing_blank_property_byte_preservingly():
    text = _sheet()
    doc = SexpDocument.parse(text)
    # fill U1's blank Datasheet (an existing property) -> a CHANGED atom, no structural change
    n = fill.fill_document(doc, {"U1": {"Datasheet": "https://ti.com/lm358.pdf"}})
    assert n == 1
    out = doc.serialize()
    assert '(property "Datasheet" "https://ti.com/lm358.pdf"' in out
    assert_only_changed(text, out, allowed_changes=1)


def test_fill_inserts_absent_property():
    text = _sheet()
    doc = SexpDocument.parse(text)
    n = fill.fill_document(doc, {"U1": {"MPN": "LM358DR", "Manufacturer": "TI"}})
    assert n == 1
    out = doc.serialize()
    assert '(property "MPN" "LM358DR"' in out
    assert '(property "Manufacturer" "TI"' in out
    assert SexpDocument.parse(out).root.name == "kicad_sch"  # still valid


def test_fill_repoints_lib_id_on_placed_only():
    text = _sheet()
    doc = SexpDocument.parse(text)
    fill.fill_document(doc, {}, lib_id_by_ref={"R?": "SR-Resistors:R_10k"})
    out = doc.serialize()
    assert '(lib_id "SR-Resistors:R_10k")' in out
    # the lib_symbols cache "Device:R" symbol keeps its name (never repointed)
    assert '(symbol "Device:R"' in out


def test_fill_never_touches_lib_symbols_cache():
    text = _sheet()
    doc = SexpDocument.parse(text)
    # A ref "R" (the cache symbol's bare Reference) must not match any placed instance.
    n = fill.fill_document(doc, {"R": {"MPN": "SHOULD-NOT-APPEAR"}})
    assert n == 0
    assert "SHOULD-NOT-APPEAR" not in doc.serialize()


def test_fill_is_idempotent():
    text = _sheet()
    doc = SexpDocument.parse(text)
    fill.fill_document(doc, {"U1": {"Datasheet": "https://x"}})
    once = doc.serialize()
    doc2 = SexpDocument.parse(once)
    assert fill.fill_document(doc2, {"U1": {"Datasheet": "https://x"}}) == 0
    assert doc2.serialize() == once


def test_lib_id_for_qualifies_symbol():
    part = fill.library_match_records(_parts())[0]
    assert fill.lib_id_for(part) == "SR-ICs:LM358"


# -- real fixture (skipped in CI: external repo) -------------------------------


@pytest.mark.skipif(not _REAL_SCH.exists(), reason="NETDECK fixture not present")
def test_read_and_fill_roundtrip_on_real_sheet_is_byte_identical_when_noop():
    doc = SexpDocument.load(_REAL_SCH)
    comps = fill.read_components(doc)
    assert comps  # the real sheet has placed instances
    # a fill of values already on disk changes nothing -> byte identical
    changes = {c["ref"]: {"Value": c["value"]} for c in comps if c["value"]}
    before = doc.serialize()
    fill.fill_document(doc, changes)
    assert doc.serialize() == before


# -- the binding tier: a recorded assignment outranks every guess ---------------


def test_read_components_carries_the_placements_uuid():
    # The durable placement identity. Without it every binding would be keyed by a designator
    # that annotation rewrites.
    doc = SexpDocument.parse(_sheet())
    comps = {c["ref"]: c for c in fill.read_components(doc)}
    assert comps["U1"]["uuid"] == "u-u"


def test_a_bound_placement_matches_its_bound_part_over_the_symbol_tier():
    """The binding is the user's explicit decision, so it outranks the symbol tier's inference.
    Proven with a placement whose symbol WOULD identify a different part."""
    index = fill.library_match_records(_parts())
    comp = {"ref": "U1", "uuid": "u-u", "lib_id": "SR-ICs:LM358",
            "props": {"Reference": "U1", binding.BOUND_PART: "r10k"}}
    m = fill.match_component(comp, index)
    assert m["confidence"] == "binding"
    assert m["part"]["id"] == "r10k"


def test_a_bound_generic_passive_is_matched_where_nothing_else_could_match_it():
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "lib_id": "Device:R", "props": {"Reference": "R5", "Value": "47k"}}
    assert fill.match_component(comp, index)["part"] is None
    comp["props"][binding.BOUND_PART] = "r10k"
    m = fill.match_component(comp, index)
    assert m["confidence"] == "binding"
    assert m["part"]["id"] == "r10k"


def test_a_binding_naming_a_part_that_no_longer_exists_never_falls_back_to_a_GUESS():
    """Silently substituting whatever the guesser finds for a deleted part is exactly the class
    of bug this slice exists to remove. A dangling binding reports itself instead."""
    index = fill.library_match_records(_parts())
    comp = {"ref": "U1", "uuid": "u-u", "lib_id": "SR-ICs:LM358",
            "props": {"Reference": "U1", binding.BOUND_PART: "deleted-part"}}
    m = fill.match_component(comp, index)
    assert m["part"] is None
    assert m["confidence"] == "binding_missing"


def test_a_bound_placement_offers_no_candidates_because_it_is_already_decided():
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "lib_id": "Device:R",
            "props": {"Reference": "R5", "Value": "47k", binding.BOUND_PART: "r47k"}}
    assert fill.candidate_matches(comp, index) == []


def test_a_DANGLING_binding_still_offers_candidates_so_the_user_can_repair_it():
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "lib_id": "Device:R",
            "props": {"Reference": "R5", "Value": "47k", binding.BOUND_PART: "deleted-part"}}
    assert [c["part_id"] for c in fill.candidate_matches(comp, index)] == ["r47k"]


def test_a_bound_placement_survives_a_reannotate_and_a_value_edit():
    """The property the whole slice exists for, exercised end to end on the pure layer: the
    binding still resolves to the same part after the reference is renumbered and the Value is
    changed, both of which break every other tier."""
    index = fill.library_match_records(_passive_parts())
    comp = {"ref": "R5", "uuid": "u-r5", "lib_id": "Device:R",
            "props": {"Reference": "R5", "Value": "10k", binding.BOUND_PART: "r10k"}}
    assert fill.match_component(comp, index)["part"]["id"] == "r10k"
    comp["ref"] = "R91"
    comp["props"]["Reference"] = "R91"
    comp["props"]["Value"] = "47k"
    assert fill.match_component(comp, index)["part"]["id"] == "r10k"
