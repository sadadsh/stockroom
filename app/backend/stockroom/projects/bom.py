"""M7c: a grouped, optionally priced Bill of Materials for a registered KiCad project.

Grouping + cost are pure COMPUTE, clean-lifted from the retired PyQt app's
LibraryManager (which could not be imported: it is a Qt hub, so the ~20 dict-in/dict-out
functions were copied out). Two faithful changes from the original:

  1. the schematic is read through Stockroom's byte-preserving sexp layer
     (SexpDocument), never fp_render.parse_sexpr;
  2. the group key layers KiBoM value-normalization + do-not-fit / testpoint exclusion
     (projects/kibom.py, Decision 5) ON TOP of the app's MPN-primary grouping, so
     4.7k and 4700 merge and a fiducial drops, without disturbing MPN-primary +
     manufacturer-in-key + value-as-MPN promotion.

No kicad-cli is needed: grouping is offline. Pricing is a separate, injected
`price_lookup(mpn)` served by Stockroom's enrich layer (see enrichment_to_bom_lookup);
when it is absent or a lookup misses, the line stays honestly unpriced and a price is
never invented. Cost + procurement EXPORTS, the revision diff, sourcing-risk, and lead
time land in M7d.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from stockroom.projects import kibom
from stockroom.projects.identity import _PLACEHOLDERS, part_identity, strict_mpn
from stockroom.sexp.document import SexpDocument, SexpNode

# passives a fab stocks by value alone (a basic part when they carry no real MPN)
_BASIC_PREFIXES = {"R", "C", "L", "FB"}


def _natural_ref(ref: str):
    """Sort key so R2 < R10 (prefix, then numeric index)."""
    m = re.match(r"([A-Za-z_]+)(\d+)", ref or "")
    return (m.group(1), int(m.group(2))) if m else (ref or "", 0)


def is_basic_part(ref, value, mpn) -> bool:
    """A 'basic' part: a standard passive a fab stocks by value alone (R / C / L /
    ferrite bead with a value and no specific manufacturer part number). The offline
    analogue of JLCPCB's basic-vs-extended split."""
    if mpn and str(mpn).strip() and str(mpn).strip().lower() not in _PLACEHOLDERS:
        return False
    m = re.match(r"[A-Za-z]+", str(ref or ""))
    prefix = m.group(0).upper() if m else ""
    return prefix in _BASIC_PREFIXES and bool(str(value or "").strip())


def _dist_pn(r) -> str:
    """The distributor's own part number for a priced row, matched to its Source so an
    export can say 'order from {Source} by {this P/N}': LCSC -> lcsc_pn, Mouser ->
    mouser_pn, DigiKey -> digikey_pn. Falls back to whichever is present when the source
    is unknown, or '' when nothing was threaded."""
    src = (r.get("source") or "").strip().lower()
    lcsc = (r.get("lcsc_pn") or "").strip()
    mouser = (r.get("mouser_pn") or "").strip()
    digikey = (r.get("digikey_pn") or "").strip()
    if src == "lcsc":
        return lcsc or mouser or digikey
    if src == "mouser":
        return mouser or lcsc or digikey
    if src == "digikey":
        return digikey or mouser or lcsc
    return lcsc or mouser or digikey


# -- schematic read (Stockroom sexp, replacing fp_render.parse_sexpr) ----------


def _read_root(sch_path) -> SexpNode | None:
    try:
        root = SexpDocument.load(sch_path).root
    except Exception:  # noqa: BLE001 - a corrupt/missing file yields no components, never a crash
        return None
    return root if root.name == "kicad_sch" else None


def _token_is_yes(node: SexpNode | None) -> bool:
    """A KiCad flag token, true when present and not explicitly 'no': (dnp yes) and a
    bare (exclude_from_bom) are true; (dnp no) and an absent node are false."""
    if node is None:
        return False
    val = node.children[1].value if len(node.children) > 1 else "yes"
    return val != "no"


