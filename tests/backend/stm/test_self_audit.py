"""Plan 02 Task 2: the build-time structural self-audit hard gate (DATA-07).

Pin-count reconciliation, zero-pin (Pitfall 2 regression lock), and spec
completeness are all HARD gates - the build refuses to complete (raises
StmAuditFailure) rather than silently returning a defective index. AF-range
checks are explicitly out of Phase 1's gate scope.
"""

from pathlib import Path

import pytest

from stockroom.stm import db as db_mod

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "stm"


def test_clean_fixture_build_passes_the_gate():
    idx = db_mod.StmIndex.build(FIXTURES)
    # build() itself calls run_self_audit internally; reaching here without a
    # raised StmAuditFailure already proves the gate passed. Calling it again
    # directly confirms it is idempotently clean.
    db_mod.run_self_audit(idx._conn)


def test_injected_pin_count_mismatch_raises():
    idx = db_mod.StmIndex.build(FIXTURES)
    idx._conn.execute(
        "UPDATE mcu SET pin_count = 999 WHERE ref_name = 'STM32F030RCTx'"
    )
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(idx._conn)
    assert "pin-count mismatch" in str(exc_info.value)
    assert "LQFP64" in str(exc_info.value)


def test_injected_zero_pin_package_raises():
    idx = db_mod.StmIndex.build(FIXTURES)
    mcu_id = idx._conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F048C6Ux'"
    ).fetchone()["id"]
    idx._conn.execute("DELETE FROM mcu_package_pin WHERE mcu_id = ?", (mcu_id,))
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(idx._conn)
    assert "zero-pin package" in str(exc_info.value)


def test_injected_null_spec_field_raises():
    idx = db_mod.StmIndex.build(FIXTURES)
    idx._conn.execute(
        "UPDATE mcu_spec SET core = NULL WHERE mcu_id = "
        "(SELECT id FROM mcu WHERE ref_name = 'STM32F407V(E-G)Tx')"
    )
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(idx._conn)
    assert "incomplete mcu_spec" in str(exc_info.value)
    assert "core" in str(exc_info.value)


def test_missing_mcu_spec_row_raises():
    idx = db_mod.StmIndex.build(FIXTURES)
    mcu_id = idx._conn.execute(
        "SELECT id FROM mcu WHERE ref_name = 'STM32F072RBIx'"
    ).fetchone()["id"]
    idx._conn.execute("DELETE FROM mcu_spec WHERE mcu_id = ?", (mcu_id,))
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.run_self_audit(idx._conn)
    assert "missing mcu_spec row" in str(exc_info.value)


_BAD_PIN_COUNT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<Mcu ClockTree="STM32F0" DBVersion="V3.0" Family="STM32F0" HasPowerPad="false" \
IOType="" Line="STM32F0x0" Package="LQFP64" RefName="SYNTH_BAD_PINCOUNT_Tx" \
xmlns="http://mcd.rou.st.com/modules.php?name=mcu">
    <Core>Arm Cortex-M0</Core>
    <Frequency>48</Frequency>
    <Flash>64</Flash>
    <Ram>8</Ram>
    <IONb>4</IONb>
    <Voltage Max="3.6" Min="2"/>
    <Pin Name="PA0" Position="1" Type="I/O"/>
    <Pin Name="PA1" Position="2" Type="I/O"/>
    <Pin Name="PA2" Position="3" Type="I/O"/>
    <Pin Name="PA3" Position="4" Type="I/O"/>
</Mcu>
"""


def test_stmindex_build_itself_refuses_on_a_real_pin_count_mismatch(tmp_path):
    """Exercises the wired call site (StmIndex.build), not just the standalone
    run_self_audit function: a device claiming package LQFP64 (curated at 64
    pins) but parsing only 4 pins must fail the build outright."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "SYNTH_BAD_PINCOUNT_Tx.xml").write_text(_BAD_PIN_COUNT_XML, encoding="utf-8")
    with pytest.raises(db_mod.StmAuditFailure) as exc_info:
        db_mod.StmIndex.build(src)
    assert "pin-count mismatch" in str(exc_info.value)


def test_af_range_checks_are_not_part_of_this_gate():
    """DATA-07 mentions AF-range checks, but no pin_alternate_function table
    exists in Phase 1 - the gate must not reference AF concepts at all."""
    import inspect

    src = inspect.getsource(db_mod.run_self_audit)
    assert "af_index" not in src
    assert "pin_alternate_function" not in src
