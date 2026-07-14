"""M7d: BOM procurement compute (lead time, sourcing/stock risk, per-line orderability).

Ports the retired app's PROC-* procurement functions behavior-for-behavior onto the
Stockroom BOM row schema. Pure compute: no kicad-cli, no network. A row that was never
priced carries no lifecycle/stock/lead, and absence of that data is NEVER a risk.
"""

from stockroom.projects.bom import _lead_weeks, _row_is_passive
from stockroom.projects.procurement import (
    bom_lead_time,
    bom_line_is_populated,
    bom_line_is_priced,
    bom_line_stock_risk,
    bom_procurement_summary,
    bom_sourcing_risks,
    project_procurement,
)


# -- lead-time normalization ---------------------------------------------------
def test_lead_weeks_parses_the_provider_shapes():
    assert _lead_weeks("16 Weeks") == 16
    assert _lead_weeks(12) == 12  # DigiKey numeric weeks
    assert _lead_weeks("14 days") == 2  # days round UP to whole weeks
    assert _lead_weeks("8 days") == 2
    assert _lead_weeks("In Stock") is None  # unparseable -> unknown, not a warning
    assert _lead_weeks("") is None
    assert _lead_weeks(None) is None
    assert _lead_weeks(-3) is None  # garbage
    assert _lead_weeks(0) == 0  # in stock, not a lead risk
    assert _lead_weeks(True) is None  # a stray bool is not a duration


def test_bom_lead_time_finds_the_critical_path():
    rows = [
        {"mpn": "A", "lead_time": "4 Weeks"},
        {"mpn": "B", "lead_time": "16 Weeks"},
        {"mpn": "C", "lead_time": "In Stock"},  # no parseable lead -> ignored
        {"mpn": "D"},  # never priced -> ignored
    ]
    lead = bom_lead_time(rows)
    assert lead["max_weeks"] == 16
    assert lead["critical_mpn"] == "B"
    assert lead["with_lead"] == 2
    assert lead["any"] is True


def test_bom_lead_time_empty_when_no_line_carries_lead():
    lead = bom_lead_time([{"mpn": "A"}, {"mpn": "B", "lead_time": "In Stock"}])
    assert lead == {"max_weeks": None, "critical_mpn": None, "with_lead": 0, "any": False}


# -- sourcing risk -------------------------------------------------------------
def test_sourcing_risks_flag_not_active_no_stock_and_short():
    rows = [
        {"mpn": "EOL", "qty": 1, "lifecycle": "Obsolete", "stock": 5000},  # not active
        {"mpn": "DEAD", "qty": 2, "stock": 0},  # no stock
        {"mpn": "SHORT", "qty": 100, "stock": 50},  # insufficient for the run
        {"mpn": "OK", "qty": 1, "lifecycle": "Active", "stock": 9000},  # fine
        {"mpn": "UNKNOWN", "qty": 1},  # never priced -> not a risk
    ]
    risks = bom_sourcing_risks(rows, boards=1)
    assert risks["not_active"] == 1
    assert risks["no_stock"] == 1
    assert risks["insufficient_stock"] == 1
    assert set(risks["risky_mpns"]) == {"EOL", "DEAD", "SHORT"}
    assert risks["any"] is True


def test_sourcing_risks_scale_stock_coverage_by_boards():
    # 60 in stock covers 1 board (qty 50) but not a run of 2 (needs 100).
    rows = [{"mpn": "X", "qty": 50, "stock": 60}]
    assert bom_sourcing_risks(rows, boards=1)["insufficient_stock"] == 0
    assert bom_sourcing_risks(rows, boards=2)["insufficient_stock"] == 1


def test_sourcing_risks_none_when_clean():
    risks = bom_sourcing_risks([{"mpn": "A", "qty": 1, "lifecycle": "Active", "stock": 100}])
    assert risks["any"] is False
    assert risks["risky_mpns"] == []


# -- per-line stock risk -------------------------------------------------------
def test_line_stock_risk_err_warn_and_none():
    assert bom_line_stock_risk({"qty": 2, "stock": 0}, 1)["kind"] == "err"
    short = bom_line_stock_risk({"qty": 100, "stock": 50}, 1)
    assert short["kind"] == "warn"
    assert short["required"] == 100
    assert short["available"] == 50
    assert short["short"] is True
    ok = bom_line_stock_risk({"qty": 1, "stock": 9000}, 1)
    assert ok["kind"] is None
    unknown = bom_line_stock_risk({"qty": 1}, 1)  # never priced
    assert unknown["kind"] is None
    assert unknown["available"] is None


