"""M7f-B object conform: byte-preserving font size/thickness normalize over the SexpDocument
bulk-edit seam. Verified against inline fixtures AND the real KiCad-10 fixtures."""

from pathlib import Path

import pytest

from stockroom.kicad import conform
from stockroom.sexp.document import SexpDocument
from stockroom.verify.semdiff import assert_only_changed

_REAL_PCB = Path("/home/sadad/git/Hardware/tests/fixtures/rp2040_pico30.kicad_pcb")
_REAL_SCH = Path("/home/sadad/git/NETDECK/Master/LQFP100.kicad_sch")

# A compact but structurally-real KiCad-10 .kicad_pcb: a board gr_text on silk, a board gr_text on
# an INNER copper layer, a footprint whose reference designator + value are (property ...) nodes
# (the KiCad 8+/10 form, NOT fp_text reference/value), an fp_text user on silk, a metadata property
# with NO layer (must be skipped), and a PAD whose bare (size 1 1) must never be touched.
_PCB = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    '\t(gr_text "BRD"\n'
    "\t\t(at 5 5 0)\n"
    '\t\t(layer "F.SilkS")\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.5 1.5)\n\t\t\t\t(thickness 0.3)\n\t\t\t)\n\t\t)\n"
    "\t)\n"
    '\t(gr_text "CU"\n'
    "\t\t(at 6 6 0)\n"
    '\t\t(layer "In1.Cu")\n'
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t)\n\t\t)\n"
    "\t)\n"
    '\t(footprint "R_0402"\n'
    '\t\t(property "Reference" "R1"\n'
    "\t\t\t(at 0 0 0)\n"
    '\t\t\t(layer "F.SilkS")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t)\n"
    "\t\t)\n"
    '\t\t(property "Value" "10k"\n'
    "\t\t\t(at 0 1 0)\n"
    '\t\t\t(layer "F.Fab")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 0.8 0.8)\n\t\t\t\t)\n\t\t\t)\n"
    "\t\t)\n"
    '\t\t(property "Datasheet" "~"\n'
    "\t\t\t(at 0 0 0)\n"
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1 1)\n\t\t\t\t)\n\t\t\t)\n"
    "\t\t)\n"
    '\t\t(fp_text user "USR"\n'
    "\t\t\t(at 0 2 0)\n"
    '\t\t\t(layer "F.SilkS")\n'
    "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 0.9 0.9)\n\t\t\t\t)\n\t\t\t)\n"
    "\t\t)\n"
    '\t\t(pad "1" smd roundrect\n\t\t\t(at 0 0)\n\t\t\t(size 1 1)\n\t\t)\n'
    "\t)\n"
    ")\n"
)

# A compact .kicad_sch: a lib_symbols cache that embeds a symbol graphic (text) which must NEVER
# be resized, a top-level graphic text, and a top-level label. Placed content is a direct child
# of the root; the library cache is a sibling container.
_SCH = (
    "(kicad_sch\n"
    "\t(version 20260306)\n"
    "\t(lib_symbols\n"
    '\t\t(symbol "Device:R"\n'
    '\t\t\t(text "SYMBOL-CACHE"\n'
    "\t\t\t\t(at 0 0 0)\n"
    "\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)\n"
    "\t\t\t)\n"
    "\t\t)\n"
    "\t)\n"
    '\t(text "SHEET NOTE"\n'
    "\t\t(at 10 10 0)\n"
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.54 2.54)\n\t\t\t)\n\t\t)\n"
    "\t)\n"
    '\t(label "NET1"\n'
    "\t\t(at 20 20 0)\n"
    "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n"
    "\t)\n"
    ")\n"
)


# --- PCB ----------------------------------------------------------------------

def test_conform_pcb_silk_sets_square_size_minimal_diff():
    doc = SexpDocument.parse(_PCB)
    counts = conform.conform_pcb(doc, {"silk": {"size": 2.0, "thickness": None}})
    out = doc.serialize()
    # the three silk text objects (board gr_text + the Reference-designator property + fp_text
    # user) resized to a square size; the reference designator (a property, not fp_text) counts.
    assert counts["silk"] == 3
    assert out.count("(size 2 2)") == 3
    ref = out.index('(property "Reference" "R1"')
    assert "(size 2 2)" in out[ref:ref + 300]  # the reference designator property was resized
    # the fab-layer value, the inner-copper text, and the pad size (1 1) were NOT touched
    assert "(size 0.8 0.8)" in out
    assert "\t\t\t(size 1 1)\n\t\t)" in out  # the pad's bare (size 1 1) survives verbatim
    assert_only_changed(_PCB, out, allowed_changes=6)  # 3 objects x 2 size atoms


