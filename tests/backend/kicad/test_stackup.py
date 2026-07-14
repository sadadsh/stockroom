"""M7f-C stackup / fab-preset writer: byte-preserving `(setup (stackup ...))` read + per-field edit
+ whole-block preset generate, on the SexpDocument span-splice editor.

The grammar is verified against the REAL KiCad-10 boards (NETDECK `SH Files`/`CG Files`, both
generator_version 10.0): each `(layer ...)` is MULTI-LINE / expanded, dielectrics carry
type/thickness/material/epsilon_r/loss_tangent, copper layers carry thickness, and the block ends
with `(copper_finish "...")` + `(dielectric_constraints yes|no)`. The inline fixture reproduces that
exact structure so CI (where the external NETDECK repo is absent) still exercises every path."""

from pathlib import Path

import pytest

from stockroom.kicad import stackup
from stockroom.sexp.document import SexpDocument
from stockroom.verify.semdiff import assert_only_changed

# A real NETDECK KiCad-10 4-layer FR4 board (external repo -> skipif in CI).
_REAL_PCB = Path("/home/sadad/git/NETDECK/Development/SH Files/SH Files.kicad_pcb")

# The exact real KiCad-10 stackup block text (verified vs the NETDECK boards), for byte-fidelity
# assertions. Tabs, multi-line layers, atom order type/thickness/material/epsilon_r/loss_tangent.
_REAL_STACKUP = (
    "(stackup\n"
    '\t\t\t(layer "F.SilkS"\n\t\t\t\t(type "Top Silk Screen")\n\t\t\t)\n'
    '\t\t\t(layer "F.Paste"\n\t\t\t\t(type "Top Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "F.Mask"\n\t\t\t\t(type "Top Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "F.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 1"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In1.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 2"\n\t\t\t\t(type "core")\n\t\t\t\t(thickness 1.24)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "In2.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 3"\n\t\t\t\t(type "prepreg")\n\t\t\t\t(thickness 0.1)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "B.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "B.Mask"\n\t\t\t\t(type "Bottom Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "B.Paste"\n\t\t\t\t(type "Bottom Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "B.SilkS"\n\t\t\t\t(type "Bottom Silk Screen")\n\t\t\t)\n'
    '\t\t\t(copper_finish "None")\n'
    "\t\t\t(dielectric_constraints no)\n"
    "\t\t)"
)

# A full inline KiCad-10 .kicad_pcb wrapping that stackup. The (layers) block lists copper in KiCad
# INDEX order (F.Cu 0, B.Cu 2, In1.Cu 4, In2.Cu 6) which is NOT the physical top->bottom order, so a
# correct copper_layer_names() must re-sort to F.Cu, In1.Cu, In2.Cu, B.Cu.
_PCB = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    '\t(generator "pcbnew")\n'
    '\t(generator_version "10.0")\n'
    "\t(general\n\t\t(thickness 1.51)\n\t)\n"
    "\t(layers\n"
    '\t\t(0 "F.Cu" signal)\n'
    '\t\t(2 "B.Cu" signal)\n'
    '\t\t(4 "In1.Cu" signal)\n'
    '\t\t(6 "In2.Cu" signal)\n'
    '\t\t(1 "F.Mask" user)\n'
    '\t\t(3 "B.Mask" user)\n'
    "\t)\n"
    "\t(setup\n"
    "\t\t" + _REAL_STACKUP + "\n"
    "\t\t(pad_to_mask_clearance 0.05)\n"
    "\t)\n"
    ")\n"
)

