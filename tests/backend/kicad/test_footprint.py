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