# -- populated / priced predicates --------------------------------------------
def test_line_predicates():
    assert bom_line_is_populated({"mpn": "A"}) is True
    assert bom_line_is_populated({"value": "10k"}) is True
    assert bom_line_is_populated({"mpn": "", "value": ""}) is False
    assert bom_line_is_priced({"extended": 1.5}) is True
    assert bom_line_is_priced({"unit_price": "$0.10"}) is True
    assert bom_line_is_priced({"mpn": "A"}) is False


def test_row_is_passive():
    assert _row_is_passive({"refs": ["R1"]}) is True
    assert _row_is_passive({"refs": ["C3"]}) is True
    assert _row_is_passive({"refs": ["U1"]}) is False
    assert _row_is_passive({"refs": []}) is False


# -- procurement summary line --------------------------------------------------
def test_procurement_summary_is_an_honest_digest():
    rows = [
        {"mpn": "A", "qty": 2, "unit_price": 1.0, "extended": 2.0, "lead_time": "16 Weeks"},
        {"mpn": "B", "qty": 1},  # unpriced
    ]
    s = bom_procurement_summary(rows, boards=1)
    assert s.startswith("BOM: ")
    assert "2 lines" in s
    assert "3 parts" in s  # 2 + 1
    assert "critical path 16 wk" in s
    assert "1 unpriced" in s


# -- the project orchestrator --------------------------------------------------
def _priced_bom(boards=1):
    """The shape ProjectOps.bom caches: a priced project BOM result."""
    return {
        "project": "Demo",
        "ran_at": "2026-07-13T00:00:00Z",
        "boards": boards,
        "priced": True,
        "line_count": 3,
        "component_count": 4,
        "lines": [
            {"mpn": "U1-EOL", "value": "REG", "refs": ["U1"], "qty": 1,
             "unit_price": 2.0, "extended": 2.0, "stock": 0, "lifecycle": "Obsolete",
             "lead_time": "20 Weeks", "source": "Mouser", "mouser_pn": "595-U1"},
            {"mpn": "U2", "value": "MCU", "refs": ["U2"], "qty": 1,
             "unit_price": 3.5, "extended": 3.5, "stock": 5000, "lifecycle": "Active",
             "source": "Mouser"},
            {"mpn": "", "value": "10k", "refs": ["R1", "R2"], "qty": 2, "basic": True},
        ],
        "summary": {"total_cost": 5.5, "priced_lines": 2, "unpriced_lines": 1,
                    "line_count": 3, "currency": "USD", "state": "partial", "priced": True},
    }


def test_project_procurement_from_a_cached_bom():
    proc = project_procurement(_priced_bom())
    assert proc["priced"] is True
    assert proc["boards"] == 1
    # per-line orderability rows preserve the BOM order and carry a stock-risk verdict
    lines = proc["lines"]
    assert len(lines) == 3
    assert lines[0]["mpn"] == "U1-EOL"
    assert lines[0]["stock_risk"]["kind"] == "err"  # 0 stock
    assert lines[0]["orderable"] is False  # priced but no stock
    assert lines[1]["orderable"] is True
    # roll-ups
    assert proc["risks"]["not_active"] == 1
    assert proc["risks"]["no_stock"] == 1
    assert proc["lead"]["max_weeks"] == 20
    assert proc["lead"]["critical_mpn"] == "U1-EOL"
    assert proc["summary"].startswith("BOM: ")


def test_project_procurement_honest_when_not_built():
    # An unbuilt project (ran_at None) has nothing to procure: honest empty, never a crash.
    proc = project_procurement({"project": "Demo", "ran_at": None, "priced": False,
                                "boards": 1, "lines": [], "summary": None})
    assert proc["built"] is False
    assert proc["lines"] == []
    assert proc["risks"]["any"] is False
    assert proc["lead"]["any"] is False


def test_project_procurement_unpriced_build_has_no_cost_but_still_lists_lines():
    bom = {"project": "Demo", "ran_at": "2026-07-13T00:00:00Z", "priced": False, "boards": 1,
           "lines": [{"mpn": "A", "value": "v", "refs": ["U1"], "qty": 1}], "summary": None}
    proc = project_procurement(bom)
    assert proc["built"] is True
    assert proc["priced"] is False
    assert len(proc["lines"]) == 1
    assert proc["lines"][0]["stock_risk"]["kind"] is None  # unknown, not a risk
