"""M7b: structured ERC + DRC over a registered KiCad project.

The JSON parsers are pure and independently tested (no kicad-cli). The
project_checks orchestrator is tested with the runners monkeypatched, so it never
shells out: it verifies root-sheet selection, per-board DRC, and the combined
summary that Overview + the Buildability verdict (M7g) read.
"""

from __future__ import annotations

import json

from stockroom.projects import checks


# ---- parse_erc_json ---------------------------------------------------------


def test_parse_erc_json_flattens_sheets_and_sorts_by_severity():
    doc = {
        "sheets": [
            {
                "path": "/root.kicad_sch",
                "violations": [
                    {"severity": "warning", "type": "unconnected",
                     "description": "Pin not connected",
                     "items": [{"description": "U1 pin 3", "pos": {"x": 10, "y": 20}}]},
                    {"severity": "error", "type": "power",
                     "description": "Input power pin not driven", "items": []},
                ],
            }
        ]
    }
    out = checks.parse_erc_json(json.dumps(doc))
    assert [f["severity"] for f in out] == ["error", "warning"]  # error sorts first
    assert out[0]["rule"] == "power"
    assert out[1]["where"] == "U1 pin 3 (10, 20)"


def test_parse_erc_json_tolerates_a_top_level_violations_shape():
    doc = {"violations": [{"severity": "warning", "type": "x", "description": "y"}]}
    out = checks.parse_erc_json(json.dumps(doc))
    assert len(out) == 1 and out[0]["rule"] == "x"


def test_parse_erc_json_on_garbage_is_empty_not_a_crash():
    assert checks.parse_erc_json("not json") == []
    assert checks.parse_erc_json("") == []


# ---- parse_drc_json ---------------------------------------------------------


def test_parse_drc_json_merges_all_three_sections():
    doc = {
        "violations": [{"severity": "error", "type": "clearance", "description": "too close"}],
        "unconnected_items": [{"severity": "warning", "type": "unconnected", "description": "net N"}],
        "schematic_parity": [{"severity": "error", "type": "parity", "description": "extra pad"}],
    }
    out = checks.parse_drc_json(json.dumps(doc))
    rules = {f["rule"] for f in out}
    assert rules == {"clearance", "unconnected", "parity"}
    assert [f["severity"] for f in out][:2] == ["error", "error"]  # errors first


def test_summarize_counts_by_severity_and_rule():
    findings = [
        {"severity": "error", "rule": "a"},
        {"severity": "warning", "rule": "a"},
        {"severity": "warning", "rule": "b"},
    ]
    s = checks.summarize(findings)
    assert s["total"] == 3 and s["errors"] == 1 and s["warnings"] == 2
    assert s["by_rule"] == {"a": 2, "b": 1}


# ---- project_checks orchestrator (runners monkeypatched) --------------------


def _fake_runs(monkeypatch, erc_result, drc_by_board):
    seen = {"erc": [], "drc": []}

    def fake_erc(path, cli):
        seen["erc"].append(str(path))
        return dict(erc_result)

    def fake_drc(path, cli):
        seen["drc"].append(str(path))
        return dict(drc_by_board[__import__("pathlib").Path(path).name])

    monkeypatch.setattr(checks, "run_erc", fake_erc)
    monkeypatch.setattr(checks, "run_drc", fake_drc)
    return seen


def _clean(errors=0, warnings=0):
    findings = ([{"severity": "error", "rule": "e"}] * errors
                + [{"severity": "warning", "rule": "w"}] * warnings)
    return {"ok": True, "findings": findings, "summary": checks.summarize(findings), "error": ""}


def test_project_checks_runs_erc_on_the_root_sheet_matching_the_pro_stem(monkeypatch):
    seen = _fake_runs(
        monkeypatch,
        _clean(errors=1),
        {"board.kicad_pcb": _clean(warnings=2)},
    )
    result = checks.project_checks(
        root="/ext/board",
        pro_path="board.kicad_pro",
        board_paths=["board.kicad_pcb"],
        # The root (board, stem == pro stem) is deliberately NOT first, so a regression
        # to "always the first sheet" runs on power and turns this test red.
        sheet_paths=["power.kicad_sch", "board.kicad_sch"],
        cli="/fake/kicad-cli",
        name="board",
    )
    # ERC runs ONCE, on the root sheet (stem == pro stem), never the sub-sheet.
    assert len(seen["erc"]) == 1 and seen["erc"][0].endswith("board.kicad_sch")
    assert result["erc"]["sheet"] == "board.kicad_sch"
    assert result["drc"][0]["board"] == "board.kicad_pcb"
    # combined summary sums erc(1 error) + drc(2 warnings); ran_at + project stamped.
    assert result["summary"] == {"ok": True, "errors": 1, "warnings": 2, "total": 3, "checked": 2}
    assert result["project"] == "board" and result["ran_at"]