# A 2-layer board: (layers) has only F.Cu/B.Cu, and its stackup has a single dielectric.
_PCB_2LAYER = (
    "(kicad_pcb\n"
    "\t(version 20260206)\n"
    "\t(general\n\t\t(thickness 1.6)\n\t)\n"
    "\t(layers\n"
    '\t\t(0 "F.Cu" signal)\n'
    '\t\t(2 "B.Cu" signal)\n'
    "\t)\n"
    "\t(setup\n"
    "\t\t(stackup\n"
    '\t\t\t(layer "F.SilkS"\n\t\t\t\t(type "Top Silk Screen")\n\t\t\t)\n'
    '\t\t\t(layer "F.Paste"\n\t\t\t\t(type "Top Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "F.Mask"\n\t\t\t\t(type "Top Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "F.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "dielectric 1"\n\t\t\t\t(type "core")\n\t\t\t\t(thickness 1.51)\n'
    '\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n\t\t\t)\n'
    '\t\t\t(layer "B.Cu"\n\t\t\t\t(type "copper")\n\t\t\t\t(thickness 0.035)\n\t\t\t)\n'
    '\t\t\t(layer "B.Mask"\n\t\t\t\t(type "Bottom Solder Mask")\n\t\t\t\t(thickness 0.01)\n\t\t\t)\n'
    '\t\t\t(layer "B.Paste"\n\t\t\t\t(type "Bottom Solder Paste")\n\t\t\t)\n'
    '\t\t\t(layer "B.SilkS"\n\t\t\t\t(type "Bottom Silk Screen")\n\t\t\t)\n'
    '\t\t\t(copper_finish "None")\n'
    "\t\t\t(dielectric_constraints no)\n"
    "\t\t)\n"
    "\t)\n"
    ")\n"
)


# --- copper_layer_names -------------------------------------------------------

def test_copper_layer_names_physical_order_not_index_order():
    doc = SexpDocument.parse(_PCB)
    # (layers) lists them F.Cu, B.Cu, In1.Cu, In2.Cu (index order); physical order is
    # F.Cu -> inners ascending -> B.Cu.
    assert stackup.copper_layer_names(doc) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def test_copper_layer_names_two_layer():
    doc = SexpDocument.parse(_PCB_2LAYER)
    assert stackup.copper_layer_names(doc) == ["F.Cu", "B.Cu"]


def test_copper_layer_names_no_layers_block_is_empty():
    doc = SexpDocument.parse("(kicad_pcb\n\t(version 1)\n)\n")
    assert stackup.copper_layer_names(doc) == []


# --- read_stackup -------------------------------------------------------------

def test_read_stackup_structured_four_layer():
    doc = SexpDocument.parse(_PCB)
    st = stackup.read_stackup(doc)
    assert st is not None
    assert st["copper_finish"] == "None"
    assert st["dielectric_constraints"] is False
    layers = st["layers"]
    # 4 framing top (silk/paste/mask) is actually 3 top + 3 bottom + 4 copper + 3 dielectric = 13.
    assert len(layers) == 13
    names = [lyr["name"] for lyr in layers]
    assert names[:4] == ["F.SilkS", "F.Paste", "F.Mask", "F.Cu"]
    assert "In1.Cu" in names and "In2.Cu" in names
    fcu = next(lyr for lyr in layers if lyr["name"] == "F.Cu")
    assert fcu["type"] == "copper" and fcu["thickness"] == 0.035
    d1 = next(lyr for lyr in layers if lyr["name"] == "dielectric 1")
    assert d1["type"] == "prepreg" and d1["thickness"] == 0.1
    assert d1["material"] == "FR4" and d1["epsilon_r"] == 4.5 and d1["loss_tangent"] == 0.02
    fmask = next(lyr for lyr in layers if lyr["name"] == "F.Mask")
    assert fmask["type"] == "Top Solder Mask" and fmask["thickness"] == 0.01
    assert "color" not in fmask  # a native board with no mask color has no (color) atom
    fsilk = next(lyr for lyr in layers if lyr["name"] == "F.SilkS")
    assert "thickness" not in fsilk  # silk/paste carry no thickness atom


def test_read_stackup_none_when_absent():
    doc = SexpDocument.parse("(kicad_pcb\n\t(setup\n\t\t(pad_to_mask_clearance 0.05)\n\t)\n)\n")
    assert stackup.read_stackup(doc) is None


# --- render_stackup_block (byte fidelity, the load-bearing guarantee) ----------

def test_render_block_reproduces_real_grammar_byte_for_byte():
    # read the real block, render it straight back -> byte-identical. This is the fidelity
    # guarantee the preset-apply path inherits (it uses the same renderer).
    doc = SexpDocument.parse(_PCB)
    st = stackup.read_stackup(doc)
    rendered = stackup.render_stackup_block(
        st["layers"], copper_finish=st["copper_finish"],
        dielectric_constraints=st["dielectric_constraints"],
    )
    assert rendered == _REAL_STACKUP


