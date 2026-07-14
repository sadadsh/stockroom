"""M7d: BOM revision diff - what a revision changed, and what it costs / how it moves lead.

Pure COMPUTE, clean-lifted from the retired PyQt app's LibraryManager, plus a
`project_bom_diff` orchestrator that binds a registered project's OWN git repo, reconstructs
the BOM at an older revision through Stockroom's byte-preserving sexp reader (identity only,
no network, no pricing - a diff compares parts and quantity, not cost), and diffs it against
the current build.

Lines match by MPN (case-folded), else value+footprint - the same grouping the consolidated
BOM uses, so a value edited on an MPN'd part is not seen as add+remove. Cost and lead deltas
are read from the NEWER (rev B) side's own prices/leads: an added or grown line can be costed
from rev B, but a removed line exists only in the older, unpriced revision and is reported as
unpriced/unassessed, never silently one-sided.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from pathlib import Path

from stockroom.projects.bom import _bom_line_qty, _coerce_price, _lead_weeks
from stockroom.projects.procurement import bom_lead_time


def _bom_line_key(r):
    """Identity of a BOM line for diffing: its MPN (case-folded) when present, else
    value+footprint - the same grouping the consolidated BOM uses, so a value edited on an
    MPN'd part is not seen as add+remove."""
    mpn = (r.get("mpn") or "").strip()
    if mpn:
        return ("MPN", mpn.upper())
    return ("VF", (r.get("value") or "").strip().lower(),
            (r.get("footprint") or "").strip().lower())


def _bom_index(rows) -> dict:
    """Aggregate BOM rows by line key -> {qty, mpn, value, footprint}. Sums duplicate lines
    so a part split across two rows still compares by its true total quantity."""
    idx: dict = {}
    for r in rows or []:
        k = _bom_line_key(r)
        e = idx.setdefault(k, {"qty": 0, "mpn": (r.get("mpn") or "").strip(),
                               "value": (r.get("value") or "").strip(),
                               "footprint": (r.get("footprint") or "").strip()})
        e["qty"] += _bom_line_qty(r)
    return idx


def bom_diff(rows_a, rows_b) -> dict:
    """Compare two BOMs (rev A -> rev B). Lines match by MPN, else value+footprint. Returns
    {added, removed, changed, unchanged, csv}: `added` are lines only in B, `removed` only in
    A, `changed` are lines whose quantity moved (each with from_qty/to_qty/delta), `unchanged`
    the count of identical-quantity lines."""
    a, b = _bom_index(rows_a), _bom_index(rows_b)
    added, removed, changed, unchanged = [], [], [], 0
    for k, e in b.items():
        if k not in a:
            added.append({"mpn": e["mpn"], "value": e["value"],
                          "footprint": e["footprint"], "qty": e["qty"]})
    for k, e in a.items():
        if k not in b:
            removed.append({"mpn": e["mpn"], "value": e["value"],
                            "footprint": e["footprint"], "qty": e["qty"]})
    for k, ea in a.items():
        if k not in b:
            continue
        eb = b[k]
        if ea["qty"] != eb["qty"]:
            changed.append({"mpn": eb["mpn"] or ea["mpn"], "value": eb["value"] or ea["value"],
                            "footprint": eb["footprint"] or ea["footprint"],
                            "from_qty": ea["qty"], "to_qty": eb["qty"],
                            "delta": eb["qty"] - ea["qty"]})
        else:
            unchanged += 1

    def _lbl(r):
        return (r["mpn"] or r["value"]).lower()

    added.sort(key=_lbl)
    removed.sort(key=_lbl)
    changed.sort(key=_lbl)

    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["Change", "MPN", "Value", "From Qty", "To Qty", "Delta"])
    for r in added:
        w.writerow(["Added", r["mpn"], r["value"], 0, r["qty"], r["qty"]])
    for r in removed:
        w.writerow(["Removed", r["mpn"], r["value"], r["qty"], 0, -r["qty"]])
    for r in changed:
        w.writerow(["Changed", r["mpn"], r["value"], r["from_qty"], r["to_qty"], r["delta"]])
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged, "csv": buf.getvalue()}


