"""Placing a DbLib row onto a real schematic, and refusing to call a no-op a success.

The Altium-driving half is exercised through a fake driver, exactly as the 3D embed is: the
value of these tests is that the RESULT LOGIC is honest about what it observed, which is the
half that was wrong for ten boots when only Altium's own word was consulted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from stockroom.altium.place import (
    PlaceResult,
    parse_resolution,
    place_from_dblib,
    render_place_script,
)
from tests.backend.altium.cfb_writer import write_cfb

_ITEM = "TPD6E05U06RVZR"


# -- the generated script ------------------------------------------------------------------


def test_the_script_resolves_before_it_places_so_a_hang_still_answers_the_question():
    """Resolution is the expensive answer to obtain and placement is the step that can hang, so
    the progress flush must sit BETWEEN them. If placement were attempted first, a timeout would
    teach nothing at all, which is what a timeout used to do here."""
    text = render_place_script(
        dblib_win="C:\\lib\\Stockroom.DbLib",
        design_item_id=_ITEM,
        schdoc_win="C:\\work\\out.SchDoc",
        marker_win="C:\\work\\m.txt",
        progress_win="C:\\work\\p.txt",
    )
    find = text.index("FindComponentSymbol")
    flush = text.index("P.SaveToFile")
    place = text.index("PlaceLibraryComponent")
    assert find < flush < place, "resolution and its flush must both precede the placement"


def test_the_document_is_named_and_marked_modified_before_any_save():
    """The save bug this harness found in itself, locked so it cannot come back.

    Measured 2026-07-26: `DoSafeChangeFileNameAndSave` returned True on a sheet that genuinely
    held the placed component and wrote NO FILE ANYWHERE. A document Altium does not consider
    dirty short circuits its save and still reports success. Naming it is what stops a modal
    Save As; marking it modified is what makes the save actually happen, and only the pair works.
    """
    text = render_place_script(
        dblib_win="C:\\lib\\Stockroom.DbLib",
        design_item_id=_ITEM,
        schdoc_win="C:\\work\\out.SchDoc",
        marker_win="C:\\work\\m.txt",
        progress_win="C:\\work\\p.txt",
    )
    set_name = text.index("Doc.SetFileName")
    modified = text.index("Doc.Modified := True")
    save = text.index("Doc.DoFileSave")
    assert set_name < save, "an unnamed document opens a modal Save As nothing headless can answer"
    assert modified < save, "an unmodified document reports a save it never performed"


def test_a_path_with_an_apostrophe_cannot_end_the_delphi_literal_early():
    """`C:\\Users\\O'Brien\\` is a real path shape, and an unescaped one would not fail loudly: it
    would produce a script that compiles into something else entirely."""
    text = render_place_script(
        dblib_win="C:\\Users\\O'Brien\\Stockroom.DbLib",
        design_item_id=_ITEM,
        schdoc_win="C:\\work\\out.SchDoc",
        marker_win="C:\\work\\m.txt",
        progress_win="C:\\work\\p.txt",
    )
    assert "'C:\\Users\\O''Brien\\Stockroom.DbLib'" in text


def test_every_identifier_kind_is_tried_and_a_rejected_one_cannot_sink_the_run():
    """DelphiScript exposes no constant for TLibIdentifierKind, so the kind is an integer and the
    documented order is a claim. Trying all four inside one boot turns the guess into a fact, and
    guarding each one means a rejected value is REPORTED rather than fatal."""
    text = render_place_script(
        dblib_win="C:\\lib\\Stockroom.DbLib",
        design_item_id=_ITEM,
        schdoc_win="C:\\work\\out.SchDoc",
        marker_win="C:\\work\\m.txt",
        progress_win="C:\\work\\p.txt",
    )
    assert "For kind := 0 To 3 Do" in text
    assert text.count("Except") >= 3  # per-kind guards plus the whole-run guard


# -- the machine-readable log --------------------------------------------------------------


def test_resolution_lines_are_parsed_and_prose_is_ignored():
    log = "\n".join(
        [
            "SR-DbLib=C:\\lib\\Stockroom.DbLib",
            "note: FindComponentSymbol rejected kind 0",
            "SR-SymbolLibrary=C:\\lib\\tpd6e05u06rvzr.SchLib",
            "SR-FootprintLibrary=C:\\lib\\tpd6e05u06rvzr.PcbLib",
            "DONE placed=1",
        ]
    )
    got = parse_resolution(log)
    assert got["SymbolLibrary"] == "C:\\lib\\tpd6e05u06rvzr.SchLib"
    assert got["FootprintLibrary"] == "C:\\lib\\tpd6e05u06rvzr.PcbLib"
    assert "note" not in got


def test_an_empty_answer_never_masks_a_later_real_one():
    """One line per identifier kind is emitted, and the early kinds are the ones that come back
    blank. Keeping the first line rather than the first NON-EMPTY line would report every
    resolution as a failure."""
    log = "SR-SymbolLibrary=\nSR-SymbolLibrary=C:\\lib\\x.SchLib\n"
    assert parse_resolution(log)["SymbolLibrary"] == "C:\\lib\\x.SchLib"


# -- the result logic ----------------------------------------------------------------------


@dataclass
class _Outcome:
    status: str
    detail: str
    marker_text: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class _FakeHost:
    def to_windows_path(self, path: str) -> str:
        return path

    def windows_temp(self) -> Path:  # pragma: no cover - never reached, workdir is always passed
        raise AssertionError("the test always passes an explicit workdir")


class _FakeDriver:
    """Stands in for Altium. `writes` is what the run leaves on disk, so a run that reports
    success while writing nothing is expressible, because that is the failure being guarded."""

    def __init__(self, outcome: _Outcome, writes: bytes | None = None, out_doc: Path | None = None):
        self.host = _FakeHost()
        self._outcome = outcome
        self._writes = writes
        self._out_doc = out_doc
        self.ran = False

    def run_script(self, **kwargs):
        self.ran = True
        if self._writes is not None and self._out_doc is not None:
            self._out_doc.write_bytes(self._writes)
        return self._outcome


def _rec(*pairs: str) -> bytes:
    payload = ("|" + "|".join(pairs)).encode("latin-1") + b"\x00"
    return struct.pack("<I", len(payload)) + payload


def _placed_schdoc(path: Path, design_item_id: str = _ITEM) -> None:
    """A real OLE compound file holding one placed component, written with the same builder the
    .SchDoc reader's own tests use. Building it rather than checking in a binary keeps the
    independent verdict exercised against genuine framing without a fixture nobody can read."""
    stream = (
        _rec("HEADER=Protel for Windows - Schematic Capture Binary File Version 5.0", "WEIGHT=10")
        + _rec(
            "RECORD=1",
            "LIBREFERENCE=" + design_item_id,
            "DESIGNITEMID=" + design_item_id,
            "OWNERPARTID=-1",
            "PARTCOUNT=1",
        )
        + _rec("RECORD=34", "OWNERINDEX=0", "NAME=Designator", "TEXT=D1")
        + _rec("RECORD=41", "OWNERINDEX=0", "NAME=MPN", "TEXT=" + design_item_id)
        + _rec("RECORD=44", "OWNERINDEX=0")
        + _rec("RECORD=45", "OWNERINDEX=3", "MODELNAME=RVZ0014A", "MODELTYPE=PCBLIB", "ISCURRENT=T")
    )
    write_cfb(path, "FileHeader", stream)


def test_a_missing_dblib_is_reported_without_booting_altium(tmp_path):
    drv = _FakeDriver(_Outcome("ok", ""))
    res = place_from_dblib(tmp_path / "nope.DbLib", _ITEM, driver=drv, workdir=tmp_path)
    assert res.status == "not-placed"
    assert not drv.ran, "a missing library must not cost an Altium boot"


def test_altium_reporting_success_while_writing_nothing_is_NOT_ok(tmp_path):
    """The whole point of the second verdict. This exact shape (a clean log, an unwritten file)
    is what cost ten boots on the 3D embed before the file was consulted."""
    dblib = tmp_path / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    drv = _FakeDriver(_Outcome("ok", "", marker_text="SR-PlaceReturned=True\nDONE placed=1\n"))
    res = place_from_dblib(dblib, _ITEM, driver=drv, workdir=tmp_path)
    assert res.status == "not-placed"
    assert "nothing was actually placed" in res.detail


def test_a_FAIL_line_wins_over_a_clean_exit_code(tmp_path):
    dblib = tmp_path / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    log = "SR-SymbolLibrary=\nFAIL: the save was REFUSED for C:\\x.SchDoc\nDONE placed=0\n"
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = place_from_dblib(dblib, _ITEM, driver=drv, workdir=tmp_path)
    assert res.status == "not-placed"
    assert "REFUSED" in res.detail


def test_resolution_survives_a_timeout_via_the_progress_file(tmp_path):
    """A timeout is a backstop, not a detector. The run may die during placement and the
    resolution answer must still come back, because that is the expensive half to obtain."""
    dblib = tmp_path / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    work = tmp_path / "w"
    work.mkdir()

    class _Timeout(_FakeDriver):
        def run_script(self, **kwargs):
            (work / "SRPlace-progress.txt").write_text(
                "SR-SymbolLibrary=C:\\lib\\x.SchLib\nSR-FootprintLibrary=C:\\lib\\x.PcbLib\n",
                encoding="utf-8",
            )
            return _Outcome("timeout", "Altium never wrote the marker")

    res = place_from_dblib(dblib, _ITEM, driver=_Timeout(_Outcome("timeout", "")), workdir=work)
    assert res.status == "timeout"
    assert res.resolved_symbol and res.resolved_footprint
    assert res.symbol_library == "C:\\lib\\x.SchLib"


def test_a_real_schdoc_is_read_back_as_the_independent_verdict(tmp_path):
    """The success path, proven against a genuine Altium binary: the components in the SAVED file
    are what is reported, never what the script claimed."""
    dblib = tmp_path / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    built = tmp_path / "built.SchDoc"
    _placed_schdoc(built)
    out = tmp_path / "SRPlace.SchDoc"
    drv = _FakeDriver(
        _Outcome("ok", "", marker_text="SR-SymbolLibrary=C:\\lib\\x.SchLib\nDONE placed=1\n"),
        writes=built.read_bytes(),
        out_doc=out,
    )
    res = place_from_dblib(dblib, _ITEM, driver=drv, schdoc=out, workdir=tmp_path)
    assert res.status == "ok"
    # The verdict comes from the FILE, not from the log: the identity, the footprint and the
    # carried DbLib column are all read back out of the saved binary.
    assert res.placed_design_item_ids == (_ITEM,)
    assert res.placed_footprints == ("RVZ0014A",)
    assert res.placed_parameters["MPN"] == _ITEM
    assert res.symbol_library == "C:\\lib\\x.SchLib"


def test_resolution_is_read_from_the_signals_that_actually_marshal(tmp_path):
    """DelphiScript does not marshal `out WideString` back to the caller.

    Measured 2026-07-26 on a run that genuinely placed a component: FindComponentSymbol returned
    True and the part landed on the sheet, while its ASymbolLibraryPath out-param arrived EMPTY.
    Reading resolution from that out-param made a working library report `<UNRESOLVED>`, so the
    gate produced a false negative about the very thing it exists to measure. The signals that do
    survive are the recorded return value and FindComponentDisplayPath.
    """
    dblib = tmp_path / "Stockroom.DbLib"
    dblib.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    built = tmp_path / "built.SchDoc"
    _placed_schdoc(built)
    out = tmp_path / "SRPlace.SchDoc"
    log = "\n".join(
        [
            "SR-DisplayPath0=",  # the empty kinds must not win
            "SR-DisplayPath3=C:\\lib\\tpd6e05u06rvzr.SchLib",
            "SR-SymbolLibrary=",  # the out-param, empty even on success
            "SR-SymbolIdentifier=C:\\lib\\tpd6e05u06rvzr.SchLib",
            "DONE placed=1",
        ]
    )
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log), writes=built.read_bytes(), out_doc=out)
    res = place_from_dblib(dblib, _ITEM, driver=drv, schdoc=out, workdir=tmp_path)
    assert res.resolved_symbol, "an empty out-param must not read as an unresolved symbol"
    assert res.symbol_library == "C:\\lib\\tpd6e05u06rvzr.SchLib"


def test_resolved_flags_are_false_when_altium_resolved_nothing():
    """An empty string is the honest answer for "could not resolve", and the flags must not turn
    it into a truthy one."""
    res = PlaceResult("ok", "", symbol_library="", footprint_library="C:\\x.PcbLib")
    assert not res.resolved_symbol
    assert res.resolved_footprint