def test_render_block_emits_color_when_present():
    layers = [
        {"name": "F.Mask", "type": "Top Solder Mask", "thickness": 0.01, "color": "Purple"},
    ]
    out = stackup.render_stackup_block(layers, copper_finish="ENIG", dielectric_constraints=False)
    assert '(color "Purple")' in out
    assert '(copper_finish "ENIG")' in out
    # color precedes thickness inside a mask layer
    assert out.index('(color "Purple")') < out.index("(thickness 0.01)")


# --- build_preset_layers + render (preset apply) ------------------------------

def test_build_preset_layers_uses_board_copper_names_and_numbers_dielectrics():
    physical = [
        {"kind": "copper", "thickness": 0.0432},
        {"kind": "dielectric", "type": "prepreg", "thickness": 0.2, "material": "FR408HR",
         "epsilon_r": 3.6, "loss_tangent": 0.0091},
        {"kind": "copper", "thickness": 0.0175},
        {"kind": "dielectric", "type": "core", "thickness": 0.99, "material": "FR408HR",
         "epsilon_r": 3.6, "loss_tangent": 0.0091},
        {"kind": "copper", "thickness": 0.0175},
        {"kind": "dielectric", "type": "prepreg", "thickness": 0.2, "material": "FR408HR",
         "epsilon_r": 3.6, "loss_tangent": 0.0091},
        {"kind": "copper", "thickness": 0.0432},
    ]
    layers = stackup.build_preset_layers(
        ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], physical, mask_color="Purple")
    names = [lyr["name"] for lyr in layers]
    # framing + the board's own copper names + numbered dielectrics
    assert names == ["F.SilkS", "F.Paste", "F.Mask", "F.Cu", "dielectric 1", "In1.Cu",
                     "dielectric 2", "In2.Cu", "dielectric 3", "B.Cu", "B.Mask", "B.Paste", "B.SilkS"]
    fcu = next(lyr for lyr in layers if lyr["name"] == "F.Cu")
    assert fcu["type"] == "copper" and fcu["thickness"] == 0.0432
    incu = next(lyr for lyr in layers if lyr["name"] == "In1.Cu")
    assert incu["thickness"] == 0.0175  # inner copper is thinner (0.5oz)
    d2 = next(lyr for lyr in layers if lyr["name"] == "dielectric 2")
    assert d2["type"] == "core" and d2["material"] == "FR408HR"
    fmask = next(lyr for lyr in layers if lyr["name"] == "F.Mask")
    assert fmask["color"] == "Purple"