def bom_diff_cost(rows_a, rows_b) -> dict:
    """Cost the change a revision makes (rev A -> rev B), from the NEWER revision's own
    prices. Rev B is the current, priced build; rev A is the older side, reconstructed
    offline WITHOUT pricing. So every line B ADDS or grows can be costed from B's price, but a
    line B REMOVES exists only in A (no price anywhere) and cannot - reported in
    `removed_unpriced`. Uses each line's stored per-board unit_price (the qty-1 unit, the
    stable figure for a per-board delta). Returns {delta, added_cost, changed_cost,
    removed_unpriced, priced, currency}."""
    a, b = _bom_index(rows_a), _bom_index(rows_b)
    bprice: dict = {}  # line key -> per-board unit price
    for r in rows_b or []:
        k = _bom_line_key(r)
        if k not in bprice:
            bprice[k] = _coerce_price(r.get("unit_price"))
    added_cost = changed_cost = 0.0
    for k, eb in b.items():
        u = bprice.get(k)
        if u is None:
            continue
        if k not in a:  # added: whole line is new
            added_cost += u * eb["qty"]
        elif a[k]["qty"] != eb["qty"]:  # changed: only the qty delta
            changed_cost += u * (eb["qty"] - a[k]["qty"])
    removed_unpriced = sum(1 for k in a if k not in b)  # only in A -> no price to use
    priced = any(u is not None for u in bprice.values())
    return {"delta": round(added_cost + changed_cost, 2),
            "added_cost": round(added_cost, 2), "changed_cost": round(changed_cost, 2),
            "removed_unpriced": removed_unpriced, "priced": priced, "currency": "USD"}


def bom_diff_lead(rows_a, rows_b) -> dict:
    """Assess how a revision (rev A -> rev B) changes the procurement critical path. A lead
    delta is presence-sensitive: a part's lead matters because it is in the BOM at all. So only
    the lines rev B ADDS introduce new lead exposure (from rev B's own `lead_time`); a removed
    line exists only in the older, unpriced rev A and is reported as `removed_unassessed`; a
    qty-only change adds no new lead. Returns {added_max_weeks, added_critical_mpn,
    build_max_weeks, build_critical_mpn, on_critical_path, removed_unassessed, any}."""
    a, b = _bom_index(rows_a), _bom_index(rows_b)
    lead_by_key: dict = {}  # line key -> longest lead (weeks)
    for r in rows_b or []:
        w = _lead_weeks(r.get("lead_time"))
        if w is None:
            continue
        k = _bom_line_key(r)
        if lead_by_key.get(k) is None or w > lead_by_key[k]:
            lead_by_key[k] = w
    added_max = None
    added_mpn = None
    for k, eb in b.items():
        if k in a:  # not an added line -> no new lead
            continue
        w = lead_by_key.get(k)
        if w is None:
            continue
        if added_max is None or w > added_max:
            added_max = w
            added_mpn = (eb["mpn"] or eb["value"] or "").strip() or None
    build = bom_lead_time(rows_b)
    on_cp = (added_max is not None and build["max_weeks"] is not None
             and added_max >= build["max_weeks"])
    removed_unassessed = sum(1 for k in a if k not in b)
    return {"added_max_weeks": added_max, "added_critical_mpn": added_mpn,
            "build_max_weeks": build["max_weeks"], "build_critical_mpn": build["critical_mpn"],
            "on_critical_path": on_cp, "removed_unassessed": removed_unassessed,
            "any": build["any"]}


