"""The .SchDoc component reader: placed components with designator, library
reference, parameters, and current footprint, read straight from the Altium
binary schematic (OLE FileHeader stream of length-prefixed pipe records).

Record framing: <u32 little-endian> where the low 3 bytes are the payload length
and the high byte is the record type (0 = ASCII pipe record), then the payload
`|KEY=VALUE|...` NUL-terminated. OWNERINDEX counts records from zero starting at
the first record AFTER the file header record (python-altium's convention).
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from stockroom.altium.schdoc import (
    _components_from_stream,
    read_schdoc_components,
)
from tests.backend.altium.cfb_writer import write_cfb


def _rec(*pairs: str) -> bytes:
    payload = ("|" + "|".join(pairs)).encode("latin-1") + b"\x00"
    return struct.pack("<I", len(payload)) + payload


HEADER = _rec("HEADER=Protel for Windows - Schematic Capture Binary File Version 5.0", "WEIGHT=10")


def _component_stream() -> bytes:
    # index 0: the component; 1: its designator; 2: a parameter; 3: the implementation
    # list; 4: the current PCBLIB implementation (owner chain 4 -> 3 -> 0).
    return (
        HEADER
        + _rec("RECORD=1", "LIBREFERENCE=LM358", "DESIGNITEMID=LM358DR", "OWNERPARTID=-1", "PARTCOUNT=3")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=U1")
        + _rec("RECORD=41", "OWNERINDEX=0", "NAME=MPN", "TEXT=LM358DR")
        + _rec("RECORD=44", "OWNERINDEX=0")
        + _rec("RECORD=45", "OWNERINDEX=3", "MODELNAME=SOIC-8", "MODELTYPE=PCBLIB", "ISCURRENT=T")
    )


def test_reads_a_component_with_designator_params_and_footprint():
    comps = _components_from_stream(_component_stream())
    assert len(comps) == 1
    c = comps[0]
    assert c["designator"] == "U1"
    assert c["lib_ref"] == "LM358"
    assert c["params"]["MPN"] == "LM358DR"
    assert c["footprint"] == "SOIC-8"
    assert c["design_item_id"] == "LM358DR"


def test_multi_unit_placements_collapse_to_one_physical_component():
    # A multi-part component (an op-amp's A and B units) places one RECORD=1 per unit,
    # all sharing the designator. The BOM must count ONE physical part.
    stream = (
        HEADER
        + _rec("RECORD=1", "LIBREFERENCE=LM358", "OWNERPARTID=-1", "CURRENTPARTID=1")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=U1")
        + _rec("RECORD=1", "LIBREFERENCE=LM358", "OWNERPARTID=-1", "CURRENTPARTID=2")
        + _rec("RECORD=34", "OWNERINDEX=2", "NAME=Designator", "TEXT=U1")
    )
    comps = _components_from_stream(stream)
    assert [c["designator"] for c in comps] == ["U1"]


def test_two_unannotated_copies_stay_two_components():
    # Two placed-but-unannotated copies of a SINGLE-part symbol share the designator
    # ("R?") AND the library reference, but both are unit 1 (same CURRENTPARTID).
    # They are two physical parts; only DIFFERENT unit ids collapse.
    stream = (
        HEADER
        + _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1", "CURRENTPARTID=1")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=R?")
        + _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1", "CURRENTPARTID=1")
        + _rec("RECORD=34", "OWNERINDEX=2", "NAME=Designator", "TEXT=R?")
    )
    comps = _components_from_stream(stream)
    assert [c["designator"] for c in comps] == ["R?", "R?"]


def test_two_distinct_components_stay_distinct():
    stream = (
        HEADER
        + _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=R1")
        + _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1")
        + _rec("RECORD=34", "OWNERINDEX=2", "NAME=Designator", "TEXT=R2")
    )
    comps = _components_from_stream(stream)
    assert sorted(c["designator"] for c in comps) == ["R1", "R2"]


def test_utf8_twin_key_wins_over_the_latin1_spelling():
    # Altium writes |NAME=X|%UTF8%NAME=X with the utf-8 bytes authoritative.
    stream = (
        HEADER
        + _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=R1")
        + _rec(
            "RECORD=41",
            "OWNERINDEX=0",
            "NAME=Manufacturer",
            "TEXT=M\xc3\xbcller",  # utf-8 bytes seen through latin-1
            "%UTF8%TEXT=M\xc3\xbcller",
        )
    )
    comps = _components_from_stream(stream)
    assert comps[0]["params"]["Manufacturer"] == "Müller"


def test_records_without_a_header_record_still_index_from_zero():
    # Defensive: a stream missing the HEADER record indexes its first record as 0.
    stream = (
        _rec("RECORD=1", "LIBREFERENCE=RES", "OWNERPARTID=-1")
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=R7")
    )
    assert _components_from_stream(stream)[0]["designator"] == "R7"


def test_zero_length_padding_terminates_the_stream():
    stream = _component_stream() + b"\x00" * 64
    assert len(_components_from_stream(stream)) == 1


def test_read_schdoc_components_end_to_end(tmp_path):
    path = tmp_path / "Amp.SchDoc"
    write_cfb(path, "FileHeader", _component_stream())
    comps = read_schdoc_components(path)
    assert len(comps) == 1
    assert comps[0]["designator"] == "U1"
    assert comps[0]["footprint"] == "SOIC-8"


def test_read_schdoc_components_returns_empty_for_a_fileheaderless_ole(tmp_path):
    path = tmp_path / "Odd.SchDoc"
    write_cfb(path, "SomethingElse", b"\x00")
    assert read_schdoc_components(path) == []


def test_read_schdoc_components_raises_on_a_non_ole_file(tmp_path):
    path = tmp_path / "NotOle.SchDoc"
    path.write_text("plain text", encoding="utf-8")
    with pytest.raises(Exception):
        read_schdoc_components(path)


# -- key CASE: what a real Altium writes, versus what these tests used to assume ----


def _real_world_stream() -> bytes:
    """Records spelled the way real AD26 spells them: MIXED CASE.

    Every other test in this file synthesises UPPERCASE keys, and the reader matched uppercase, so
    the whole suite passed while the reader returned blank fields for every genuine Altium file.
    Captured 2026-07-26 from a component placed by hand in AD26 26.8.1 from the Stockroom DbLib
    (`C:\\srplace\\Placed.SchDoc`): `LibReference`, `DesignItemId`, `OwnerIndex`, `Text`, `Name`,
    `ModelName`, `ModelType`, `IsCurrent`. Not one of them is uppercase.
    """
    return (
        _rec("HEADER=Protel for Windows - Schematic Capture Binary File Version 5.0", "Weight=82")
        + _rec(
            "RECORD=1",
            "LibReference=TPD6E05U06RVZR",
            "DesignItemId=TPD6E05U06RVZR",
            "SourceLibraryName=Stockroom.DbLib",
            "DatabaseTableName=Parts",
            "UniqueID=DCIJNTYU",
            "OwnerPartId=-1",
            "PartCount=2",
            "CurrentPartId=1",
        )
        + _rec("RECORD=34", "OwnerIndex=0", "Name=Designator", "Text=U?")
        + _rec("RECORD=41", "OwnerIndex=0", "Name=MPN", "Text=TPD6E05U06RVZR")
        + _rec("RECORD=41", "OwnerIndex=0", "Name=Manufacturer", "Text=TI")
        + _rec("RECORD=44", "OwnerIndex=0")
        + _rec("RECORD=45", "OwnerIndex=4", "ModelName=RVZ0014A", "ModelType=PCBLIB", "IsCurrent=T")
    )


def test_reads_a_component_written_with_REAL_altium_key_casing():
    """The reader must not care how Altium capitalises its keys.

    This failed before 2026-07-26: a real placed component came back with every field empty
    (designator '', lib_ref '', footprint ''), which silently emptied the Altium BOM and project
    health. It went unnoticed because no test had ever been run against a file Altium wrote.
    """
    comps = _components_from_stream(_real_world_stream())
    assert len(comps) == 1
    c = comps[0]
    assert c["lib_ref"] == "TPD6E05U06RVZR"
    assert c["design_item_id"] == "TPD6E05U06RVZR"
    assert c["designator"] == "U?"
    assert c["footprint"] == "RVZ0014A"
    assert c["params"]["MPN"] == "TPD6E05U06RVZR"
    assert c["params"]["Manufacturer"] == "TI"
    assert c["unique_id"] == "DCIJNTYU"


def test_reads_a_REAL_ad26_file_placed_from_the_stockroom_dblib():
    """The anti-vacuity test: a file Altium itself wrote, not one this suite invented.

    Every other fixture here is synthesised, and that is exactly how the mixed-case bug survived -
    the suite could not fail on the artifact it exists to read. This one was produced on
    2026-07-26 by placing TPD6E05U06RVZR onto a sheet by hand in AD26 26.8.1, from the generated
    Stockroom DbLib, and saving. If Altium changes its framing or its casing, this fails.

    It also pins the whole Altium handoff end to end: the symbol resolved, the footprint attached,
    and all twenty database columns rode onto the placement - including `Stockroom ID`, which is
    the durable binding back to the library record.
    """
    fixture = Path(__file__).resolve().parent / "fixtures" / "ad26-dblib-placed.SchDoc"
    comps = read_schdoc_components(fixture)
    assert len(comps) == 1
    c = comps[0]
    assert c["designator"] == "U?"
    assert c["lib_ref"] == "TPD6E05U06RVZR"
    assert c["design_item_id"] == "TPD6E05U06RVZR"
    assert c["footprint"] == "RVZ0014A"
    assert c["unique_id"]
    assert c["params"]["MPN"] == "TPD6E05U06RVZR"
    assert c["params"]["Manufacturer"] == "TI"
    # The placement binding, which is the whole point of shipping a Stockroom ID column.
    assert c["params"]["Stockroom ID"] == "tpd6e05u06rvzr"