def _bom_components(sch_path) -> list:
    """Every real BOM component (ref, props) in one .kicad_sch. Skips power / virtual
    symbols, in_bom=no / exclude_from_bom / dnp=yes parts, and the KiBoM exclude set
    (testpoints, fiducials, mounting holes, do-not-fit). [] for a non-schematic file."""
    root = _read_root(sch_path)
    if root is None:
        return []
    out = []
    for node in root.find_all("symbol"):
        lib_node = node.find("lib_id")
        lib_id = (
            lib_node.children[1].value
            if lib_node is not None and len(lib_node.children) > 1
            else ""
        )
        props: dict = {}
        for prop in node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3:
                props[kids[1].value] = kids[2].value
        in_bom = True
        ib = node.find("in_bom")
        if ib is not None and len(ib.children) > 1 and ib.children[1].value == "no":
            in_bom = False
        if _token_is_yes(node.find("exclude_from_bom")):
            in_bom = False
        if _token_is_yes(node.find("dnp")):
            in_bom = False
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#") or lib_id.lower().startswith("power:") or not in_bom:
            continue
        part_name = lib_id.split(":")[-1]
        if kibom.is_excluded(ref, part_name, props.get("Footprint", "")):
            continue
        if kibom.is_do_not_fit(props):
            continue
        out.append((ref, props))
    return out


# -- grouping (the app's MPN-primary logic + KiBoM value-normalization) --------


def _bom_from_components(comps, lookup=None,
                        enrich_fields=("manufacturer", "datasheet", "description"),
                        price_lookup=None) -> dict:
    """Group (ref, props) components into BOM lines, enrich blanks via `lookup`, flag
    basic parts, and (when `price_lookup` is given) price each line with an MPN and roll
    up a cost summary. Shared by the single-sheet and whole-project builders.

    Grouping is MPN-primary: a real manufacturer part number groups by that MPN; an IC
    with a manufacturer and no dedicated MPN promotes its Value to the MPN; everything
    else falls back to a (value, footprint, manufacturer) key whose value is
    KiBoM-normalized so 4.7k and 4700 merge (Decision 5). Two parts of the same value
    but different manufacturers stay distinct lines."""
    groups: dict = {}
    for ref, props in comps:
        ident = part_identity(props, fallback=props.get("Value", ""))
        value = (props.get("Value") or "").strip()
        smpn = strict_mpn(props)
        # An IC (non-passive) with a manufacturer often carries its real MPN in the
        # Value field. Promote it, but NEVER for a passive, whose Value is a value.
        if not smpn and ident["manufacturer"] and not is_basic_part(ref, value, None):
            smpn = value if value and value.lower() not in _PLACEHOLDERS else None
        # Fallback key on the KiBoM-normalized value + footprint + manufacturer, so
        # equivalent values merge while different makers stay apart.
        key = smpn or (
            "VF", kibom.normalize_value(value), props.get("Footprint", ""),
            ident["manufacturer"] or "",
        )
        g = groups.setdefault(key, {
            "mpn": smpn, "manufacturer": ident["manufacturer"],
            "datasheet": ident["datasheet"], "description": ident["description"],
            "value": props.get("Value", ""), "footprint": props.get("Footprint", ""),
            "refs": []})
        g["refs"].append(ref)

    if lookup:
        for g in groups.values():
            if g["mpn"] and any(not g.get(f) for f in enrich_fields):
                res = lookup(g["mpn"])
                if res:
                    for f in enrich_fields:
                        if not g.get(f) and res.get(f):
                            g[f] = res[f]

    rows = []
    for g in groups.values():
        refs = sorted(g["refs"], key=_natural_ref)
        rows.append({"refs": refs, "qty": len(refs), "value": g["value"],
                     "mpn": g["mpn"] or "", "manufacturer": g["manufacturer"] or "",
                     "has_real_mpn": bool(g["mpn"]),
                     "footprint": g["footprint"], "datasheet": g["datasheet"] or "",
                     "description": g["description"] or "",
                     "basic": is_basic_part(refs[0] if refs else "", g["value"], g["mpn"])})
    rows.sort(key=lambda r: (r["value"].lower(), r["footprint"].lower(),
                             _natural_ref(r["refs"][0]) if r["refs"] else ("", 0)))

    priced = price_lookup is not None
    if priced:
        _price_rows(rows, price_lookup, "qty")

    out = {"rows": rows, "component_count": len(comps), "line_count": len(rows),
           "csv": _bom_project_csv(rows, priced)}
    if priced:
        out["cost"] = bom_cost_summary(rows)
    return out


