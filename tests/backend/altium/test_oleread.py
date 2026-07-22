from pathlib import Path

import pytest

from stockroom.altium.oleread import (
    _footprint_names_from_data,
    _symbol_names_from_header,
    pick_entry,
    read_footprint_names,
    read_symbol_names,
)

FIX = Path(__file__).parent / "fixtures"


def test_symbol_names_from_real_schlib():
    assert read_symbol_names(FIX / "sample.SchLib") == ["S1M"]


def test_footprint_names_from_real_pcblib():
    assert read_footprint_names(FIX / "sample.PcbLib") == ["DIOM5227X270N"]


def test_symbol_parser_reads_authoritative_untruncated_name():
    # FileHeader is a pipe-delimited key=value blob; LibRefN holds the FULL symbol name even
    # when it exceeds the 31-char OLE storage-name limit (so no truncation, no metadata filter).
    long_name = "A_VERY_LONG_SYMBOL_NAME_OVER_31_CHARACTERS"
    header = f"|CompCount=1|LibRef0={long_name}|CompDescr0=whatever|PartCount0=1".encode("latin-1")
    assert _symbol_names_from_header(header) == [long_name]


def test_symbol_parser_does_not_treat_a_component_named_header_as_metadata():
    # a symbol literally named "Header" (common pin-header symbol) must survive
    header = b"|CompCount=1|LibRef0=Header|CompDescr0=x|PartCount0=1"
    assert _symbol_names_from_header(header) == ["Header"]


def test_footprint_parser_reads_length_prefixed_records_untruncated():
    long_fp = "HIROSE-BM23PF-40-0.35MM-RECEPTACLE"  # 34 chars > 31
    payload = _fp_record(long_fp) + _fp_record("SMD0402")
    assert _footprint_names_from_data(payload) == [long_fp, "SMD0402"]


def _fp_record(name: str) -> bytes:
    import struct
    b = name.encode("latin-1")
    return struct.pack("<I", len(b) + 1) + bytes([len(b)]) + b


def test_pick_entry_single():
    assert pick_entry(["ONLY"], "symbol") == "ONLY"


def test_pick_entry_prefers_exact_match_when_multiple():
    assert pick_entry(["A", "BQ24074RGTT", "C"], "symbol", prefer="BQ24074RGTT") == "BQ24074RGTT"


def test_pick_entry_raises_on_ambiguous_multiple():
    with pytest.raises(ValueError, match="entries"):
        pick_entry(["A", "B"], "footprint")  # no prefer, cannot disambiguate


def test_pick_entry_raises_on_empty():
    with pytest.raises(ValueError, match="no footprint"):
        pick_entry([], "footprint")
