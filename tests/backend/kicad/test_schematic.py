from stockroom.kicad.schematic import Schematic
from stockroom.verify.semdiff import assert_only_changed


def test_enumerates_instances(fixtures_dir):
    sch = Schematic.load(fixtures_dir / "minimal.kicad_sch")
    refs = sorted(i.reference for i in sch.instances)
    assert refs == ["C1", "R1"]
    r1 = sch.instance_by_reference("R1")
    assert r1.lib_id == "Device:R"
    assert r1.value == "10k"
    assert r1.get_property("Footprint") == "Resistor_SMD:R_0603"


def test_rewrites_only_target_instance(tmp_fixture):
    sch = Schematic.load(tmp_fixture("minimal.kicad_sch"))
    r1 = sch.instance_by_reference("R1")
    r1.set_lib_id("SR-Resistors:R_0603")
    r1.set_property("MPN", "RC0603FR-0710KL")
    assert r1.lib_id == "SR-Resistors:R_0603"
    assert r1.get_property("MPN") == "RC0603FR-0710KL"
    # C1 must be untouched
    assert sch.instance_by_reference("C1").lib_id == "Device:C"


def test_lib_id_edit_is_minimal(tmp_fixture):
    sch = Schematic.load(tmp_fixture("minimal.kicad_sch"))
    original = sch.serialize()
    sch.instance_by_reference("R1").set_lib_id("SR-Resistors:R_0603")
    assert_only_changed(original, sch.serialize(), allowed_changes=1)
