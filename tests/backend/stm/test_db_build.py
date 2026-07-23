"""Task 1 tracer: text source -> stamped, loadable StmIndex.

Fixtures (tests/backend/fixtures/stm/, real CubeMX XML, cited in the phase CONTEXT):
  STM32F030RCTx.xml  - LQFP64, numeric positions
  STM32F048C6Ux.xml  - UFQFPN48, numeric positions (QFN)
  STM32F072RBIx.xml  - UFBGA64, alphanumeric positions A1..H8
  STM32F407V(E-G)Tx.xml - LQFP100, the rich mcu_spec/mcu_peripheral sample
"""

from pathlib import Path

import pytest

from stockroom.stm import db as db_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_build_populates_nine_table_schema_and_meta_stamp():
    idx = db_mod.StmIndex.build(FIXTURES)
    assert idx.mcu_count() == 4

    conn = idx._conn
    tables = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert tables >= {
        "meta",
        "source_artifact",
        "mcu",
        "mcu_spec",
        "mcu_peripheral",
        "mcu_package_pin",
        "pin_function",
        "pin_role",
        "package_geometry",
        "pin_alternate_function",  # Phase 2 (02-01): the AF0-15 mux join table
    }

    assert conn.execute("SELECT COUNT(*) FROM source_artifact").fetchone()[0] == 1

    meta = idx.meta()
    for key in (
        "classifier_rev",
        "geometry_rev",
        "source_sha256",
        "source_file_count",
        "source_path",
        "built_at",
        "all_families",
        "device_xml_count",
        "family_count",
    ):
        assert key in meta, f"missing meta key: {key}"
    assert meta["classifier_rev"] == str(db_mod.CLASSIFIER_REV)


def test_mcu_package_pin_populated_for_every_fixture_with_typed_positions():
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn

    # Every fixture MCU has a non-zero pin count.
    rows = conn.execute("SELECT id, ref_name, pin_count FROM mcu").fetchall()
    assert len(rows) == 4
    for r in rows:
        assert r["pin_count"] > 0, f"{r['ref_name']} parsed zero pins"

    # UFBGA64 (STM32F072RBIx) keeps all 64 alnum positions.
    bga_mcu = conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F072RBIx'"
    ).fetchone()
    assert bga_mcu is not None
    bga_pins = conn.execute(
        "SELECT position_kind, lqfp_side, bga_row, bga_col FROM mcu_package_pin "
        "WHERE mcu_id = ?",
        (bga_mcu["id"],),
    ).fetchall()
    assert len(bga_pins) == 64
    for p in bga_pins:
        assert p["position_kind"] == "alnum"
        assert p["lqfp_side"] is None
        assert p["bga_row"] is not None
        assert p["bga_col"] is not None

    # The numeric fixtures get position_kind='numeric' and a non-null lqfp_side.
    numeric_mcu = conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F030RCTx'"
    ).fetchone()
    numeric_pins = conn.execute(
        "SELECT position_kind, lqfp_side, bga_row, bga_col FROM mcu_package_pin "
        "WHERE mcu_id = ?",
        (numeric_mcu["id"],),
    ).fetchall()
    assert len(numeric_pins) > 0
    for p in numeric_pins:
        assert p["position_kind"] == "numeric"
        assert p["lqfp_side"] is not None
        assert p["bga_row"] is None
        assert p["bga_col"] is None


def test_load_round_trips_a_file_backed_build(tmp_path):
    db_path = tmp_path / "index.sqlite"
    built = db_mod.StmIndex.build(FIXTURES, db_path=db_path)
    built_count = built.mcu_count()
    built.close()

    assert db_path.exists()
    loaded = db_mod.StmIndex.load(db_path)
    assert loaded is not None
    assert loaded.mcu_count() == built_count
    loaded.close()


def test_load_returns_none_on_classifier_rev_mismatch(tmp_path, monkeypatch):
    db_path = tmp_path / "index.sqlite"
    db_mod.StmIndex.build(FIXTURES, db_path=db_path).close()

    monkeypatch.setattr(db_mod, "CLASSIFIER_REV", db_mod.CLASSIFIER_REV + 1)
    assert db_mod.StmIndex.load(db_path) is None


def test_load_returns_none_on_geometry_rev_mismatch(tmp_path, monkeypatch):
    db_path = tmp_path / "index.sqlite"
    db_mod.StmIndex.build(FIXTURES, db_path=db_path).close()

    monkeypatch.setattr(db_mod.geometry_mod, "GEOMETRY_REV", db_mod.geometry_mod.GEOMETRY_REV + 1)
    assert db_mod.StmIndex.load(db_path) is None


def test_load_returns_none_on_missing_file(tmp_path):
    assert db_mod.StmIndex.load(tmp_path / "nope.sqlite") is None


def test_load_returns_none_on_corrupt_file(tmp_path):
    db_path = tmp_path / "corrupt.sqlite"
    db_path.write_text("not a sqlite file at all", encoding="utf-8")
    assert db_mod.StmIndex.load(db_path) is None


def test_rebuild_with_unchanged_source_skips_reparse(tmp_path):
    db_path = tmp_path / "index.sqlite"
    first = db_mod.StmIndex.build(FIXTURES, db_path=db_path)
    first_stamp = first.meta()["built_at"]
    first.close()

    # Rebuilding against the SAME unchanged source short-circuits: the returned
    # index is the pre-existing one (same built_at stamp), not a fresh parse.
    second = db_mod.StmIndex.build(FIXTURES, db_path=db_path)
    assert second.meta()["built_at"] == first_stamp
    second.close()