def bom_from_project(sch_paths, lookup=None,
                     enrich_fields=("manufacturer", "datasheet", "description"),
                     price_lookup=None) -> dict:
    """A single BOM merged across EVERY sheet of a project (not just the root),
    grouping identical parts with summed quantity. Priced when `price_lookup` is given."""
    comps = []
    for p in (sch_paths or []):
        try:
            comps.extend(_bom_components(p))
        except Exception:  # noqa: BLE001 - an unreadable sheet drops out, never crashes the build
            continue
    return _bom_from_components(comps, lookup, enrich_fields, price_lookup=price_lookup)


def bom_from_kicad_schematic(sch_path, lookup=None,
                             enrich_fields=("manufacturer", "datasheet", "description"),
                             price_lookup=None) -> dict:
    """Grouped BOM from one KiCad 6+ schematic (.kicad_sch). Skips power / virtual /
    excluded-from-BOM symbols, groups by MPN (else normalized value + footprint), and
    prices each MPN line when `price_lookup` is given. Returns {rows, component_count,
    line_count, csv}, plus a cost roll-up when priced; an error shape for a non-schematic."""
    root = _read_root(sch_path)
    if root is None:
        return {"error": "not a KiCad schematic (.kicad_sch)", "rows": [],
                "component_count": 0, "line_count": 0, "csv": ""}
    return _bom_from_components(_bom_components(sch_path), lookup, enrich_fields,
                               price_lookup=price_lookup)


def consolidated_bom(boards: dict, lookup=None, price_lookup=None) -> dict:
    """Merge the BOMs of several boards into one purchasing list. `boards` is
    {board_name: [.kicad_sch sheet paths]}. Groups by MPN (else normalized value +
    footprint) across ALL boards, sums quantity, and keeps the per-board breakdown +
    reference designators. Priced by total_qty when `price_lookup` is given. Read-only."""
    board_names = list(boards)
    merged: dict = {}
    for board, sheets in boards.items():
        for sheet in sheets:
            for r in bom_from_kicad_schematic(sheet)["rows"]:
                key = r["mpn"] or ("VF", kibom.normalize_value(r["value"]), r["footprint"],
                                   r.get("manufacturer") or "")
                m = merged.setdefault(key, {
                    "mpn": r["mpn"], "manufacturer": r["manufacturer"], "value": r["value"],
                    "has_real_mpn": bool(r["mpn"]),
                    "footprint": r["footprint"], "datasheet": r["datasheet"],
                    "description": r["description"], "total_qty": 0,
                    "per_board": {}, "refs_by_board": {}})
                m["total_qty"] += r["qty"]
                m["per_board"][board] = m["per_board"].get(board, 0) + r["qty"]
                m["refs_by_board"][board] = sorted(
                    set(m["refs_by_board"].get(board, []) + r["refs"]), key=_natural_ref)
                for f in ("manufacturer", "datasheet", "description"):
                    if not m[f] and r.get(f):
                        m[f] = r[f]

    if lookup:
        for m in merged.values():
            if not m["mpn"]:
                m["source"] = ""
                continue
            res = lookup(m["mpn"])
            if res:
                m["source"] = res.get("source", "")
                for f in ("manufacturer", "datasheet"):
                    if not m[f] and res.get(f):
                        m[f] = res[f]
            else:
                m["source"] = "NOT FOUND"

    rows = sorted(merged.values(), key=lambda r: (r["value"].lower(), r["footprint"].lower()))
    sourced = bool(lookup)
    priced = price_lookup is not None
    if priced:
        _price_rows(rows, price_lookup, "total_qty")
    out = {"rows": rows, "board_names": board_names,
           "csv": _bom_consolidated_csv(rows, board_names, sourced, priced),
           "line_count": len(rows), "total_parts": sum(r["total_qty"] for r in rows)}
    if priced:
        out["cost"] = bom_cost_summary(rows)
    return out


