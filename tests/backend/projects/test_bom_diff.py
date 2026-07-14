"""M7d: BOM revision diff (parts added/removed/changed, cost delta, lead delta).

Ports the retired app's revision-diff functions behavior-for-behavior. Pure compute over
row lists; `project_bom_diff` binds a project's OWN git repo, reconstructs the BOM at a
revision through the byte-preserving reader (identity only, no pricing), and diffs it
against the current build.
"""

import subprocess

from stockroom.projects.bom_diff import (
    _bom_line_key,
    bom_diff,
    bom_diff_cost,
    bom_diff_lead,
    bom_diff_csv,
    project_bom_diff,
)


def _r(mpn="", value="", footprint="", qty=1, **extra):
    return {"mpn": mpn, "value": value, "footprint": footprint, "qty": qty, **extra}


# -- line identity -------------------------------------------------------------
def test_line_key_prefers_mpn_then_value_footprint():
    assert _bom_line_key(_r(mpn="ABC")) == ("MPN", "ABC")
    assert _bom_line_key(_r(mpn="abc")) == ("MPN", "ABC")  # case-folded
    assert _bom_line_key(_r(value="10k", footprint="R_0402")) == ("VF", "10k", "r_0402")


# -- parts diff ----------------------------------------------------------------
def test_bom_diff_added_removed_changed():
    a = [_r(mpn="KEEP", qty=2), _r(mpn="GONE", qty=1), _r(mpn="GROW", qty=1)]
    b = [_r(mpn="KEEP", qty=2), _r(mpn="NEW", qty=3), _r(mpn="GROW", qty=4)]
    d = bom_diff(a, b)
    assert [x["mpn"] for x in d["added"]] == ["NEW"]
    assert [x["mpn"] for x in d["removed"]] == ["GONE"]
    assert len(d["changed"]) == 1
    ch = d["changed"][0]
    assert ch["mpn"] == "GROW"
    assert ch["from_qty"] == 1 and ch["to_qty"] == 4 and ch["delta"] == 3
    assert d["unchanged"] == 1  # KEEP


def test_bom_diff_value_edit_on_an_mpnd_part_is_not_add_remove():
    # Same MPN, different value: it groups by MPN, so it is NOT seen as add+remove.
    a = [_r(mpn="U1", value="OLD", qty=1)]
    b = [_r(mpn="U1", value="NEW", qty=1)]
    d = bom_diff(a, b)
    assert d["added"] == [] and d["removed"] == [] and d["unchanged"] == 1


# -- cost delta ----------------------------------------------------------------
def test_bom_diff_cost_prices_added_and_changed_from_rev_b():
    a = [_r(mpn="GROW", qty=1)]
    b = [_r(mpn="GROW", qty=3, unit_price=2.0), _r(mpn="NEW", qty=2, unit_price=1.5)]
    cost = bom_diff_cost(a, b)
    # GROW: +2 units * $2 = $4 ; NEW: +2 units * $1.5 = $3 ; delta = $7
    assert cost["added_cost"] == 3.0
    assert cost["changed_cost"] == 4.0
    assert cost["delta"] == 7.0
    assert cost["priced"] is True


def test_bom_diff_cost_removed_line_is_unpriced_not_negative():
    a = [_r(mpn="GONE", qty=5, unit_price=9.0)]  # only in A -> no price to use
    b = []
    cost = bom_diff_cost(a, b)
    assert cost["removed_unpriced"] == 1
    assert cost["delta"] == 0.0
    assert cost["priced"] is False  # rev B carried no price at all


# -- lead delta ----------------------------------------------------------------
def test_bom_diff_lead_flags_a_new_part_on_the_critical_path():
    a = [_r(mpn="OLD", qty=1, lead_time="4 Weeks")]
    b = [_r(mpn="OLD", qty=1, lead_time="4 Weeks"), _r(mpn="NEW", qty=1, lead_time="20 Weeks")]
    lead = bom_diff_lead(a, b)
    assert lead["added_max_weeks"] == 20
    assert lead["added_critical_mpn"] == "NEW"
    assert lead["build_max_weeks"] == 20
    assert lead["on_critical_path"] is True