def bom_diff_csv(d, rows_b) -> str:
    """The BOM diff (from bom_diff) as a CSV, extending the parts diff with a per-line 'Cost
    Delta' column when rev B carries prices, and a 'Lead (wks)' column when any ADDED line
    carries a lead. Each added line costs qty*unit, each changed line delta*unit, read from rev
    B's own price (re-keyed by line identity) so the column sums to bom_diff_cost's headline; a
    removed line's cost cell is blank. When rev B has no price AND no added line carries lead,
    the output matches bom_diff's plain form. Rows are ordered added, removed, changed."""
    import csv as _csv
    import io as _io
    bprice: dict = {}
    blead: dict = {}  # line key -> longest lead (weeks)
    for r in rows_b or []:
        k = _bom_line_key(r)
        if k not in bprice:
            bprice[k] = _coerce_price(r.get("unit_price"))
        w_ = _lead_weeks(r.get("lead_time"))
        if w_ is not None and (blead.get(k) is None or w_ > blead[k]):
            blead[k] = w_
    priced = any(u is not None for u in bprice.values())
    added_keys = {_bom_line_key(e) for e in d["added"]}
    has_lead = any(blead.get(k) is not None for k in added_keys)

    def cost(entry, qty):
        u = bprice.get(_bom_line_key(entry))
        return None if u is None else round(u * qty, 2)

    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    head = ["Change", "MPN", "Value", "From Qty", "To Qty", "Delta"]
    if priced:
        head.append("Cost Delta")
    if has_lead:
        head.append("Lead (wks)")
    w.writerow(head)

    def row(change, e, frm, to, dq, c, lead):
        cells = [change, e["mpn"], e["value"], frm, to, dq]
        if priced:
            cells.append("" if c is None else f"{c:.2f}")
        if has_lead:
            cells.append("" if lead is None else lead)
        return cells

    for e in d["added"]:
        w.writerow(row("Added", e, 0, e["qty"], e["qty"], cost(e, e["qty"]),
                       blead.get(_bom_line_key(e))))
    for e in d["removed"]:
        w.writerow(row("Removed", e, e["qty"], 0, -e["qty"], None, None))
    for e in d["changed"]:
        w.writerow(row("Changed", e, e["from_qty"], e["to_qty"], e["delta"],
                       cost(e, e["delta"]), None))
    return buf.getvalue()


# -- the project orchestrator --------------------------------------------------

# Sentinels for rev B meaning "the current build" (the working tree / cached priced BOM)
# rather than a committed revision.
_CURRENT = {"", "current", "working", "head~0-working"}


def _repo_rels(root: Path, git_root: Path, sheet_paths) -> list:
    """The project's current sheet paths, made relative to the project's git repo root (so
    show_file can read each at a revision). Sheets outside the repo are dropped."""
    rels = []
    root_r = root.resolve()
    git_r = git_root.resolve()
    for s in (sheet_paths or []):
        try:
            rels.append((root_r / s).resolve().relative_to(git_r).as_posix())
        except ValueError:
            continue
    return rels


def project_bom_diff(root, sheet_paths, git_root, rev_a, rev_b="", current_rows=None) -> dict:
    """Diff a registered project's BOM between two revisions of its own git repo (M7d).

    `rev_a` is the older side, reconstructed offline (identity only) from the repo blobs.
    `rev_b` is the newer side: a blank / 'current' sentinel means the current build - the
    cached priced rows when `current_rows` is given (so cost/lead deltas are meaningful), else
    the live working-tree BOM read unpriced; any other value is reconstructed as a committed
    revision. Returns {rev_a, rev_b, added, removed, changed, unchanged, cost, lead, csv,
    a_sheets_found, b_sheets_found}. Never raises on a bad blob: a revision that cannot be read
    yields no components for that side (surfaced via the *_sheets_found counts), never a crash."""
    from stockroom.projects.bom import bom_from_project, bom_rows_at_ref
    from stockroom.vcs.repo import GitRepo

    root_p, git_p = Path(root), Path(git_root)
    repo = GitRepo(git_p)
    rels = _repo_rels(root_p, git_p, sheet_paths)

    def _show(rev):
        return lambda rel: repo.show_file(rev, rel)

    a_built = bom_rows_at_ref(rels, _show(rev_a))
    rows_a = a_built["rows"]

    b_sheets_found = None
    if (rev_b or "").strip().lower() in _CURRENT:
        rev_b_label = "current"
        if current_rows is not None:
            rows_b = current_rows
        else:
            abs_sheets = [str(root_p / s) for s in (sheet_paths or [])]
            rows_b = bom_from_project(abs_sheets)["rows"]
    else:
        rev_b_label = rev_b
        b_built = bom_rows_at_ref(rels, _show(rev_b))
        rows_b = b_built["rows"]
        b_sheets_found = b_built["sheets_found"]

    d = bom_diff(rows_a, rows_b)
    cost = bom_diff_cost(rows_a, rows_b)
    lead = bom_diff_lead(rows_a, rows_b)
    return {"rev_a": rev_a, "rev_b": rev_b_label,
            "added": d["added"], "removed": d["removed"], "changed": d["changed"],
            "unchanged": d["unchanged"], "cost": cost, "lead": lead,
            "csv": bom_diff_csv(d, rows_b),
            "a_sheets_found": a_built["sheets_found"], "b_sheets_found": b_sheets_found}