def bom_rows_at_ref(sheet_rels, show) -> dict:
    """Reconstruct a project's BOM as it existed at a git revision, for diffing against
    the current build. `sheet_rels` are the current build's repo-relative sheet paths;
    `show(rel) -> str | None` returns that sheet's content at the target revision.
    Identity only, NO network and NO pricing. Never raises: a failing `show` or an
    unparseable sheet is skipped. Returns {rows, sheets_found, sheets_missing}."""
    import os
    import tempfile
    comps: list = []
    found = missing = 0
    with tempfile.TemporaryDirectory() as td:
        for i, rel in enumerate(sheet_rels or []):
            try:
                text = show(rel)
            except Exception:  # noqa: BLE001 - a git failure is just an absent sheet
                text = None
            if not text:
                missing += 1
                continue
            found += 1
            fp = os.path.join(td, f"sheet_{i}.kicad_sch")
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                comps.extend(_bom_components(fp))
            except Exception:  # noqa: BLE001 - an unparseable sheet drops out
                continue
    res = _bom_from_components(comps)
    return {"rows": res["rows"], "sheets_found": found, "sheets_missing": missing}


# Header aliases so an exported BOM (project OR consolidated) parses back into
# diff-ready rows, matched case-insensitively.
_CSV_MPN_COLS = ("mpn", "manufacturer part number", "mfr part number",
                 "manufacturer part no", "part number")
_CSV_VALUE_COLS = ("value",)
_CSV_FOOTPRINT_COLS = ("footprint",)
_CSV_QTY_COLS = ("qty", "quantity", "total", "total qty")


def bom_rows_from_csv(text: str) -> list:
    """Parse an exported BOM CSV back into diff-ready rows [{mpn, value, footprint, qty}].
    Columns match by name (case-insensitive) so both the project and consolidated
    exports load. Rows with neither an MPN nor a value are skipped. Never raises."""
    if not text:
        return []
    import csv as _csv
    import io as _io
    rows = []
    try:
        reader = _csv.DictReader(_io.StringIO(text))
        headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}

        def _col(cols):
            for c in cols:
                if c in headers:
                    return headers[c]
            return None

        mpn_c = _col(_CSV_MPN_COLS)
        val_c = _col(_CSV_VALUE_COLS)
        fp_c = _col(_CSV_FOOTPRINT_COLS)
        qty_c = _col(_CSV_QTY_COLS)
        for raw in reader:
            mpn = (raw.get(mpn_c) or "").strip() if mpn_c else ""
            value = (raw.get(val_c) or "").strip() if val_c else ""
            if not mpn and not value:
                continue
            try:
                qty = int(float(raw.get(qty_c) or 0)) if qty_c else 0
            except (TypeError, ValueError):
                qty = 0
            rows.append({"mpn": mpn, "value": value,
                         "footprint": (raw.get(fp_c) or "").strip() if fp_c else "",
                         "qty": qty})
    except Exception:  # noqa: BLE001 - a malformed CSV yields what parsed so far
        return rows
    return rows


# -- cost roll-up --------------------------------------------------------------