def test_conform_pcb_property_without_a_layer_is_skipped():
    # a metadata property (no (layer ...)) is board data, not on-board text; a conform never
    # touches it even though it carries a font.
    doc = SexpDocument.parse(_PCB)
    conform.conform_pcb(doc, {"silk": {"size": 2.0}, "fab": {"size": 2.0}})
    out = doc.serialize()
    ds = out.index('(property "Datasheet" "~"')
    assert "(size 1 1)" in out[ds:ds + 300]  # the layerless Datasheet property is unchanged


def test_conform_pcb_copper_reaches_an_inner_layer():
    doc = SexpDocument.parse(_PCB)
    counts = conform.conform_pcb(doc, {"copper": {"size": 0.5, "thickness": None}})
    out = doc.serialize()
    assert counts["copper"] == 1  # the In1.Cu gr_text
    cu = out.index('(gr_text "CU"')
    assert "(size 0.5 0.5)" in out[cu:cu + 300]


def test_conform_pcb_thickness_updates_only_existing_thickness_atoms():
    doc = SexpDocument.parse(_PCB)
    # the gr_text + Reference property fonts carry a thickness atom; the fp_text user font has
    # none -> it is not given one.
    counts = conform.conform_pcb(doc, {"silk": {"size": None, "thickness": 0.25}})
    out = doc.serialize()
    assert counts["silk"] == 2  # only the two silk fonts that already carry a thickness atom
    assert out.count("(thickness 0.25)") == 2
    # the board-general (thickness 1.6) is a physical thickness, NEVER touched by a font conform
    assert "(thickness 1.6)" in out


def test_conform_pcb_fab_only_touches_fab_layer():
    doc = SexpDocument.parse(_PCB)
    counts = conform.conform_pcb(doc, {"fab": {"size": 0.5, "thickness": None}})
    out = doc.serialize()
    assert counts["fab"] == 1  # the Value property on F.Fab
    assert "(size 0.5 0.5)" in out
    assert out.count("(size 1.5 1.5)") == 1  # the silk gr_text untouched
    assert_only_changed(_PCB, out, allowed_changes=2)


def test_conform_pcb_is_idempotent_second_pass_is_byte_identical():
    doc = SexpDocument.parse(_PCB)
    conform.conform_pcb(doc, {"silk": {"size": 2.0, "thickness": 0.25}})
    once = doc.serialize()
    doc2 = SexpDocument.parse(once)
    counts = conform.conform_pcb(doc2, {"silk": {"size": 2.0, "thickness": 0.25}})
    assert sum(counts.values()) == 0
    assert doc2.serialize() == once  # a re-conform to the same target changes nothing


# --- SCH ----------------------------------------------------------------------

def test_conform_sch_text_and_labels_but_never_lib_symbols_cache():
    doc = SexpDocument.parse(_SCH)
    counts = conform.conform_sch(doc, {"text": {"size": 3.0, "thickness": None},
                                       "labels": {"size": 1.0, "thickness": None}})
    out = doc.serialize()
    assert counts["text"] == 1
    assert counts["labels"] == 1
    assert "(size 3 3)" in out  # top-level sheet text resized
    assert "(size 1 1)" in out  # top-level label resized
    # the lib_symbols-embedded symbol graphic text is NEVER resized (it belongs to the library)
    assert "SYMBOL-CACHE" in out
    assert "(size 1.27 1.27)" in out  # the cache font is exactly as it was
    assert_only_changed(_SCH, out, allowed_changes=4)


def test_conform_sch_never_touches_symbol_instance_fields():
    # a placed symbol's reference/value are (property ...) fields nested inside the (symbol ...)
    # instance; they are a SEPARATE KiCad category (symbol fields, edited apart from schematic
    # text/graphics) and are intentionally out of scope. The direct-child walk never descends in.
    sch = (
        "(kicad_sch\n"
        '\t(symbol\n\t\t(lib_id "Device:R")\n'
        '\t\t(property "Reference" "R1"\n\t\t\t(at 0 0 0)\n'
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n"
        '\t(text "NOTE"\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.54 2.54)\n\t\t\t)\n\t\t)\n\t)\n'
        ")\n"
    )
    doc = SexpDocument.parse(sch)
    counts = conform.conform_sch(doc, {"text": {"size": 5.0, "thickness": None}})
    out = doc.serialize()
    assert counts["text"] == 1
    assert "(size 5 5)" in out  # the top-level sheet text was resized
    ref = out.index('(property "Reference" "R1"')
    assert "(size 1.27 1.27)" in out[ref:ref + 200]  # the symbol field is left untouched


