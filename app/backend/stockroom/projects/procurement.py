"""M7d: BOM procurement compute - per-line orderability, sourcing/stock risk, lead time.

Pure COMPUTE, clean-lifted from the retired PyQt app's LibraryManager (a Qt hub that
cannot be imported), ported onto Stockroom's BOM row schema. Reads the fields the M7c
price adapter threads onto a priced line (stock / lifecycle / lead_time / source), and
treats absence of any of them as UNKNOWN, never a risk: a line that was never priced
does not warn. Offline, no kicad-cli, no network.

The `project_procurement` orchestrator takes a cached project BOM result (the shape
ProjectOps.bom returns) and produces the per-line + rolled-up procurement view the
Projects frontend renders. Honest states throughout: an unbuilt project procures
nothing; an unpriced build still lists its lines but with unknown risk.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from stockroom.projects.bom import (
    _bom_line_qty,
    _board_count,
    _lead_weeks,
    _coerce_price,
    bom_cost_at_qty,
    bom_cost_summary,
)


def bom_lead_time(rows) -> dict:
    """Find the critical-path part - the priced line with the longest manufacturer lead
    time - so an order can be planned around the part that gates it. Scans each row's
    threaded `lead_time` through `_lead_weeks`; lines without parseable lead data are
    ignored (absence is not a risk). Ties keep the first-seen line. Returns
    {max_weeks, critical_mpn, with_lead, any}; max_weeks/critical_mpn are None when no
    line carries lead data."""
    max_weeks = None
    critical = None
    with_lead = 0
    for r in rows:
        w = _lead_weeks(r.get("lead_time"))
        if w is None:
            continue
        with_lead += 1
        if max_weeks is None or w > max_weeks:
            max_weeks = w
            critical = (r.get("mpn") or r.get("value") or "").strip() or None
    return {"max_weeks": max_weeks, "critical_mpn": critical,
            "with_lead": with_lead, "any": max_weeks is not None}


def bom_sourcing_risks(rows, boards=1) -> dict:
    """Scan priced BOM rows for procurement risk - the failures worth catching BEFORE you
    order. A line is risky when its lifecycle is known and not Active (NRND / EOL /
    obsolete), when its stock is a known 0 (nothing to buy), or when known stock cannot
    cover the line's order quantity for the whole run. Lines with unknown lifecycle/stock
    (never priced) are NOT risks - absence of data is not a warning. per-board qty comes
    from 'qty' (project) or 'total_qty' (consolidated), scaled by `boards` so stock
    coverage is judged against the run you are actually ordering (a board count below 1 is
    treated as 1). Returns {not_active, no_stock, insufficient_stock, risky_mpns, any}."""
    n = _board_count(boards)
    not_active = no_stock = insufficient = 0
    risky: list = []
    for r in rows:
        flagged = False
        lc = (r.get("lifecycle") or "").strip()
        if lc and lc.lower() != "active":
            not_active += 1
            flagged = True
        stock = r.get("stock")
        if isinstance(stock, bool):  # a stray bool is not a stock count
            stock = None
        if isinstance(stock, (int, float)):
            qty = _bom_line_qty(r) * n  # order qty for the whole run
            if stock <= 0:
                no_stock += 1
                flagged = True
            elif qty and stock < qty:
                insufficient += 1
                flagged = True
        if flagged:
            risky.append((r.get("mpn") or r.get("value") or "").strip())
    # Preserve first-seen order, drop blanks and duplicates.
    seen: dict = {}
    for m in risky:
        if m and m not in seen:
            seen[m] = True
    return {"not_active": not_active, "no_stock": no_stock,
            "insufficient_stock": insufficient, "risky_mpns": list(seen),
            "any": bool(not_active or no_stock or insufficient)}


def bom_line_stock_risk(r, boards=1) -> dict:
    """Stock coverage for ONE BOM line at a build of `boards` boards - the per-row form of
    bom_sourcing_risks' stock test, so a tinted table row can never disagree with the
    headline No-Stock / Low-Stock counts. required = per_board_qty * boards (a board count
    below 1 folds to 1). available is the line's known integer stock, or None when stock is
    unknown (a line that was never priced) - unknown is NOT a risk. kind is 'err' when known
    stock is 0 (nothing to buy), 'warn' when a positive known stock is below required (a
    short line), else None. `short` is True for both risky cases."""
    n = _board_count(boards)
    required = _bom_line_qty(r) * n
    stock = r.get("stock")
    if isinstance(stock, bool) or not isinstance(stock, (int, float)):
        return {"kind": None, "required": required, "available": None, "short": False}
    # Branch on the RAW stock (not int(stock)) so the No-Stock vs Low-Stock split matches
    # bom_sourcing_risks EXACTLY - flooring first would call a fractional 0 < stock < 1 line
    # No-Stock while the aggregate counts it Low-Stock, breaking the invariant. `available`
    # reports the whole count for display (real stock is integral).
    available = int(stock)
    if stock <= 0:
        return {"kind": "err", "required": required, "available": available, "short": True}
    if required and stock < required:
        return {"kind": "warn", "required": required, "available": available, "short": True}
    return {"kind": None, "required": required, "available": available, "short": False}


def bom_line_is_populated(r) -> bool:
    """Whether a BOM line is a real, orderable/identifiable line - it carries a part number
    OR a value. The 'Populated Lines Only' export predicate: it drops blank/placeholder
    lines (no MPN and no value) that a purchasing sheet should never carry."""
    return bool((r.get("mpn") or "").strip()) or bool((r.get("value") or "").strip())


def bom_line_is_priced(r) -> bool:
    """Whether a BOM line carries a usable price - a stored extended cost, or a unit price
    that parses to a number. The 'Priced Lines Only' export predicate."""
    if r.get("extended") is not None:
        return True
    return _coerce_price(r.get("unit_price")) is not None


def bom_procurement_summary(rows, boards=1) -> str:
    """A one-line, human-readable procurement digest of a BOM - the headline facts an
    engineer pastes into a purchase request: line count, total parts, per-board cost (plus
    the run total when building more than one board), the critical-path lead time, and how
    many lines are still unpriced. Builds on the same roll-ups the on-screen summary uses
    (bom_cost_summary / bom_cost_at_qty / bom_lead_time) so the copied text can never
    disagree with what is shown. The cost figure appears only when at least one line is
    priced, the lead only when a line carries lead data, and the unpriced caveat only when
    a line lacks a price - nothing is invented. Returns the summary string (prefixed 'BOM: ')."""
    n = _board_count(boards)
    cost = bom_cost_summary(rows)
    lead = bom_lead_time(rows)
    total_parts = sum(_bom_line_qty(r) for r in rows)
    parts_lbl = "parts/board" if n > 1 else "parts"
    pieces = [f"{cost['line_count']} lines", f"{total_parts} {parts_lbl}"]
    if cost["priced_lines"]:
        pieces.append(f"${cost['total_cost']:,.2f}/board")  # prototype (qty-1) per-board cost
        if n > 1:
            run = bom_cost_at_qty(rows, n)["total_cost"]  # volume-priced at the scaled order
            pieces.append(f"x{n}: ${run:,.2f} (${run / n:,.2f} each)")
    if lead["any"]:
        who = f" ({lead['critical_mpn']})" if lead["critical_mpn"] else ""
        pieces.append(f"critical path {lead['max_weeks']} wk{who}")
    if cost["unpriced_lines"]:
        pieces.append(f"{cost['unpriced_lines']} unpriced")
    return "BOM: " + " · ".join(pieces)


# -- per-line procurement annotation (shared by the BOM builder + the endpoint) -----


def annotate_procurement_fields(rows, boards=1) -> dict:
    """Attach the per-line procurement verdict (`stock_risk` + `orderable`) to each row IN
    PLACE for a build of `boards` boards, and return the {risks, lead} roll-ups. The single
    place the folded BOM table's stock-risk tint, orderability and risk/lead headline are
    computed, so a row can never disagree with the aggregate. Pure over the given rows (only
    adds the two keys), offline, never raises. `orderable` = the line carries a usable price
    AND its known stock covers the run (no err/warn); an unknown-stock priced line is
    orderable (nothing says it is short), an unpriced line is not (no way to buy it yet)."""
    n = _board_count(boards)
    for r in rows:
        risk = bom_line_stock_risk(r, n)
        r["stock_risk"] = risk
        r["orderable"] = bool(bom_line_is_priced(r)) and risk["kind"] is None
    return {"risks": bom_sourcing_risks(rows, n), "lead": bom_lead_time(rows)}


# -- project orchestrator ------------------------------------------------------


def project_procurement(bom_result) -> dict:
    """The per-line + rolled-up procurement view for a cached project BOM (M7d).

    `bom_result` is the shape ProjectOps.bom returns (project / ran_at / boards / priced /
    lines / summary). Returns {built, priced, boards, lines, risks, lead, summary}:
      - `built` is False when the BOM was never built (ran_at None) - nothing to procure;
      - each `lines` entry is the BOM line plus `stock_risk` (bom_line_stock_risk) and an
        `orderable` flag (priced with known non-zero, sufficient stock);
      - `risks` / `lead` are the bom_sourcing_risks / bom_lead_time roll-ups;
      - `summary` is the one-line procurement digest.
    Honest: an unpriced build still lists its lines, but with unknown (never-a-risk) stock.
    Pure, offline, never raises."""
    rows = bom_result.get("lines") or []
    boards = _board_count(bom_result.get("boards", 1))
    built = bom_result.get("ran_at") is not None
    priced = bool(bom_result.get("priced"))

    # Annotate COPIES so the cached BOM result is never mutated by a read of the endpoint.
    lines = [dict(r) for r in rows]
    roll = annotate_procurement_fields(lines, boards)

    return {
        "built": built,
        "priced": priced,
        "boards": boards,
        "lines": lines,
        "risks": roll["risks"],
        "lead": roll["lead"],
        "summary": bom_procurement_summary(rows, boards) if rows else "",
    }
