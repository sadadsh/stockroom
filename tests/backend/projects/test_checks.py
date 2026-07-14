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
        sheet_paths=["board.kicad_sch", "power.kicad_sch"],  # power is a sub-sheet
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
