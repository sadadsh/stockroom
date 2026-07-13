from stockroom.kicad.footprint import Footprint
from stockroom.verify.semdiff import assert_only_changed, semantic_diff


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
