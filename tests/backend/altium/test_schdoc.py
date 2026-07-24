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
