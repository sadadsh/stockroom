"""Task 2: mcu_spec + mcu_peripheral extraction (the spec matrix).

Text-content elements (Core, Frequency, Flash, Ram, CCMRam, IONb, Die) must be read
via el.text; attribute-valued elements (Voltage Min/Max, Current Lowest/Run,
Temperature Min/Max) must be read via el.get(...) - mixing these up is an easy,
real parsing bug (verified against the committed STM32F407V(E-G)Tx.xml sample).
"""

from pathlib import Path

from stockroom.stm import db as db_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"
F407_XML = FIXTURES / "STM32F407V(E-G)Tx.xml"


def test_f407_mcu_spec_fields_from_real_fixture():
    mcu = db_mod.parse_mcu_xml(F407_XML)
    assert mcu.core == "Arm Cortex-M4"
    assert mcu.frequency_mhz == 168
    # <Flash>512</Flash> then <Flash>1024</Flash> - MAX, not the first.
    assert mcu.flash_kb == 1024
    # <Ram>128</Ram> twice - MAX across the repeat.
    assert mcu.ram_kb == 128
    assert mcu.ccm_ram_kb == 64
    assert mcu.io_count == 82
    assert mcu.die == "DIE413"
    # <Voltage Max="3.6" Min="1.8"/>, <Temperature Max="85" Min="-40"/>
    assert mcu.vdd_min == "1.8"
    assert mcu.vdd_max == "3.6"
    assert mcu.temp_min_c == -40
    assert mcu.temp_max_c == 85


def test_f407_mcu_peripheral_rows_and_group_by_count():
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    mcu_id = conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F407V(E-G)Tx'"
    ).fetchone()["id"]

    rows = conn.execute(
        "SELECT peripheral_name, instance_name, version FROM mcu_peripheral "
        "WHERE mcu_id = ?",
        (mcu_id,),
    ).fetchall()
    assert len(rows) > 0

    counts = {
        r["peripheral_name"]: r["n"]
        for r in conn.execute(
            "SELECT peripheral_name, COUNT(*) n FROM mcu_peripheral WHERE mcu_id = ? "
            "GROUP BY peripheral_name",
            (mcu_id,),
        )
    }
    # USART/SPI/ADC bucket cleanly under IP/@Name in the real F407 XML (each
    # instance shares one Name value). TIM does NOT: CubeMX groups timers by
    # silicon variant (Name="TIM1_8"/"TIM6_7" here, not a flat "TIM"), so a
    # generic peripheral_name GROUP BY is verified via instance_name prefix
    # instead - this is a genuine CubeMX data quirk, not a parser bug.
    for name in ("USART", "SPI", "ADC"):
        assert counts.get(name, 0) > 0, f"expected {name} peripheral(s) on F407"
    tim_instances = conn.execute(
        "SELECT COUNT(*) FROM mcu_peripheral WHERE mcu_id = ? AND instance_name LIKE 'TIM%'",
        (mcu_id,),
    ).fetchone()[0]
    assert tim_instances > 0, "expected TIM instance(s) on F407"


def test_every_fixture_mcu_gets_exactly_one_mcu_spec_row():
    idx = db_mod.StmIndex.build(FIXTURES)
    conn = idx._conn
    mcu_ids = [r["id"] for r in conn.execute("SELECT id FROM mcu")]
    assert len(mcu_ids) == 4
    for mcu_id in mcu_ids:
        n = conn.execute(
            "SELECT COUNT(*) FROM mcu_spec WHERE mcu_id = ?", (mcu_id,)
        ).fetchone()[0]
        assert n == 1, f"mcu {mcu_id} should have exactly one mcu_spec row, got {n}"
        row = conn.execute(
            "SELECT core, flash_kb, ram_kb, max_freq_mhz FROM mcu_spec WHERE mcu_id = ?",
            (mcu_id,),
        ).fetchone()
        assert row["core"], f"mcu {mcu_id} missing core"
        assert row["flash_kb"] is not None
        assert row["ram_kb"] is not None
        assert row["max_freq_mhz"] is not None


_TEXT_VS_ATTR_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Mcu ClockTree="STM32F0" DBVersion="V3.0" Family="STM32F0" HasPowerPad="false" \
IOType="" Line="STM32F0x0" Package="LQFP48" RefName="SYNTH_TEXT_VS_ATTR_Tx" \
xmlns="http://mcd.rou.st.com/modules.php?name=mcu">
    <Core>Arm Cortex-M0</Core>
    <Frequency>48</Frequency>
    <Voltage Max="3.6" Min="2.0"/>
    <Temperature Max="85" Min="-40"/>
    <Current Lowest="1.5" Run="12"/>
</Mcu>
"""


def test_text_content_vs_attribute_distinction_is_not_swapped(tmp_path):
    src = tmp_path / "SYNTH_TEXT_VS_ATTR_Tx.xml"
    src.write_text(_TEXT_VS_ATTR_XML, encoding="utf-8")
    mcu = db_mod.parse_mcu_xml(src)

    # Core is TEXT content - a naive el.get("Core") would find nothing (Core has
    # no attributes at all), so this also proves text-reading, not attr-reading.
    assert mcu.core == "Arm Cortex-M0"
    assert mcu.frequency_mhz == 48

    # Voltage/Temperature/Current are ATTRIBUTE-valued and carry NO text content;
    # if the parser mistakenly tried el.text on these elements it would get None/""
    # instead of the real values, so a correct read proves attribute-sourcing.
    assert mcu.vdd_min == "2.0"
    assert mcu.vdd_max == "3.6"
    assert mcu.temp_min_c == -40
    assert mcu.temp_max_c == 85
    assert mcu.current_lowest_ua == 1
    assert mcu.current_run_ma == 12