def _coerce_price(v):
    """A price ('$0.10', '1,250.00', a number) -> float, or None if unparseable
    (e.g. 'Call for pricing')."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lstrip("$").replace(",", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def price_at_qty(price_breaks, qty):
    """The applicable unit price for ordering `qty` from a [{qty, price}, ...] ladder:
    the price of the largest break quantity <= qty. Below the first break, falls back to
    that first break. None when the ladder is empty or qty is unparseable."""
    if not price_breaks:
        return None
    try:
        q = int(float(qty))
    except (TypeError, ValueError):
        return None
    ladder = sorted(price_breaks, key=lambda b: b["qty"])
    applicable = None
    for b in ladder:
        if b["qty"] <= q:
            applicable = b["price"]
        else:
            break
    return applicable if applicable is not None else ladder[0]["price"]


def line_extended(unit_price, qty):
    """Extended line cost = unit_price * qty, or None when either is missing. Rounded to
    4 dp so fractional-cent unit prices do not accumulate float noise."""
    p = _coerce_price(unit_price)
    try:
        q = int(float(qty))
    except (TypeError, ValueError):
        q = 0
    return round(p * q, 4) if (p is not None and q) else None


def bom_cost_summary(rows) -> dict:
    """Roll up a BOM's line costs. Sums the extended cost of every PRICED line and
    counts unpriced lines separately, so a partial total is never mistaken for the whole.
    qty comes from 'qty' (project BOM) or 'total_qty' (consolidated). Returns {total_cost,
    priced_lines, unpriced_lines, line_count, currency}."""
    total = 0.0
    priced = unpriced = 0
    for r in rows:
        qty = r.get("qty", r.get("total_qty", 0))
        ext = r.get("extended")
        if ext is None:
            ext = line_extended(r.get("unit_price"), qty)
        if ext is None:
            unpriced += 1
        else:
            total += ext
            priced += 1
    return {"total_cost": round(total, 2), "priced_lines": priced,
            "unpriced_lines": unpriced, "line_count": len(rows), "currency": "USD"}


def _board_count(boards) -> int:
    """A build's board count as a whole number >= 1: anything unparseable or below 1
    folds to 1."""
    try:
        n = int(boards)
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1


def _row_cost_at_qty(r, boards):
    """The (order_qty, unit_price, extended) for ONE line at a build of `boards` boards.
    order_qty = per_board_qty * boards; the unit price is re-read from the line's ladder
    at that scaled qty (a bigger run buys down a cheaper break), else the stored qty-1
    unit_price. per-board qty comes from 'qty' (project) or 'total_qty' (consolidated).
    unit_price / extended are None when the line is unpriced. Never mutates `r`."""
    per_board = r.get("qty", r.get("total_qty", 0)) or 0
    try:
        per_board = int(per_board)
    except (TypeError, ValueError):
        per_board = 0
    order_qty = per_board * boards
    ladder = r.get("price_breaks")
    unit = price_at_qty(ladder, order_qty) if ladder else None
    if unit is None:
        unit = _coerce_price(r.get("unit_price"))
    ext = round(unit * order_qty, 4) if (unit is not None and order_qty) else None
    return order_qty, unit, ext


def bom_cost_at_qty(rows, boards) -> dict:
    """Project a priced BOM's cost for building `boards` copies. Each line scales to
    per_board_qty * boards and re-reads its unit price at that scaled quantity (volume
    break), else the stored qty-1 price. Mirrors bom_cost_summary's priced/unpriced
    bookkeeping. Pure: never mutates `rows`. Returns {boards, total_cost, priced_lines,
    unpriced_lines, currency}."""
    n = _board_count(boards)
    total = 0.0
    priced = unpriced = 0
    for r in rows:
        _order_qty, _unit, ext = _row_cost_at_qty(r, n)
        if ext is None:
            unpriced += 1
        else:
            total += ext
            priced += 1
    return {"boards": n, "total_cost": round(total, 2), "priced_lines": priced,
            "unpriced_lines": unpriced, "currency": "USD"}


def bom_cost_by_source(rows, boards=1) -> dict:
    """Split a priced BOM's projected cost by the distributor sourcing each line (they
    sum to the whole-run total). Uses the same per-line volume costing as bom_cost_at_qty.
    Only PRICED lines count; a priced line with a blank source is 'Unsourced'; unpriced
    lines are skipped. Returns {sources: {name: {total_cost, lines}}, currency}."""
    n = _board_count(boards)
    by: dict = {}
    for r in rows:
        _order_qty, _unit, ext = _row_cost_at_qty(r, n)
        if ext is None:
            continue
        src = (r.get("source") or "").strip() or "Unsourced"
        s = by.setdefault(src, {"total_cost": 0.0, "lines": 0})
        s["total_cost"] += ext
        s["lines"] += 1
    for s in by.values():
        s["total_cost"] = round(s["total_cost"], 2)
    return {"sources": by, "currency": "USD"}


def _price_rows(rows, price_lookup, qty_key: str):
    """Attach unit_price / stock / lifecycle / lead_time / source / distributor P/Ns and
    the extended cost to each row from a pricing lookup, one call per unique MPN. Rows
    without an MPN are left unpriced (a passive's value is not a purchasable part number).
    Prefers the price-break ladder so the line is costed at its real quantity."""
    cache: dict = {}
    for r in rows:
        mpn = r.get("mpn")
        if not mpn:
            continue
        if mpn not in cache:
            try:
                cache[mpn] = price_lookup(mpn)
            except Exception:  # noqa: BLE001 - a dead lookup leaves the line unpriced
                cache[mpn] = None
        res = cache[mpn] or {}
        qty = r.get(qty_key, 0)
        ladder = res.get("price_breaks")
        vol = price_at_qty(ladder, qty) if ladder else None
        if vol is not None:
            r["unit_price"] = vol
            r["extended"] = line_extended(vol, qty)
            r["price_breaks"] = ladder
        else:
            up = res.get("unit_price")
            if up is not None and up != "":
                r["unit_price"] = up
                r["extended"] = line_extended(up, qty)
                if ladder:
                    r["price_breaks"] = ladder
        if res.get("stock") is not None:
            r["stock"] = res.get("stock")
        if res.get("lifecycle"):
            r["lifecycle"] = res.get("lifecycle")
        if res.get("lead_time") not in (None, ""):
            r["lead_time"] = res.get("lead_time")
        for k in ("source", "lcsc_pn", "mouser_pn", "digikey_pn", "url", "category"):
            v = res.get(k)
            if v and not r.get(k):
                r[k] = v


# -- CSV shapes (return-value fields; full export suite lands in M7d) ----------


def _bom_project_csv(rows, priced: bool) -> str:
    """The project BOM export CSV (Refs, Qty, Value, MPN, Manufacturer, Footprint,
    Datasheet, Description, Basic, + priced Source/Dist P/N/Unit/Ext/Stock/Lifecycle
    columns when priced). Pure."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    head = ["Refs", "Qty", "Value", "MPN", "Manufacturer", "Footprint",
            "Datasheet", "Description", "Basic"]
    if priced:
        head += ["Source", "Dist P/N", "Unit Price", "Ext Price", "Stock", "Lifecycle"]
    w.writerow(head)
    for r in rows:
        line = [",".join(r.get("refs", [])), r.get("qty", ""), r.get("value", ""),
                r.get("mpn", ""), r.get("manufacturer", ""), r.get("footprint", ""),
                r.get("datasheet", ""), r.get("description", ""),
                "yes" if r.get("basic") else ""]
        if priced:
            ext = r.get("extended")
            line += [r.get("source", ""), _dist_pn(r), r.get("unit_price", ""),
                     f"{ext:.4f}" if ext is not None else "",
                     r.get("stock", ""), r.get("lifecycle", "")]
        w.writerow(line)
    return buf.getvalue()


