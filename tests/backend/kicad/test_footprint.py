from stockroom.kicad.footprint import Footprint
from stockroom.verify.semdiff import assert_only_changed, semantic_diff


def test_reads_footprint_name(fixtures_dir):
    fp = Footprint.load(fixtures_dir / "minimal.kicad_mod")
    assert fp.name == "R_0603"


def test_reads_model_path(fixtures_dir):
    fp = Footprint.load(fixtures_dir / "minimal.kicad_mod")
    assert fp.model_path.endswith("R_0603.step")


def test_rewrites_existing_model_path(tmp_fixture):
    fp = Footprint.load(tmp_fixture("minimal.kicad_mod"))
    original = fp.serialize()
    fp.set_model_path("${SR_LIB}/models/Resistors/R_0603.step")
    assert fp.model_path == "${SR_LIB}/models/Resistors/R_0603.step"
    assert_only_changed(original, fp.serialize(), allowed_changes=1)


def test_inserts_model_when_absent(tmp_path):
    text = '(footprint "X"\n\t(version 20260206)\n\t(layer "F.Cu")\n)'.replace("\n", "\r\n")
    p = tmp_path / "nomodel.kicad_mod"
    p.write_text(text, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    assert fp.model_path is None
    original = fp.serialize()
    fp.set_model_path("${SR_LIB}/models/X.step")
    assert fp.model_path == "${SR_LIB}/models/X.step"
    structural = [
        d for d in semantic_diff(original, fp.serialize()) if d.startswith(("LOST", "CHANGED", "TYPE"))
    ]
    assert structural == []


def test_set_name(tmp_fixture):
    fp = Footprint.load(tmp_fixture("minimal.kicad_mod"))
    original = fp.serialize()
    fp.set_name("R_0402")
    assert fp.name == "R_0402"
    assert_only_changed(original, fp.serialize(), allowed_changes=1)


_FP_WITH_TEXT = (
    '(footprint "R_0603"\n'
    '\t(layer "F.Cu")\n'
    '\t(property "Reference" "REF**"\n'
    '\t\t(at 0 -1 0)\n'
    '\t\t(layer "F.SilkS")\n'
    '\t\t(effects (font (size 1 1)))\n'
    '\t)\n'
    '\t(property "Value" "R_0603"\n'
    '\t\t(at 0 1 0)\n'
    '\t\t(layer "F.Fab")\n'
    '\t\t(effects (font (size 1 1)))\n'
    '\t)\n'
    '\t(pad "1" smd roundrect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu"))\n'
    ')\n'
)


def test_hide_field_marks_a_visible_property_hidden(tmp_path):
    p = tmp_path / "R.kicad_mod"
    p.write_text(_FP_WITH_TEXT, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    assert fp.hide_field("Reference") is True
    assert fp.hide_field("Value") is True
    fp.save(p)
    text = p.read_text()
    # both properties now carry (hide yes); the pad art is untouched
    rstart = text.index('(property "Reference"')
    assert "(hide yes)" in text[rstart:rstart + 200]
    vstart = text.index('(property "Value"')
    assert "(hide yes)" in text[vstart:vstart + 200]
    assert '(pad "1"' in text


def test_hide_field_is_idempotent_and_reports_no_change(tmp_path):
    p = tmp_path / "R.kicad_mod"
    p.write_text(_FP_WITH_TEXT, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    fp.hide_field("Reference")
    assert fp.hide_field("Reference") is False  # already hidden
    assert fp.hide_field("Nonexistent") is False


def test_hide_field_never_touches_the_pads(tmp_path):
    p = tmp_path / "R.kicad_mod"
    p.write_text(_FP_WITH_TEXT, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    fp.hide_field("Reference")
    out = fp.serialize()
    # the pad line (and everything else) is byte-preserved; only a (hide yes) node
    # was inserted into the Reference property, which semdiff sees as an ADD
    assert '\t(pad "1" smd roundrect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu"))\n' in out
    diffs = semantic_diff(_FP_WITH_TEXT, out)
    assert all(not d.startswith(("LOST", "CHANGED", "TYPE")) for d in diffs), diffs


_FP_WITH_FAB_REF = (
    '(footprint "R_0603"\n'
    '\t(layer "F.Cu")\n'
    '\t(property "Reference" "REF**"\n'
    '\t\t(at 0 -1 0)\n'
    '\t\t(layer "F.SilkS")\n'
    '\t)\n'
    '\t(fp_text user "${REFERENCE}"\n'
    '\t\t(at 0 0 0)\n'
    '\t\t(layer "F.Fab")\n'
    '\t\t(effects (font (size 0.5 0.5)))\n'
    '\t)\n'
    '\t(pad "1" smd roundrect (at -0.8 0) (size 0.9 0.95) (layers "F.Cu"))\n'
    ')\n'
)


def test_hide_reference_texts_hides_the_fab_designator(tmp_path):
    p = tmp_path / "R.kicad_mod"
    p.write_text(_FP_WITH_FAB_REF, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    assert fp.hide_reference_texts() is True
    fp.save(p)
    text = p.read_text()
    tstart = text.index("fp_text")
    assert "(hide yes)" in text[tstart:tstart + 200]
    assert '(pad "1"' in text  # pad art untouched


def test_hide_reference_texts_is_idempotent(tmp_path):
    p = tmp_path / "R.kicad_mod"
    p.write_text(_FP_WITH_FAB_REF, encoding="utf-8", newline="")
    fp = Footprint.load(p)
    assert fp.hide_reference_texts() is True
    assert fp.hide_reference_texts() is False  # already hidden


class TestModelPlacement:
    """The footprint's `(model ...)` block carries the transform that places the mesh relative to the
    footprint origin - `(offset (xyz ...))`, `(scale (xyz ...))`, `(rotate (xyz ...))`. Stockroom
    WROTE an identity transform when attaching a model and never READ one back, so a vendor footprint
    whose model needs an offset or a rotation was rendered as if it sat at the origin unrotated.

    This is the primitive that footprint-on-board 3D needs: without the transform there is no way to
    know where the body actually sits, and the preview silently shows a wrong placement rather than
    failing. Units are KiCad's: offset in mm, rotate in degrees, scale unitless.
    """

    def _fp(self, tmp_path, model_block: str):
        src = (
            '(footprint "T"\n'
            '\t(layer "F.Cu")\n'
            f"\t{model_block}\n"
            ")\n"
        )
        p = tmp_path / "t.kicad_mod"
        p.write_text(src, encoding="utf-8")
        return Footprint.load(p)

    def test_reads_a_non_identity_placement(self, tmp_path):
        fp = self._fp(
            tmp_path,
            '(model "m.step" (offset (xyz 1.5 -2 0.25)) (scale (xyz 2 2 2)) (rotate (xyz 0 0 -90)))',
        )
        place = fp.model_placement
        assert place is not None
        assert place.offset == (1.5, -2.0, 0.25)
        assert place.scale == (2.0, 2.0, 2.0)
        assert place.rotate == (0.0, 0.0, -90.0)

    def test_identity_when_the_block_omits_them(self, tmp_path):
        # A hand-written or older footprint may carry only the path. KiCad treats the missing
        # parts as identity, so reporting None here would make the caller invent its own default.
        fp = self._fp(tmp_path, '(model "m.step")')
        place = fp.model_placement
        assert place is not None
        assert place.offset == (0.0, 0.0, 0.0)
        assert place.scale == (1.0, 1.0, 1.0)
        assert place.rotate == (0.0, 0.0, 0.0)

    def test_none_when_there_is_no_model_at_all(self, tmp_path):
        src = '(footprint "T"\n\t(layer "F.Cu")\n)\n'
        p = tmp_path / "t.kicad_mod"
        p.write_text(src, encoding="utf-8")
        assert Footprint.load(p).model_placement is None

    def test_reading_the_placement_does_not_rewrite_the_file(self, tmp_path):
        # Layer 0 is byte-preserving; a READ must never dirty the document.
        block = '(model "m.step" (offset (xyz 1 2 3)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 90)))'
        fp = self._fp(tmp_path, block)
        before = (tmp_path / "t.kicad_mod").read_bytes()
        _ = fp.model_placement
        assert (tmp_path / "t.kicad_mod").read_bytes() == before


class TestPads:
    """The land pattern, as geometry a 3D view can draw.

    Owner, 2026-07-25: "cant see just the footprint in 3d option either. that way with the footprint
    showing u can see if the 3d model is oriented properly." That is the POINT of this - a body
    floating alone cannot be checked against anything, but a body sitting on its own pads either
    lines up or visibly does not.

    KiCad units: `at` is mm from the footprint origin with an optional rotation in DEGREES, `size`
    is mm. Y is reported EXACTLY as KiCad stores it (screen coordinates, +Y down); converting here
    would hide which frame the caller is in, the same reasoning as ModelPlacement.
    """

    def _fp(self, tmp_path, body: str):
        p = tmp_path / "t.kicad_mod"
        p.write_text(f'(footprint "T"\n\t(layer "F.Cu")\n{body}\n)\n', encoding="utf-8")
        return Footprint.load(p)

    def test_reads_position_size_shape_and_rotation(self, tmp_path):
        fp = self._fp(
            tmp_path,
            '\t(pad "1" smd roundrect (at -0.675 -1.5) (size 0.75 0.2) (layers "F.Cu"))\n'
            '\t(pad "2" smd rect (at 0.675 1.5 90) (size 0.8 0.3) (layers "F.Cu"))\n',
        )
        pads = fp.pads
        assert len(pads) == 2
        assert pads[0].number == "1"
        assert pads[0].at == (-0.675, -1.5)
        assert pads[0].size == (0.75, 0.2)
        assert pads[0].shape == "roundrect"
        assert pads[0].rotation == 0.0
        assert pads[1].rotation == 90.0

    def test_ignores_a_size_that_belongs_to_something_else(self, tmp_path):
        # A footprint carries (size ...) inside text properties too. Reading the first `size` in
        # the FILE rather than the one inside each pad would silently mis-size every pad.
        fp = self._fp(
            tmp_path,
            '\t(property "Reference" "REF**" (at 0 -2.7 0) (effects (font (size 1 1))))\n'
            '\t(pad "1" smd roundrect (at -0.675 -1.5) (size 0.75 0.2) (layers "F.Cu"))\n',
        )
        assert len(fp.pads) == 1
        assert fp.pads[0].size == (0.75, 0.2)

    def test_is_empty_for_a_footprint_with_no_pads(self, tmp_path):
        assert self._fp(tmp_path, '\t(fp_line (start 0 0) (end 1 1))').pads == []

    def test_reading_pads_does_not_rewrite_the_file(self, tmp_path):
        fp = self._fp(
            tmp_path, '\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))'
        )
        before = (tmp_path / "t.kicad_mod").read_bytes()
        _ = fp.pads
        assert (tmp_path / "t.kicad_mod").read_bytes() == before


class TestGraphics:
    """Silkscreen and courtyard lines - the rest of what a footprint DRAWS.

    Owner, 2026-07-25: "the footprint doesnt show everything". Pads alone are not the land pattern;
    the silkscreen outline and the pin-1 marker are how anyone recognises the part on a board, and
    the courtyard is the keep-out it must be checked against.
    """

    def _fp(self, tmp_path, body: str):
        p = tmp_path / "t.kicad_mod"
        p.write_text(f'(footprint "T"\n\t(layer "F.Cu")\n{body}\n)\n', encoding="utf-8")
        return Footprint.load(p)

    def test_reads_lines_with_their_layer(self, tmp_path):
        fp = self._fp(
            tmp_path,
            '\t(fp_line (start -1 -2) (end 1 -2) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))\n'
            '\t(fp_line (start -2 -3) (end 2 -3) (stroke (width 0.05) (type solid)) (layer "F.CrtYd"))\n',
        )
        g = fp.graphics
        assert len(g) == 2
        assert g[0].start == (-1.0, -2.0)
        assert g[0].end == (1.0, -2.0)
        assert g[0].layer == "F.SilkS"
        assert g[0].width == 0.12
        assert g[1].layer == "F.CrtYd"

    def test_ignores_the_pads_own_geometry(self, tmp_path):
        fp = self._fp(
            tmp_path, '\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))'
        )
        assert fp.graphics == []

    def test_reading_graphics_does_not_rewrite_the_file(self, tmp_path):
        fp = self._fp(
            tmp_path,
            '\t(fp_line (start 0 0) (end 1 1) (stroke (width 0.1) (type solid)) (layer "F.SilkS"))',
        )
        before = (tmp_path / "t.kicad_mod").read_bytes()
        _ = fp.graphics
        assert (tmp_path / "t.kicad_mod").read_bytes() == before