def test_project_checks_falls_back_to_the_first_sheet_when_no_pro_stem_matches(monkeypatch):
    seen = _fake_runs(monkeypatch, _clean(), {})
    result = checks.project_checks(
        root="/ext/x", pro_path="", board_paths=[],
        sheet_paths=["only.kicad_sch"], cli="c", name="x",
    )
    assert seen["erc"][0].endswith("only.kicad_sch")
    assert result["drc"] == [] and result["summary"]["checked"] == 1


def test_project_checks_over_a_project_with_no_checkable_files_is_not_a_clean_pass(monkeypatch):
    # A .kicad_pro-only project (no schematic, no board) registers fine, but running
    # checks verifies NOTHING. That must never read as a clean pass: checked==0 forces
    # summary.ok False, so no consumer (the badge, the M7g verdict) can call it Clean.
    seen = _fake_runs(monkeypatch, _clean(), {})
    result = checks.project_checks(
        root="/ext/x", pro_path="x.kicad_pro", board_paths=[],
        sheet_paths=[], cli="c", name="x",
    )
    assert seen["erc"] == [] and seen["drc"] == []  # nothing was actually run
    assert result["erc"] is None and result["drc"] == []
    assert result["summary"]["checked"] == 0
    assert result["summary"]["ok"] is False  # nothing checked is not a pass


def test_project_checks_marks_the_run_not_ok_when_a_check_fails_to_produce_a_report(monkeypatch):
    # A failed kicad-cli run (ok:false) must NOT read as a clean board: the combined
    # ok is false, and the failed check's (absent) counts are excluded.
    _fake_runs(
        monkeypatch,
        {"ok": False, "error": "kicad-cli produced no report", "findings": [], "summary": checks.summarize([])},
        {"board.kicad_pcb": _clean(errors=3)},
    )
    result = checks.project_checks(
        root="/ext/board", pro_path="board.kicad_pro", board_paths=["board.kicad_pcb"],
        sheet_paths=["board.kicad_sch"], cli="c", name="board",
    )
    assert result["summary"]["ok"] is False
    assert result["summary"]["errors"] == 3  # only the DRC that ran contributes
    assert result["erc"]["ok"] is False


# ---- _run_json_check honest-completion guard (real runner, faked kicad-cli) --
# These exercise the REAL run_erc/run_drc (NOT monkeypatched away): the guard that a
# missing/empty/corrupt report is never a clean board. Faking subprocess.run keeps them
# deterministic and cross-platform while still running the guard + parser dispatch.
import types as _types  # noqa: E402


def _fake_cli(monkeypatch, *, writes=None, returncode=0, stdout="", raises=None):
    def fake_run(cmd, **kw):
        if raises is not None:
            raise raises
        if writes is not None:
            out = __import__("pathlib").Path(cmd[cmd.index("--output") + 1])
            out.write_text(writes, encoding="utf-8")
        return _types.SimpleNamespace(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(checks.subprocess, "run", fake_run)


def test_run_erc_with_no_cli_is_not_a_clean_board():
    r = checks.run_erc("/x/board.kicad_sch", "")
    assert r["ok"] is False and "not found" in r["error"] and r["findings"] == []


def test_run_erc_with_no_report_written_is_not_a_clean_board(monkeypatch):
    # kicad-cli ran but wrote no report (a crash / bad file). NOT a clean board.
    _fake_cli(monkeypatch, writes=None, returncode=1, stdout="could not open board")
    r = checks.run_erc("/x/board.kicad_sch", "/fake/kicad-cli")
    assert r["ok"] is False and r["findings"] == []
    assert "could not open board" in r["error"]


def test_run_drc_with_a_corrupt_report_is_not_a_clean_board(monkeypatch):
    # A truncated/garbage report is a failure, not a clean board with zero findings.
    _fake_cli(monkeypatch, writes="this is not json{", returncode=0)
    r = checks.run_drc("/x/board.kicad_pcb", "/fake/kicad-cli")
    assert r["ok"] is False and "valid JSON" in r["error"]


def test_run_erc_when_the_spawn_fails_is_not_a_clean_board(monkeypatch):
    _fake_cli(monkeypatch, raises=OSError("no such executable"))
    r = checks.run_erc("/x/board.kicad_sch", "/fake/kicad-cli")
    assert r["ok"] is False and "no such executable" in r["error"]


def test_run_erc_parses_a_valid_report_as_ok(monkeypatch):
    doc = {"sheets": [{"violations": [
        {"severity": "error", "type": "power", "description": "input not driven"}]}]}
    _fake_cli(monkeypatch, writes=json.dumps(doc), returncode=0)
    r = checks.run_erc("/x/board.kicad_sch", "/fake/kicad-cli")
    assert r["ok"] is True and len(r["findings"]) == 1 and r["findings"][0]["rule"] == "power"