# -- csv -----------------------------------------------------------------------
def test_bom_diff_csv_carries_cost_and_lead_when_present():
    a = [_r(mpn="GROW", qty=1)]
    b = [_r(mpn="GROW", qty=3, unit_price=2.0, lead_time="1 Week"),
         _r(mpn="NEW", qty=2, unit_price=1.5, lead_time="20 Weeks")]
    d = bom_diff(a, b)
    csv = bom_diff_csv(d, b)
    header = csv.splitlines()[0]
    assert header.startswith("Change,MPN,Value,From Qty,To Qty,Delta")
    assert "Cost Delta" in header
    assert "Lead (wks)" in header  # an added line carries lead


# -- the project orchestrator (real git) ---------------------------------------
def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def _make_git_project(dir_path, sheet_body):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    (dir_path / "board.kicad_sch").write_text(
        "(kicad_sch\n" + sheet_body + ")\n", encoding="utf-8"
    )
    _git(dir_path, "init", "-b", "main")
    _git(dir_path, "config", "user.email", "t@t")
    _git(dir_path, "config", "user.name", "t")
    _git(dir_path, "add", ".")
    _git(dir_path, "commit", "-m", "rev A")
    head = subprocess.run(["git", "-C", str(dir_path), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    return dir_path, head


def _sym(ref, value, lib="Device:R", mpn=None):
    lines = [
        "  (symbol",
        f'    (lib_id "{lib}")',
        f'    (property "Reference" "{ref}" (at 0 0 0))',
        f'    (property "Value" "{value}" (at 0 0 0))',
    ]
    if mpn:
        lines.append(f'    (property "MPN" "{mpn}" (at 0 0 0))')
    lines.append("  )")
    return "\n".join(lines) + "\n"


def test_project_bom_diff_reconstructs_rev_a_and_diffs_against_the_working_tree(tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board",
                                    _sym("R1", "10k") + _sym("R2", "10k"))
    # working tree: add a third 10k and a new IC
    (proj / "board.kicad_sch").write_text(
        "(kicad_sch\n" + _sym("R1", "10k") + _sym("R2", "10k") + _sym("R3", "10k")
        + _sym("U1", "MCU", lib="Device:U", mpn="STM32") + ")\n", encoding="utf-8")

    res = project_bom_diff(str(proj), ["board.kicad_sch"], str(proj), rev_a, "")
    assert res["rev_a"] == rev_a
    assert res["rev_b"] == "current"
    # the 10k line grew from 2 to 3, the STM32 IC is new
    changed = {c["value"]: c for c in res["changed"]}
    assert changed["10k"]["from_qty"] == 2 and changed["10k"]["to_qty"] == 3
    assert any(x["mpn"] == "STM32" for x in res["added"])
    assert res["a_sheets_found"] == 1


def test_project_bom_diff_uses_current_priced_rows_for_the_cost_delta(tmp_path):
    proj, rev_a = _make_git_project(tmp_path / "board", _sym("R1", "10k"))
    # current build adds a priced IC (as the cached priced rows would carry)
    current = [
        {"mpn": "", "value": "10k", "footprint": "", "refs": ["R1"], "qty": 1},
        {"mpn": "STM32", "value": "MCU", "footprint": "", "refs": ["U1"], "qty": 1,
         "unit_price": 3.5, "extended": 3.5},
    ]
    res = project_bom_diff(str(proj), ["board.kicad_sch"], str(proj), rev_a, "",
                           current_rows=current)
    assert any(x["mpn"] == "STM32" for x in res["added"])
    assert res["cost"]["added_cost"] == 3.5  # the new IC priced from the current build
    assert res["cost"]["delta"] == 3.5