def test_build_preset_layers_refuses_copper_count_mismatch():
    physical = [{"kind": "copper", "thickness": 0.035},
                {"kind": "dielectric", "type": "core", "thickness": 1.5, "material": "FR4",
                 "epsilon_r": 4.5, "loss_tangent": 0.02},
                {"kind": "copper", "thickness": 0.035}]
    # a 2-copper preset onto a 4-copper board -> refuse (the stackup must match the board layers)
    with pytest.raises(ValueError):
        stackup.build_preset_layers(["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], physical)


def test_preset_layers_render_2layer_wellformed():
    physical = [{"kind": "copper", "thickness": 0.035},
                {"kind": "dielectric", "type": "core", "thickness": 1.51, "material": "FR4",
                 "epsilon_r": 4.5, "loss_tangent": 0.02},
                {"kind": "copper", "thickness": 0.035}]
    layers = stackup.build_preset_layers(["F.Cu", "B.Cu"], physical)
    out = stackup.render_stackup_block(layers, copper_finish="None", dielectric_constraints=False)
    assert out.count('(type "copper")') == 2
    # F.SilkS/Paste/Mask + F.Cu + dielectric 1 + B.Cu + B.Mask/Paste/SilkS = 9 layers
    assert out.count("(layer ") == 9
    assert out.count("(") == out.count(")")


# --- apply_stackup_block (whole-block replace, scoped) ------------------------

def test_apply_stackup_block_replaces_only_the_stackup_span():
    # swap the whole stackup block for one that differs only in copper_finish, and prove nothing
    # outside the (stackup ...) span moves (the whole-block replace is still scoped).
    doc = SexpDocument.parse(_PCB)
    st = stackup.read_stackup(doc)
    block = stackup.render_stackup_block(
        st["layers"], copper_finish="ENIG", dielectric_constraints=st["dielectric_constraints"])
    changed = stackup.apply_stackup_block(doc, block)
    assert changed is True
    out = doc.serialize()
    # everything OUTSIDE the stackup block is byte-identical: the pad_to_mask_clearance sibling and
    # the general thickness both survive verbatim.
    assert "(pad_to_mask_clearance 0.05)" in out
    assert "(thickness 1.51)" in out
    assert '(copper_finish "ENIG")' in out
    assert '(copper_finish "None")' not in out
    # the (layers) block, version, generator are all untouched
    assert '(generator_version "10.0")' in out
    assert out.count("(stackup") == 1


def test_apply_stackup_block_is_byte_identical_when_reapplied():
    doc = SexpDocument.parse(_PCB)
    st = stackup.read_stackup(doc)
    block = stackup.render_stackup_block(
        st["layers"], copper_finish=st["copper_finish"],
        dielectric_constraints=st["dielectric_constraints"])
    stackup.apply_stackup_block(doc, block)
    out = doc.serialize()
    assert out == _PCB  # re-rendering the same stack changes nothing


def test_apply_stackup_block_inserts_as_first_setup_child_when_absent():
    src = "(kicad_pcb\n\t(setup\n\t\t(pad_to_mask_clearance 0.05)\n\t)\n)\n"
    doc = SexpDocument.parse(src)
    block = stackup.render_stackup_block(
        [{"name": "F.Cu", "type": "copper", "thickness": 0.035}],
        copper_finish="None", dielectric_constraints=False)
    changed = stackup.apply_stackup_block(doc, block)
    assert changed is True
    out = doc.serialize()
    assert "(stackup" in out
    assert "(pad_to_mask_clearance 0.05)" in out  # the existing setup child survives
    # inserted as the FIRST child of (setup ...) (KiCad's convention), before the existing sibling,
    # so KiCad does not reorder + churn it on the next save
    assert out.index("(stackup") < out.index("(pad_to_mask_clearance")
    SexpDocument.parse(out)  # the result is well-formed


# --- set_stackup_fields (per-field in-place, minimal diff) --------------------

def test_set_fields_copper_finish_and_constraints_in_place():
    doc = SexpDocument.parse(_PCB)
    n = stackup.set_stackup_fields(doc, copper_finish="ENIG", dielectric_constraints=True)
    out = doc.serialize()
    assert n == 2
    assert '(copper_finish "ENIG")' in out
    assert "(dielectric_constraints yes)" in out
    assert_only_changed(_PCB, out, allowed_changes=2)


def test_set_fields_per_dielectric_material_and_thickness():
    doc = SexpDocument.parse(_PCB)
    n = stackup.set_stackup_fields(doc, layers={
        "dielectric 2": {"thickness": 1.2, "material": "Rogers", "epsilon_r": 3.66,
                         "loss_tangent": 0.0037},
    })
    out = doc.serialize()
    assert n == 4  # thickness + material + epsilon_r + loss_tangent
    d2 = out.index('(layer "dielectric 2"')
    seg = out[d2:d2 + 220]
    assert "(thickness 1.2)" in seg and '(material "Rogers")' in seg
    assert "(epsilon_r 3.66)" in seg and "(loss_tangent 0.0037)" in seg
    assert_only_changed(_PCB, out, allowed_changes=4)


def test_set_fields_per_copper_thickness():
    doc = SexpDocument.parse(_PCB)
    n = stackup.set_stackup_fields(doc, layers={"In1.Cu": {"thickness": 0.0175}})
    out = doc.serialize()
    assert n == 1
    in1 = out.index('(layer "In1.Cu"')
    assert "(thickness 0.0175)" in out[in1:in1 + 120]
    assert_only_changed(_PCB, out, allowed_changes=1)


def test_set_fields_is_idempotent_noop_returns_zero():
    doc = SexpDocument.parse(_PCB)
    # set to the values already on disk -> no atom differs -> zero changes, byte-identical
    n = stackup.set_stackup_fields(doc, copper_finish="None", dielectric_constraints=False,
                                   layers={"F.Cu": {"thickness": 0.035}})
    assert n == 0
    assert doc.serialize() == _PCB


def test_set_fields_unknown_layer_is_ignored():
    doc = SexpDocument.parse(_PCB)
    n = stackup.set_stackup_fields(doc, layers={"NoSuch.Cu": {"thickness": 0.1}})
    assert n == 0
    assert doc.serialize() == _PCB


# --- real fixture (skipif in CI) ----------------------------------------------

@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real NETDECK PCB fixture absent")
def test_real_board_read_render_roundtrip_is_byte_identical():
    original = _REAL_PCB.read_text(encoding="utf-8")
    doc = SexpDocument.parse(original)
    st = stackup.read_stackup(doc)
    assert st is not None
    copper = [lyr for lyr in st["layers"] if lyr["type"] == "copper"]
    assert len(copper) == 4  # a real 4-layer board
    rendered = stackup.render_stackup_block(
        st["layers"], copper_finish=st["copper_finish"],
        dielectric_constraints=st["dielectric_constraints"])
    # the render must reproduce the real stackup block verbatim -> it is a substring of the file
    assert rendered.startswith("(stackup")
    assert rendered in original


def test_thickness_sum_counts_every_thickness_bearing_layer():
    doc = SexpDocument.parse(_PCB)
    st = stackup.read_stackup(doc)
    # 4 copper x 0.035 + (0.1 + 1.24 + 0.1) dielectric + 2 masks x 0.01 = 1.6
    assert stackup.stackup_thickness_sum(st["layers"]) == 1.6


@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real NETDECK PCB fixture absent")
def test_real_board_thickness_equals_stack_sum():
    # KiCad's invariant, verified against primary source: (general (thickness)) equals the sum of the
    # stackup's thickness-bearing layers. A preset apply relies on this to stay internally consistent.
    doc = SexpDocument.parse(_REAL_PCB.read_text(encoding="utf-8"))
    st = stackup.read_stackup(doc)
    general = doc.root.find("general")
    declared = float(general.find("thickness").children[1].value)
    assert stackup.stackup_thickness_sum(st["layers"]) == declared


@pytest.mark.skipif(not _REAL_PCB.exists(), reason="real NETDECK PCB fixture absent")
def test_real_board_copper_layer_names():
    doc = SexpDocument.parse(_REAL_PCB.read_text(encoding="utf-8"))
    assert stackup.copper_layer_names(doc) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


# --- via the Board facade (delegators) ----------------------------------------

def test_board_stackup_delegators(tmp_path):
    from stockroom.kicad.board import Board

    p = tmp_path / "b.kicad_pcb"
    p.write_text(_PCB, encoding="utf-8")
    board = Board.load(p)
    assert board.copper_layer_names() == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    st = board.stackup()
    assert st["copper_finish"] == "None"
    # a per-field edit through the facade, then thickness through the SAME board/doc/save
    n = board.set_stackup_fields(copper_finish="ENIG")
    assert n == 1
    board.set_thickness(1.55)
    board.save(p)
    out = p.read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in out
    assert "(thickness 1.55)" in out  # the (general thickness) edit landed alongside the stackup edit
    assert "(pad_to_mask_clearance 0.05)" in out


def test_board_apply_stackup_block_then_thickness_one_save(tmp_path):
    from stockroom.kicad.board import Board

    p = tmp_path / "b.kicad_pcb"
    p.write_text(_PCB, encoding="utf-8")
    board = Board.load(p)
    st = board.stackup()
    block = stackup.render_stackup_block(
        st["layers"], copper_finish="ENIG", dielectric_constraints=st["dielectric_constraints"])
    assert board.apply_stackup_block(block) is True
    board.set_thickness(1.6)
    board.save(p)
    out = p.read_text(encoding="utf-8")
    assert '(copper_finish "ENIG")' in out
    assert "(thickness 1.6)" in out
    assert out.count("(stackup") == 1
    assert '(generator_version "10.0")' in out  # nothing else disturbed
