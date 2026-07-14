"""M7f-D projects/fill compute + byte-preserving writers: annotate references (both the display
property and the instances-path reference), match placed components against the Stockroom library,
build a fill plan, fill identity fields onto placed instances only (never the lib_symbols cache),
and roll up the completion passport. Verified against self-contained KiCad-10 fixtures AND, where
present, a real NETDECK sheet."""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.model.part import Datasheet, LibRef, PartRecord
from stockroom.projects import fill
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
        symbol=LibRef(lib="SR-ICs", name="LM358"),
        footprint=LibRef(lib="SR-ICs", name="SOIC-8"),
        datasheet=Datasheet(file="lm358.pdf", source_url="https://ti.com/lm358.pdf"),
    )
    res = PartRecord(
        id="r10k", display_name="10k 0402", category="Resistors",
        description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo",
        symbol=LibRef(lib="SR-Resistors", name="R_10k"),
        footprint=LibRef(lib="SR-Resistors", name="R_0402"),
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
        symbol=LibRef(lib="SR-ICs", name="D"),
        datasheet=Datasheet(file="datasheets/d.pdf", source_url=""),  # file present, URL empty
    )
    rec = fill.library_match_records([part])[0]
    assert rec["datasheet"] == "datasheets/d.pdf"


def test_bad_category_part_kept_for_identity_but_drops_symbol_footprint():
    part = PartRecord(
        id="w", display_name="Widget", category="Widgets",  # not in the taxonomy
        description="x", mpn="WMPN", manufacturer="ACME",
        symbol=LibRef(lib="X", name="WSYM"), footprint=LibRef(lib="X", name="WFP"),
    )
    rec = fill.library_match_records([part])
    assert len(rec) == 1  # not dropped
    r = rec[0]
    assert r["mpn"] == "WMPN" and r["name"] == "" and r["footprint_stem"] == "" and r["nickname"] == ""


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