def _bom_consolidated_csv(rows, board_names, sourced: bool, priced: bool) -> str:
    """The consolidated BOM export CSV (MPN, Manufacturer, Value, Footprint, Total,
    [Source,] per-board columns, Datasheet, + priced columns). Pure."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    head = ["MPN", "Manufacturer", "Value", "Footprint", "Total"] + list(board_names) + ["Datasheet"]
    if sourced:
        head.insert(5, "Source")
    if priced:
        head += ["Dist P/N", "Unit Price", "Ext Price", "Stock", "Lifecycle"]
    w.writerow(head)
    for r in rows:
        row = [r.get("mpn", ""), r.get("manufacturer", ""), r.get("value", ""),
               r.get("footprint", ""), r.get("total_qty", "")]
        if sourced:
            row.append(r.get("source", ""))
        row += [(r.get("per_board") or {}).get(b, 0) for b in board_names] + [r.get("datasheet", "")]
        if priced:
            ext = r.get("extended")
            row += [_dist_pn(r), r.get("unit_price", ""), f"{ext:.4f}" if ext is not None else "",
                    r.get("stock", ""), r.get("lifecycle", "")]
        w.writerow(row)
    return buf.getvalue()


# -- enrich -> price adapter (M7c-3) -------------------------------------------


# Internal enrich source tokens that name a real distributor, mapped to a display name
# for the BOM's Source column. Anything else (a scrape / jsonld / datasheet source) is
# not a distributor, so the line's Source stays blank (Unsourced in the cost split).
_DISTRIBUTOR_SOURCES = {"mouser": "Mouser", "lcsc": "LCSC", "digikey": "DigiKey"}


def enrichment_to_bom_lookup(result) -> dict | None:
    """Adapt an enrich-layer EnrichmentResult into the flat {price_breaks, unit_price,
    stock, manufacturer, datasheet, description, source} dict the BOM's price_lookup
    expects (M7c-3), so pricing is served by Stockroom's own enrich layer rather than the
    retired app's dropped distributor adapters. Returns None for an empty result (a total
    miss), so the line stays honestly unpriced. lifecycle / lead time / distributor part
    numbers are added in M7d, where sourcing-risk and exports need them."""
    if result is None:
        return None
    breaks = [{"qty": b.qty, "price": b.price} for b in getattr(result, "price_breaks", [])]

    def _val(sourced):
        return sourced.value if sourced is not None else None

    out: dict = {}
    if breaks:
        out["price_breaks"] = breaks
        out["unit_price"] = breaks[0]["price"]
    if result.stock is not None:
        out["stock"] = result.stock.value
    if result.manufacturer is not None:
        out["manufacturer"] = _val(result.manufacturer)
    if result.datasheet_url is not None:
        out["datasheet"] = _val(result.datasheet_url)
    if result.description is not None:
        out["description"] = _val(result.description)
    # Label the Source with the distributor that carried the priced signal: prefer the
    # source recorded on stock (a distributor stock count), else on the MPN.
    for sourced in (result.stock, result.mpn, result.manufacturer):
        if sourced is not None:
            disp = _DISTRIBUTOR_SOURCES.get((sourced.source or "").lower())
            if disp:
                out["source"] = disp
                break
    return out or None


# -- project orchestrator (M7c-4) ----------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bom_state(line_count: int, priced: bool, summary: dict) -> str:
    """The honest BOM verdict, mirroring the checks rule that "nothing built is never a
    clean pass": 'empty' (no lines), 'built' (grouped, pricing not attempted), 'unpriced'
    (priced attempted, nothing costed, e.g. offline), 'partial' (some lines unpriced),
    'costed' (every line priced). Only 'costed' is a fully green verdict."""
    if line_count == 0:
        return "empty"
    if not priced:
        return "built"
    if summary["priced_lines"] == 0:
        return "unpriced"
    if summary["unpriced_lines"] > 0:
        return "partial"
    return "costed"


def project_bom(root, pro_path, sheet_paths, name="", boards=1,
                price_lookup=None, progress=None) -> dict:
    """Build a grouped, optionally priced BOM for a registered project (M7c).

    Reads every schematic sheet through Stockroom's byte-preserving sexp reader (offline,
    no kicad-cli), groups identical parts with KiBoM value-normalization + DNF/testpoint
    exclusion, and, when `price_lookup` is given, prices each line with an MPN and rolls
    up a cost summary at 1 and `boards` copies. Honest: with no price_lookup, or when a
    lookup misses, lines stay unpriced and a price is never invented. Returns
    {project, ran_at, boards, priced, line_count, component_count, lines, summary,
    by_source, cost_at_qty}."""
    root = Path(root)

    def _p(pct, msg):
        if progress:
            progress({"pct": pct, "message": msg})

    _p(10, "Reading schematics")
    abs_sheets = [str(root / s) for s in (sheet_paths or [])]

    _p(40, "Grouping components")
    priced = price_lookup is not None

    def _priced_progress(mpn_lookup):
        # Report progress as unique MPNs are priced (the slow, network-bound half).
        seen = {"n": 0}

        def wrapped(mpn):
            seen["n"] += 1
            _p(min(90, 55 + seen["n"]), f"Pricing {mpn}")
            return mpn_lookup(mpn)

        return wrapped

    lookup = _priced_progress(price_lookup) if priced else None
    built = bom_from_project(abs_sheets, price_lookup=lookup)
    rows = built["rows"]

    n = _board_count(boards)
    summary = bom_cost_summary(rows)
    summary["state"] = _bom_state(built["line_count"], priced, summary)
    summary["priced"] = priced

    _p(95, "Summarizing")
    return {
        "project": name,
        "ran_at": _utc_now_iso(),
        "boards": n,
        "priced": priced,
        "line_count": built["line_count"],
        "component_count": built["component_count"],
        "lines": rows,
        "summary": summary,
        "by_source": bom_cost_by_source(rows, n) if priced else None,
        "cost_at_qty": bom_cost_at_qty(rows, n) if (priced and n > 1) else None,
    }