def test_conform_sch_global_and_hierarchical_labels_are_covered():
    sch = (
        "(kicad_sch\n"
        '\t(global_label "G"\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t)\n'
        '\t(hierarchical_label "H"\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t)\n\t)\n'
        ")\n"
    )
    doc = SexpDocument.parse(sch)
    counts = conform.conform_sch(doc, {"labels": {"size": 2.0, "thickness": None}})
    assert counts["labels"] == 2
    assert doc.serialize().count("(size 2 2)") == 2


# --- router + real fixtures ---------------------------------------------------

def test_conform_document_routes_by_root_name():
    pcb = SexpDocument.parse(_PCB)
    c1 = conform.conform_document(pcb, {"silk": {"size": 2.0, "thickness": None}}, {})
    assert c1["silk"] == 3
    sch = SexpDocument.parse(_SCH)
    c2 = conform.conform_document(sch, {}, {"text": {"size": 3.0, "thickness": None}})
    assert c2["text"] == 1


@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real PCB fixture absent")
def test_conform_real_pcb_silk_is_minimal_and_leaves_board_thickness():
    original = _REAL_PCB.read_text(encoding="utf-8")
    doc = SexpDocument.parse(original)
    counts = conform.conform_pcb(doc, {"silk": {"size": 1.0, "thickness": None}})
    out = doc.serialize()
    assert counts["silk"] > 0  # a real board has silk text
    # each changed object contributes at most 2 size atoms; nothing structural is lost
    assert_only_changed(original, out, allowed_changes=counts["silk"] * 2)
    assert "(thickness 1.5)" in out  # the board's physical thickness is untouched


@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real PCB fixture absent")
def test_conform_real_pcb_conforms_footprint_reference_and_value_properties():
    # The review's confirmed bug: on KiCad 8+/10 boards reference designators + values live in
    # (property ...) nodes (with their own layer + font), NOT (fp_text reference/value). A silk
    # conform must resize the reference designators; a fab conform must resize the values.
    original = _REAL_PCB.read_text(encoding="utf-8")
    doc = SexpDocument.parse(original)
    counts = conform.conform_pcb(doc, {"silk": {"size": 3.0, "thickness": None},
                                       "fab": {"size": 4.0, "thickness": None}})
    out = doc.serialize()
    # a real reference-designator property on F.SilkS is resized square to the silk target
    ref = out.index('(property "Reference" "C1"')
    assert "(size 3 3)" in out[ref:ref + 400]
    # a real value property on F.Fab is resized to the fab target
    assert "(size 4 4)" in out
    # the board carries dozens of silk reference designators, all now counted (was ~0 before)
    assert counts["silk"] > 40 and counts["fab"] > 40
    assert_only_changed(original, out, allowed_changes=(counts["silk"] + counts["fab"]) * 2)


@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real PCB fixture absent")
def test_conform_real_pcb_copper_reaches_inner_layers():
    # A copper conform must reach board text on inner copper layers (In1.Cu/In2.Cu on a
    # multilayer board), not only the outer F.Cu/B.Cu.
    original = _REAL_PCB.read_text(encoding="utf-8")
    doc = SexpDocument.parse(original)
    counts = conform.conform_pcb(doc, {"copper": {"size": 3.0, "thickness": None}})
    # the board carries text on In1.Cu + In2.Cu (2 inner) plus 3 on outer F/B.Cu; a copper
    # conform must reach all 5, not only the outer 3.
    assert counts["copper"] >= 5


@pytest.mark.skipif(not _REAL_SCH.exists(), reason="real SCH fixture absent")
def test_conform_real_sch_labels_are_minimal():
    original = _REAL_SCH.read_text(encoding="utf-8")
    doc = SexpDocument.parse(original)
    counts = conform.conform_sch(doc, {"labels": {"size": 1.5, "thickness": None}})
    out = doc.serialize()
    assert counts["labels"] > 0
    assert_only_changed(original, out, allowed_changes=counts["labels"] * 2)