def _copy_with_gpio_modes(src: Path, device_xml_name: str, modes_xml_name: str) -> None:
    """Copy a real Phase 1 device XML fixture into a fresh source dir ALONG
    WITH its matching real GPIO-<version>_Modes.xml (Phase 2's AF join now
    resolves every declared GPIO peripheral version, so a bare device-XML
    copy with no IP/ sibling would trip the 100%-join-resolution gate)."""
    (src / device_xml_name).write_bytes((FIXTURES / device_xml_name).read_bytes())
    ip_dir = src / "IP"
    ip_dir.mkdir(exist_ok=True)
    (ip_dir / modes_xml_name).write_bytes((FIXTURES / "IP" / modes_xml_name).read_bytes())


def test_changing_an_input_byte_changes_source_sha256(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _copy_with_gpio_modes(
        src, "STM32F030RCTx.xml", "GPIO-STM32F091_gpio_v1_0_Modes.xml"
    )
    sha_before = db_mod.StmIndex.build(src).meta()["source_sha256"]

    # append a byte of trailing whitespace (well-formed XML unaffected; the raw
    # source bytes, and therefore source_sha256, must still change)
    xml_path = src / "STM32F030RCTx.xml"
    xml_path.write_bytes(xml_path.read_bytes() + b"\n")
    sha_after = db_mod.StmIndex.build(src).meta()["source_sha256"]

    assert sha_before != sha_after


def test_rebuild_reparses_when_source_changes(tmp_path):
    db_path = tmp_path / "index.sqlite"
    src = tmp_path / "src"
    src.mkdir()
    _copy_with_gpio_modes(
        src, "STM32F030RCTx.xml", "GPIO-STM32F091_gpio_v1_0_Modes.xml"
    )
    first = db_mod.StmIndex.build(src, db_path=db_path)
    assert first.mcu_count() == 1
    first.close()

    _copy_with_gpio_modes(
        src, "STM32F048C6Ux.xml", "GPIO-STM32F042_gpio_v1_0_Modes.xml"
    )
    second = db_mod.StmIndex.build(src, db_path=db_path)
    assert second.mcu_count() == 2
    second.close()


_PINREMAP_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Mcu ClockTree="STM32F0" DBVersion="V3.0" Family="STM32F0" HasPowerPad="false" \
IOType="" Line="STM32F0x0" Package="SYNTH_PINREMAP_PKG" RefName="SYNTH_PINREMAP_Tx" \
xmlns="http://mcd.rou.st.com/modules.php?name=mcu">
    <Core>Arm Cortex-M0</Core>
    <Frequency>48</Frequency>
    <Flash>64</Flash>
    <Ram>8</Ram>
    <IONb>2</IONb>
    <Voltage Max="3.6" Min="2"/>
    <Pin Name="PA9" Position="30" Type="I/O">
        <Signal Name="USART1_TX" IOModes="Alternate"/>
    </Pin>
    <Pin Name="PA9_Remap" Position="30" Type="I/O" Variant="PINREMAP">
        <Signal Name="USART2_TX" IOModes="Alternate"/>
    </Pin>
</Mcu>
"""


def test_same_position_pinremap_identities_are_not_collapsed(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SYNTH_PINREMAP_Tx.xml").write_text(_PINREMAP_XML, encoding="utf-8")

    idx = db_mod.StmIndex.build(src)
    conn = idx._conn
    rows = conn.execute(
        "SELECT physical_pin_number, raw_pin_name FROM mcu_package_pin "
        "WHERE physical_pin_number = '30'"
    ).fetchall()
    assert len(rows) == 2
    raw_names = {r["raw_pin_name"] for r in rows}
    assert raw_names == {"PA9", "PA9_Remap"}


def test_is_analog_ignores_the_generic_gpio_pseudo_signals_analog_mode():
    """Classifier rev 2 regression lock: CubeMX lists "Analog" (the high-impedance
    power state) in the generic GPIO pseudo-signal's io_modes for essentially every
    I/O pin - that must NOT make the pin analog (it painted 82 of an F407's 100
    pins analog). Real analog evidence still does."""
    gpio_only = db_mod.Pin(
        position="1", name="PD5", type="I/O",
        signals=[
            db_mod.Signal(name="USART2_TX"),
            db_mod.Signal(name="GPIO", io_modes="Input,Output,Analog,EVENTOUT,EXTI"),
        ],
    )
    assert db_mod._is_analog(gpio_only) is False
    assert "analog" not in {r[0] for r in db_mod.roles(gpio_only)}

    adc = db_mod.Pin(
        position="2", name="PA1", type="I/O",
        signals=[db_mod.Signal(name="ADC1_IN1"), db_mod.Signal(name="GPIO", io_modes="Analog")],
    )
    assert db_mod._is_analog(adc) is True

    opamp = db_mod.Pin(
        position="3", name="PA2", type="I/O",
        signals=[db_mod.Signal(name="OPAMP1_VINP")],
    )
    assert db_mod._is_analog(opamp) is True

    named_analog_mode = db_mod.Pin(
        position="4", name="PB14", type="I/O",
        signals=[db_mod.Signal(name="TSC_G1_IO1", io_modes="Analog")],
    )
    assert db_mod._is_analog(named_analog_mode) is True
