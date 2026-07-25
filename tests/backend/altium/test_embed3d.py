"""Embedding a STEP model into a `.PcbLib` as an Altium 3D Body.

The verifier's predicate is unit-tested exhaustively against stream maps, because authoring a
real Altium container per case would need an Altium install. The reading path over a REAL file is
covered by `test_real_pcblib_probe_output` below, which runs only where the probe output exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stockroom.altium.driver import RunOutcome
from stockroom.altium.embed3d import (
    delphi_quote,
    embed_model,
    embedded_models,
    has_embedded_model,
    model_index_bytes,
    ole_streams,
    render_embed_script,
)

# The measured signature of a library that really does carry one embedded model, taken from
# `scripts/altium_probe.py --variant board-add` on 2026-07-25. Numbers are the real ones.
GOLDEN = {
    "Library/Data": 94428,
    "Library/Models/Data": 162,
    "Library/Models/0": 65536,
    "Library/ModelsNoEmbed/Data": 0,
    "RVZ0014A/Data": 5410,
    "RVZ0014A/PrimitiveGuids/Data": 768,
}

# The signature EVERY failed embed produced: the model storage exists but is empty.
EMPTY = {
    "Library/Data": 94417,
    "Library/Models/Data": 0,
    "Library/ModelsNoEmbed/Data": 0,
    "RVZ0014A/Data": 4578,
}


def _script(**kw) -> str:
    return render_embed_script(
        pcblib_win=kw.pop("lib", "C:\\lib\\part.PcbLib"),
        step_win=kw.pop("step", "C:\\lib\\part.stp"),
        marker_win=kw.pop("marker", "C:\\tmp\\m.txt"),
        **kw,
    )


def _code(**kw) -> str:
    """The generated script with Delphi comments stripped, for assertions about what it DOES.

    Necessary, not fussy: the script explains in a comment why the body must not be added with
    `Fp.AddPCBObject`, so a naive substring check on the whole text matches the warning against
    the mistake and reports the mistake itself.
    """
    return re.sub(r"\{.*?\}", "", _script(**kw), flags=re.DOTALL)


# --- the verifier -----------------------------------------------------------------------


def test_the_golden_signature_is_recognised_as_an_embedded_model():
    assert has_embedded_model(GOLDEN)
    assert embedded_models(GOLDEN) == {0: 65536}
    assert model_index_bytes(GOLDEN) == 162


def test_the_measured_failure_signature_is_recognised_as_no_model():
    assert not has_embedded_model(EMPTY)
    assert embedded_models(EMPTY) == {}
    assert model_index_bytes(EMPTY) == 0


def test_an_empty_container_has_no_model():
    assert not has_embedded_model({})
    assert model_index_bytes({}) == 0


def test_a_zero_length_payload_stream_does_not_count():
    # A present-but-empty numbered stream is not a model. Counting it would report a failed
    # embed as a success, which is the exact class of blind spot this verifier exists to close.
    assert not has_embedded_model({"Library/Models/0": 0})


def test_the_index_stream_is_never_mistaken_for_a_payload():
    # `Library/Models/Data` is the index, not a payload. A predicate matching anything under
    # `Models/` would count it and always report success.
    assert not has_embedded_model({"Library/Models/Data": 162})


def test_matching_is_case_insensitive_on_the_full_path():
    # The trap this locks: an earlier check used `name.startswith("models")`, which can NEVER
    # match because every path begins with `Library/`. It would have called a real success a
    # failure.
    assert has_embedded_model({"LIBRARY/MODELS/3": 40})
    assert embedded_models({"library/models/12": 7}) == {12: 7}


def test_several_models_are_all_counted():
    streams = {"Library/Models/0": 100, "Library/Models/1": 200, "Library/Models/2": 0}
    assert embedded_models(streams) == {0: 100, 1: 200}


def test_a_lookalike_path_elsewhere_is_not_counted():
    assert not has_embedded_model({"Other/Library/Models/0": 500, "Models/0": 500})


# --- the generated script ---------------------------------------------------------------


def test_the_body_is_added_to_the_board_and_never_to_the_footprint():
    # THE regression lock for punch 16. `Fp.AddPCBObject` attaches the body in memory and it is
    # silently dropped on save; `Board.AddPCBObject` persists it. Ten Altium boots and nine wrong
    # hypotheses went into that one call, and both community scripts used as references have it
    # wrong, so it is asserted rather than trusted to a comment.
    code = _code()
    assert "Board.AddPCBObject(Body)" in code
    assert "Fp.AddPCBObject" not in code, "the failing call must not appear in executable code"


def test_the_footprint_is_made_current_before_it_is_touched():
    # The library's Board exposes the CURRENT component's primitives, which is the graph the save
    # serialises.
    text = _script()
    current = text.index("SetState_CurrentComponent")
    assert current < text.index("Board.AddPCBObject(Body)")


def test_the_model_is_embedded_not_linked():
    # A linked path cannot survive the library moving to another machine, which a git-synced
    # shared library does by definition.
    assert "ModelFactory_FromFilename(StepPath, True)" in _script()


def test_the_save_return_value_is_checked():
    # Calling DoFileSave as a procedure throws the answer away, so a REFUSED save looked exactly
    # like a successful one.
    text = _script()
    assert "SaveOk := Doc.DoFileSave('PcbLib')" in text
    assert "REFUSED" in text


def test_the_marker_is_written_on_every_path():
    text = _script()
    assert "Finally" in text
    assert text.index("L.SaveToFile") > text.index("Finally")
    assert "DONE added=" in text


def test_re_running_removes_a_body_for_the_same_model_first():
    text = _script()
    assert "RemovePCBObject" in text
    assert text.index("RemovePCBObject") < text.index("Board.AddPCBObject(Body)")


def test_paths_are_delphi_quoted_and_apostrophes_are_doubled():
    # A user really can be called O'Brien, and an unescaped apostrophe ends the literal early and
    # breaks the whole script.
    assert delphi_quote("C:\\Users\\O'Brien\\a.stp") == "'C:\\Users\\O''Brien\\a.stp'"
    text = _script(lib="C:\\O'B\\p.PcbLib")
    assert "'C:\\O''B\\p.PcbLib'" in text


def test_an_empty_footprint_filter_still_consults_the_list():
    # ONE code path in both cases, so the filter logic is never an untested generated branch.
    text = _script()
    assert "Wanted := TStringList.Create" in text
    assert "Wanted.IndexOf(Fp.Name)" in text
    assert "Wanted.Add(" not in text
    assert "no filter" in text


def test_named_footprints_are_added_to_the_filter():
    text = _script(footprints=("RVZ0014A", "SOT-23"))
    assert "Wanted.Add('RVZ0014A')" in text
    assert "Wanted.Add('SOT-23')" in text


def test_the_generated_script_is_structurally_balanced():
    # A cheap structural gate over the template. In Delphi every `Begin` and every `Try` closes
    # with an `End`, so the counts must satisfy End == Begin + Try. Editing the template by hand
    # is exactly how an unbalanced block gets shipped, and Altium answers an unparseable script
    # by opening a chooser and waiting for a human, which costs a whole boot to discover.
    text = _script(footprints=("A",))
    body = re.sub(r"\{.*?\}", "", text, flags=re.DOTALL)  # drop Delphi comments
    n = {word: len(re.findall(rf"\b{word}\b", body, re.IGNORECASE)) for word in ("begin", "end", "try")}
    assert n["end"] == n["begin"] + n["try"], n


def test_the_procedure_name_matches_what_the_driver_asks_altium_to_run():
    assert "Procedure SREmbed3D;" in _script()


# --- the orchestration ------------------------------------------------------------------


class FakeHost:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp

    def to_windows_path(self, path: str) -> str:
        return "C:\\fake" + str(path).replace("/", "\\")

    def windows_temp(self) -> Path:
        return self.tmp


class FakeDriver:
    """Stands in for a real Altium. `outcome` is what the run reports."""

    def __init__(self, tmp: Path, outcome: RunOutcome) -> None:
        self.host = FakeHost(tmp)
        self.outcome = outcome
        self.calls: list[dict] = []

    def run_script(self, **kw) -> RunOutcome:
        self.calls.append(kw)
        return self.outcome


@pytest.fixture
def parts(tmp_path: Path) -> tuple[Path, Path]:
    lib = tmp_path / "part.PcbLib"
    step = tmp_path / "part.stp"
    lib.write_bytes(b"not-really-ole")
    step.write_bytes(b"ISO-10303-21;")
    return lib, step


def test_a_missing_library_is_refused_without_booting_altium(tmp_path: Path, parts):
    _lib, step = parts
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "DONE added=1 removed=0"))
    res = embed_model(tmp_path / "absent.PcbLib", step, driver=drv, workdir=tmp_path)
    assert res.status == "not-written" and not drv.calls


def test_a_missing_model_file_is_refused_without_booting_altium(tmp_path: Path, parts):
    lib, _step = parts
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "DONE added=1 removed=0"))
    res = embed_model(lib, tmp_path / "absent.stp", driver=drv, workdir=tmp_path)
    assert res.status == "not-written" and not drv.calls


def test_a_driver_level_failure_is_reported_verbatim(tmp_path: Path, parts):
    lib, step = parts
    drv = FakeDriver(tmp_path, RunOutcome("busy", "A windowed Altium holds the license seat."))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.status == "busy" and "license seat" in res.detail and not res.ok


def test_altium_reporting_success_with_no_payload_is_NOT_treated_as_done(
    tmp_path: Path, parts, monkeypatch
):
    # The exact failure that survived ten boots: Altium says OK, DoFileSave returns TRUE, and the
    # file gained nothing. Trusting Altium's word here is what hid it.
    lib, step = parts
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: dict(EMPTY))
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "embedded part.stp into X\nDONE added=1 removed=0"))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.status == "not-written"
    assert "no 3D model payload" in res.detail
    assert not res.ok


def test_a_payload_appearing_is_the_success_condition(tmp_path: Path, parts, monkeypatch):
    lib, step = parts
    seq = [dict(EMPTY), dict(GOLDEN)]
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: seq.pop(0))
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "embedded part.stp into X\nDONE added=1 removed=0"))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.ok and res.embedded == 1
    assert res.payload_bytes == 65536
    assert "65536 bytes of model payload added" in res.detail


def test_a_script_reported_failure_surfaces_its_own_reason(tmp_path: Path, parts, monkeypatch):
    lib, step = parts
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: dict(EMPTY))
    drv = FakeDriver(
        tmp_path,
        RunOutcome("ok", "", "FAIL: Altium could not load C:\\lib\\part.stp\nDONE added=0 removed=0"),
    )
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.status == "not-written"
    assert "could not load" in res.detail


def test_the_script_and_project_are_written_where_altium_is_told_to_look(tmp_path: Path, parts, monkeypatch):
    lib, step = parts
    seq = [dict(EMPTY), dict(GOLDEN)]
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: seq.pop(0))
    work = tmp_path / "work"
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "DONE added=1 removed=0"))
    embed_model(lib, step, driver=drv, workdir=work)
    assert (work / "SREmbed3D.pas").exists()
    prj = (work / "SREmbed3D.PrjScr").read_text(encoding="utf-8")
    assert "DocumentPath=SREmbed3D.pas" in prj
    assert drv.calls[0]["proc"] == "SREmbed3D.pas>SREmbed3D"
    assert drv.calls[0]["project"] == work / "SREmbed3D.PrjScr"
    # CRLF matters to Altium's parser; read bytes because decoding would normalise it away.
    assert b"\r\n" in (work / "SREmbed3D.pas").read_bytes()


def test_an_unreadable_container_is_a_baseline_of_zero_not_a_crash(tmp_path: Path, parts, monkeypatch):
    # A vendor library Altium has not yet normalised can legitimately fail to parse. That is a
    # baseline, not an error to raise from the middle of an embed.
    lib, step = parts
    monkeypatch.setattr(
        "stockroom.altium.embed3d.ole_streams",
        lambda _p: (_ for _ in ()).throw(OSError("not an OLE file")),
    )
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "DONE added=1 removed=0"))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.status == "not-written"


# --- the real reading path --------------------------------------------------------------

_PROBE_OUT = Path("/mnt/c/srprobe/run")


@pytest.mark.skipif(
    not (_PROBE_OUT / "board-add.PcbLib").exists(),
    reason="needs scripts/altium_probe.py output from a machine with Altium",
)
def test_real_pcblib_probe_output():
    """`ole_streams` against REAL Altium output, not a hand-made map.

    The pass and fail libraries come from the same probe run, so this asserts the verifier tells
    them apart on genuine files. Skipped where the probe has never run; on a machine with Altium
    it is the end-to-end proof.
    """
    good = ole_streams(_PROBE_OUT / "board-add.PcbLib")
    assert has_embedded_model(good), good
    assert model_index_bytes(good) > 0
    bad_file = _PROBE_OUT / "fp-add.PcbLib"
    if bad_file.exists():
        bad = ole_streams(bad_file)
        assert not has_embedded_model(bad), bad


# --- the model index, read from outside Altium -------------------------------------------

# A REAL `Library/Models/Data` blob, taken verbatim from a library this code embedded into twice
# on 2026-07-25. Two records, same model, which is the accumulation bug this parser exists to
# detect.
REAL_INDEX = (
    b"\x9e\x00\x00\x00EMBED=TRUE|MODELSOURCE=Undefined|ID={261B8884-5385-4C61-A93C-4744C2E89326}"
    b"|ROTX=0.000|ROTY=0.000|ROTZ=0.000|DZ=0|CHECKSUM=-1180150305|NAME=TPD6E05U06RVZR.stp\x00"
    b"\x9e\x00\x00\x00EMBED=TRUE|MODELSOURCE=Undefined|ID={822CAAE1-F3A2-431C-9DE0-7EE43FE925AB}"
    b"|ROTX=0.000|ROTY=0.000|ROTZ=0.000|DZ=0|CHECKSUM=-1180150305|NAME=TPD6E05U06RVZR.stp\x00"
)


def test_the_real_model_index_parses_into_records():
    from stockroom.altium.embed3d import parse_model_index

    records = parse_model_index(REAL_INDEX)
    assert len(records) == 2
    assert records[0]["NAME"] == "TPD6E05U06RVZR.stp"
    assert records[0]["EMBED"] == "TRUE"
    assert records[0]["CHECKSUM"] == "-1180150305"
    assert records[0]["ID"] != records[1]["ID"], "each embed gets its own model id"


def test_an_empty_index_parses_to_nothing():
    from stockroom.altium.embed3d import parse_model_index

    assert parse_model_index(b"") == ()


def test_a_truncated_index_does_not_explode():
    # A library written by another tool, or a partial read, must not crash a readiness check.
    from stockroom.altium.embed3d import parse_model_index

    assert parse_model_index(b"\xff\xff\x00\x00short") == ()
    assert parse_model_index(b"\x05\x00\x00\x00") == ()


def test_model_names_are_reported_case_insensitively(tmp_path: Path, monkeypatch):
    from stockroom.altium.embed3d import model_name_present, parse_model_index

    records = parse_model_index(REAL_INDEX)
    assert model_name_present(records, "TPD6E05U06RVZR.stp")
    assert model_name_present(records, "tpd6e05u06rvzr.STP"), "Windows paths are case-insensitive"
    assert not model_name_present(records, "other.stp")


def test_a_second_embed_of_the_same_model_is_skipped_without_booting_altium(
    tmp_path: Path, parts, monkeypatch
):
    # The bug this closes, found by RUNNING the embed twice: Altium replaces the body but keeps the
    # superseded model payload, so every re-run added another 63 KB to a git-synced binary. The fix
    # is to notice the model is already there and do nothing, which also skips the Altium boot.
    lib, step = parts
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: dict(GOLDEN))
    monkeypatch.setattr(
        "stockroom.altium.embed3d.read_model_index",
        lambda _p: parse_model_index_for_name(step.name),
    )
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "DONE added=1 removed=0"))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path)
    assert res.ok
    assert "already" in res.detail.lower()
    assert not drv.calls, "an Altium boot is expensive and was not needed"


def test_replace_forces_the_embed_and_reports_the_superseded_payload(
    tmp_path: Path, parts, monkeypatch
):
    lib, step = parts
    seq = [dict(GOLDEN), {**GOLDEN, "Library/Models/1": 65536}]
    monkeypatch.setattr("stockroom.altium.embed3d.ole_streams", lambda _p: seq.pop(0))
    monkeypatch.setattr(
        "stockroom.altium.embed3d.read_model_index",
        lambda _p: parse_model_index_for_name(step.name),
    )
    drv = FakeDriver(tmp_path, RunOutcome("ok", "", "embedded x\nDONE added=1 removed=1"))
    res = embed_model(lib, step, driver=drv, workdir=tmp_path, replace=True)
    assert drv.calls, "replace must actually run"
    assert res.ok and res.embedded == 2
    assert res.orphaned == 1
    assert "superseded" in res.detail


def parse_model_index_for_name(name: str):
    from stockroom.altium.embed3d import parse_model_index

    body = f"EMBED=TRUE|NAME={name}".encode()
    return parse_model_index(len(body).to_bytes(4, "little") + body)


def test_read_model_index_on_the_real_probe_output():
    from stockroom.altium.embed3d import model_name_present, read_model_index

    good = _PROBE_OUT / "board-add.PcbLib"
    if not good.exists():
        pytest.skip("needs probe output from a machine with Altium")
    records = read_model_index(good)
    assert model_name_present(records, "TPD6E05U06RVZR.stp"), records
