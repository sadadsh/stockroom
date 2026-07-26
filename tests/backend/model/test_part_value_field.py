"""BOM-ready rebuild (SP1) Task 1: PartRecord.value field + Value in the mirror set."""
from stockroom.model.part import KICAD_MIRROR_FIELDS, PartRecord


def test_value_round_trips():
    r = PartRecord(id="x", display_name="n", category="Resistors", value="10k")
    assert r.value == "10k"
    r2 = PartRecord.loads(r.dumps())
    assert r2.value == "10k"


def test_value_defaults_empty():
    assert PartRecord(id="x", display_name="n", category="Resistors").value == ""


def test_value_in_kicad_mirror_fields():
    assert "Value" in KICAD_MIRROR_FIELDS
