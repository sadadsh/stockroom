"""M7d: BOM + procurement export writers (CSV, XLSX, Mouser cart, JLCPCB assembly).

Pure COMPUTE, clean-lifted from the retired PyQt app's LibraryManager. The XLSX writers
are pure stdlib (zipfile + hand-written OOXML), so the packaged app bundles nothing extra
to emit a real Excel workbook with numeric (sortable / summable) cost cells. Every writer
is pure: dict-in, str-or-bytes-out, offline.

`project_bom_export` is the single dispatcher the router calls: it takes a cached project
BOM result + an export kind and returns {filename, content_type, data}, mapping each kind
to its writer with the project name in the filename.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re

from stockroom.projects.bom import (
    _bom_consolidated_csv,
    _bom_line_qty,
    _bom_project_csv,
    _board_count,
    _coerce_price,
    _dist_pn,
    _lead_weeks,
    _row_cost_at_qty,
    _row_is_passive,
    _row_refs,
    line_extended,
    price_at_qty,
)

# ---------------------------------------------------------------------------
# CSV exports
# ---------------------------------------------------------------------------


def bom_csv(rows, *, mode="project", board_names=None, priced=False, sourced=False) -> str:
    """Serialize BOM rows to the export CSV for `mode` ('project' | 'consolidated'),
    reproducing the exact columns the builders emit so a FILTERED subset (populated /
    priced line filters) re-exports with the same schema. `priced`/`sourced` come from the
    ORIGINAL build, not re-detected, so filtering out every priced line keeps the header
    stable."""
    if mode == "consolidated":
        return _bom_consolidated_csv(rows, board_names or [], sourced, priced)
    return _bom_project_csv(rows, priced)


def priced_bom_csv_at_qty(rows, boards=1) -> dict:
    """A priced purchasing sheet for a build of `boards` copies - the line-by-line form of
    bom_cost_at_qty's headline projection. Each line's Order Qty = per_board_qty * boards
    and its Unit/Ext Price are re-read from the price-break ladder at that scaled quantity,
    via the same _row_cost_at_qty helper the total uses, so the sheet and the total can
    never disagree. Every row is one line (priced or not); the Per-Board Qty column keeps
    the base build visible. Lines are ranked by run spend (biggest Ext Price first, unpriced
    last). Returns {csv, boards, line_count, priced_lines, unpriced_lines, total_cost,
    currency}."""
    import csv as _csv
    import io as _io
    n = _board_count(boards)
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["MPN", "Manufacturer", "Value", "Footprint", "Per-Board Qty", "Order Qty",
                "Source", "Dist P/N", "Unit Price", "Ext Price", "Stock", "Lifecycle",
                "Lead (wks)"])
    priced = unpriced = 0
    total = 0.0
    costed = []
    for r in rows:
        order_qty, unit, ext = _row_cost_at_qty(r, n)
        if ext is None:
            unpriced += 1
        else:
            total += ext
            priced += 1
        costed.append((r, order_qty, unit, ext))
    # A purchasing sheet leads with the cost drivers: biggest run spend first, unpriced
    # lines (no cost to rank) last. Stable, so equal-cost lines keep BOM order.
    costed.sort(key=lambda c: c[3] if c[3] is not None else -1.0, reverse=True)
    for r, order_qty, unit, ext in costed:
        per_board = order_qty // n if n else order_qty  # exact: order_qty = per_board * n
        lead = _lead_weeks(r.get("lead_time"))
        w.writerow([r.get("mpn", ""), r.get("manufacturer", ""), r.get("value", ""),
                    r.get("footprint", ""), per_board, order_qty,
                    r.get("source", ""), _dist_pn(r),
                    f"{unit:.4f}" if unit is not None else "",
                    f"{ext:.4f}" if ext is not None else "",
                    r.get("stock", ""), r.get("lifecycle", ""),
                    lead if lead is not None else ""])
    return {"csv": buf.getvalue(), "boards": n, "line_count": len(rows),
            "priced_lines": priced, "unpriced_lines": unpriced,
            "total_cost": round(total, 2), "currency": "USD"}


def procurement_cart_csv(rows, boards=1, spares_pct=0) -> dict:
    """Build a Mouser cart-upload CSV from priced/enriched BOM rows. One line per part that
    has an MPN (a purchasable part number); bare passives grouped by value alone are skipped,
    since a cart orders by part number. The Mouser P/N is filled when a lookup provided it,
    else left blank so Mouser resolves it from the MPN; Customer Reference carries the refdes.
    Per-board qty comes from 'qty' (project) or 'total_qty' (consolidated), scaled by `boards`
    (a board count below 1 is treated as 1). `spares_pct` (0 by default) pads the SMT passives
    (R/C/L/FB) by that percentage, ROUNDED UP, for pick-and-place attrition. Returns {csv,
    boards, spares_pct, line_count, skipped_no_mpn, padded_lines, total_qty}."""
    import csv as _csv
    import io as _io
    import math
    try:
        n = int(boards)
    except (TypeError, ValueError):
        n = 1
    if n < 1:
        n = 1
    try:
        pct = float(spares_pct)
    except (TypeError, ValueError):
        pct = 0.0
    if pct < 0:
        pct = 0.0
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["Mouser Part Number", "Manufacturer Part Number", "Quantity",
                "Customer Reference"])
    line_count = skipped = total = padded = 0
    for r in rows:
        mpn = (r.get("mpn") or "").strip()
        per_board = r.get("qty", r.get("total_qty", 0)) or 0
        if not mpn:
            skipped += 1
            continue
        try:
            order_qty = int(per_board) * n
        except (TypeError, ValueError):
            order_qty = 0
        if pct and order_qty and _row_is_passive(r):
            buffered = math.ceil(order_qty * (1 + pct / 100.0))
            if buffered > order_qty:
                order_qty = buffered
                padded += 1
        w.writerow([r.get("mouser_pn") or "", mpn, order_qty, " ".join(_row_refs(r))])
        line_count += 1
        total += order_qty
    return {"csv": buf.getvalue(), "boards": n,
            "spares_pct": (int(pct) if pct == int(pct) else pct),
            "line_count": line_count, "skipped_no_mpn": skipped, "padded_lines": padded,
            "total_qty": total}


def jlcpcb_bom_csv(rows) -> dict:
    """Build a JLCPCB assembly BOM CSV from enriched/priced BOM rows. Columns match JLCPCB's
    assembly upload - Comment, Designator, Footprint, LCSC Part #. Unlike a distributor cart,
    assembly places parts by DESIGNATOR (including bare passives by value), so every line with
    a comment (value, else MPN) and at least one refdes is exported; the LCSC Part # is filled
    when a lookup provided one (`lcsc_pn`) else left blank. Qty comes from 'qty' (project) or
    'total_qty' (consolidated). Returns {csv, line_count, with_lcsc, without_lcsc, total_qty}."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    line_count = with_lcsc = total = 0
    for r in rows:
        refs = _row_refs(r)
        comment = (r.get("value") or "").strip() or (r.get("mpn") or "").strip()
        if not refs or not comment:  # nothing to place / nothing to call it
            continue
        lcsc = (r.get("lcsc_pn") or "").strip()
        w.writerow([comment, ",".join(refs), r.get("footprint", ""), lcsc])
        line_count += 1
        if lcsc:
            with_lcsc += 1
        qty = r.get("qty", r.get("total_qty", 0)) or 0
        try:
            total += int(qty)
        except (TypeError, ValueError):
            pass
    return {"csv": buf.getvalue(), "line_count": line_count, "with_lcsc": with_lcsc,
            "without_lcsc": line_count - with_lcsc, "total_qty": total}


# ---------------------------------------------------------------------------
# XLSX writers (pure stdlib OOXML)
# ---------------------------------------------------------------------------


def _xlsx_col(idx: int) -> str:
    """0-based column index -> spreadsheet column letters (0->A, 25->Z, 26->AA)."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_escape(s: str) -> str:
    """XML-escape cell text and drop characters XML 1.0 forbids, so a stray control byte
    (or an ampersand / angle bracket in a description) can never make Excel refuse the file."""
    s = "".join(ch for ch in str(s) if ch in "\t\n\r" or ord(ch) >= 0x20)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xlsx_number(num: float) -> str:
    """A fixed-point OOXML numeric literal for a <v> cell - NEVER scientific notation.
    repr(1e-5) is '1e-05', which Excel/LibreOffice reject as a numeric value, so a sub-1e-4
    price (a real unit cost on high-volume passives) would corrupt the sheet. Whole numbers
    stay compact ('5'); fractions render fixed-point with trailing zeros trimmed."""
    if num == int(num):
        return str(int(num))
    return format(num, ".6f").rstrip("0").rstrip(".")


# Shared workbook scaffolding. Style ids referenced by cells: s="1" bold (header / totals
# label); s="2" currency 0.00; s="3" bold currency (totals).
_XLSX_STYLES_BOLD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    # font 2: the hyperlink look (blue + underline) so a link cell reads as a clickable link
    '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')
# Adds a currency number format ($#,##0.00) as styles 2 (plain) and 3 (bold, for totals).
_XLSX_STYLES_CURRENCY = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')


def _xlsx_package(sheet_xml: str, styles_xml: str, sheet_name: str = "Sheet1",
                  sheet_rels_xml: str = "") -> bytes:
    """Zip a single-worksheet .xlsx from its worksheet + styles XML. Writes the fixed OPC
    parts (content types, relationships, workbook) around them so each writer only builds
    the sheet and picks a style table. `sheet_rels_xml`, when given, is the worksheet's own
    relationships part (external hyperlink targets). Pure stdlib - no packaging dependency."""
    import io as _io
    import zipfile as _zip
    name = _xlsx_escape(sheet_name)[:31] or "Sheet1"  # Excel caps sheet names at 31 chars
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>')
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>')
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>')
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w", _zip.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if sheet_rels_xml:
            z.writestr("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels_xml)
    return buf.getvalue()


def bom_xlsx(rows) -> bytes:
    """A clean Excel (.xlsx) workbook of the BOM: one 'BOM' sheet with a bold, frozen header
    row, autofilter dropdowns, auto-sized columns, and - the real win over CSV - NUMBERS
    stored as numbers (Qty, Unit/Ext Price, Stock) so Excel can sort and sum them. Mirrors the
    Full BOM CSV columns and adds the priced Source / Dist P/N / Unit Price / Ext Price / Stock
    / Lifecycle columns only when the build carries pricing. A Mouser string price ('$0.10') is
    coerced to a real number. Written with the standard library alone (zipfile + a little XML).
    Returns the .xlsx file as bytes."""
    priced = any(_coerce_price(r.get("unit_price")) is not None or r.get("extended") is not None
                 for r in rows)
    # The build-economics group is present once a BOM has been built for a board count (every row
    # carries final_qty then): the ORDER quantity for the build (price-break optimized), its unit
    # cost, the line cost, the tax/tariff, and the line total - the columns you actually order and
    # budget from. XLSX is the primary deliverable, so it must carry these, not just the CSV/table.
    build = any(r.get("final_qty") is not None for r in rows)
    cols = [("Refs", "t"), ("Qty", "i"), ("Value", "t"), ("MPN", "t"), ("Manufacturer", "t"),
            ("Footprint", "t"), ("Package", "t"), ("Datasheet", "t"), ("Mouser Link", "t"),
            ("Description", "t"), ("Basic", "t"), ("RoHS", "t"), ("Country of Origin", "t")]
    if priced:
        cols += [("Source", "t"), ("Dist P/N", "t"), ("Unit Price", "n"), ("Ext Price", "n"),
                 ("Stock", "i"), ("Lifecycle", "t")]
    if build:
        cols += [("Min Qty", "i"), ("Final Qty", "i"), ("Order Unit Cost", "n"),
                 ("Cost @ Qty", "n"), ("Tariff %", "n"), ("Tax/Tariff", "n"), ("Total Cost", "n")]

    def values(r):
        refs = r.get("refs", [])
        v = {"Refs": ",".join(refs) if isinstance(refs, list) else str(refs),
             "Qty": _bom_line_qty(r), "Value": r.get("value", ""), "MPN": r.get("mpn", ""),
             "Manufacturer": r.get("manufacturer", ""), "Footprint": r.get("footprint", ""),
             "Package": r.get("package", ""), "Datasheet": r.get("datasheet", ""),
             # the distributor purchase link (canonical Mouser ProductDetail) the owner buys from
             "Mouser Link": r.get("url", ""),
             "Description": r.get("description", ""), "Basic": "yes" if r.get("basic") else "",
             "RoHS": r.get("rohs", ""), "Country of Origin": r.get("country_of_origin", "")}
        if priced:
            ext = r.get("extended")
            if ext is None:
                ext = line_extended(_coerce_price(r.get("unit_price")), _bom_line_qty(r))
            v.update({"Source": r.get("source", ""), "Dist P/N": _dist_pn(r),
                      "Unit Price": _coerce_price(r.get("unit_price")), "Ext Price": ext,
                      "Stock": r.get("stock", ""), "Lifecycle": r.get("lifecycle", "")})
        if build:
            v.update({"Min Qty": r.get("moq"), "Final Qty": r.get("final_qty"),
                      "Order Unit Cost": r.get("final_unit_price"),
                      "Cost @ Qty": r.get("final_extended"),
                      # per-part US import tariff: the % Mouser shows, and the $ it works out to
                      "Tariff %": r.get("tariff_rate"),
                      "Tax/Tariff": r.get("tax_tariff"), "Total Cost": r.get("line_total")})
        return v

    def _num(raw):
        if isinstance(raw, bool) or raw in (None, ""):
            return None
        if isinstance(raw, (int, float)):
            return raw
        return _coerce_price(raw)  # "$0.10", "5,000" -> float, else None

    def cell(ref, kind, raw, header=False):
        style = ' s="1"' if header else ""
        if kind in ("n", "i") and not header:
            n = _num(raw)
            if n is None:
                return f'<c r="{ref}"{style}/>'  # blank, not a text "0"
            if kind == "i":
                return f'<c r="{ref}"{style}><v>{int(round(n))}</v></c>'
            num = round(float(n), 6)  # currency precision, never sci-notation
            text = _xlsx_number(num)
            return f'<c r="{ref}"{style}><v>{text}</v></c>'
        s = "" if raw is None else str(raw)
        if s == "":
            return f'<c r="{ref}"{style}/>'
        return (f'<c r="{ref}"{style} t="inlineStr"><is>'
                f'<t xml:space="preserve">{_xlsx_escape(s)}</t></is></c>')

    all_vals = [values(r) for r in rows]
    widths = []
    for name, _k in cols:
        w = len(name)
        for v in all_vals:
            cv = v[name]
            w = max(w, len("" if cv is None else str(cv)))
        widths.append(min(max(w + 2, 8), 60))
    cols_xml = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                       for i, w in enumerate(widths))

    body = ["".join(cell(f"{_xlsx_col(i)}1", "t", name, header=True)
                    for i, (name, _k) in enumerate(cols))]
    row_xml = [f'<row r="1">{body[0]}</row>']
    # URL columns become real, clickable external hyperlinks. A generated xlsx does NOT
    # auto-linkify plain text, so without this the Datasheet/Mouser cells are dead when clicked
    # and read as "cut" in a narrow column. Each gets the blue-underline link style (s=2) and a
    # worksheet relationship to the external target.
    url_cols = {"Datasheet", "Mouser Link"}
    hyperlinks: list[tuple[str, str, str]] = []
    for ri, v in enumerate(all_vals, start=2):
        parts = []
        for i, (name, k) in enumerate(cols):
            ref = f"{_xlsx_col(i)}{ri}"
            val = v[name]
            if name in url_cols and isinstance(val, str) and val.startswith("http"):
                rid = f"rId{len(hyperlinks) + 1}"
                hyperlinks.append((ref, rid, val))
                parts.append(f'<c r="{ref}" s="2" t="inlineStr"><is>'
                             f'<t xml:space="preserve">{_xlsx_escape(val)}</t></is></c>')
            else:
                parts.append(cell(ref, k, val))
        row_xml.append(f'<row r="{ri}">{"".join(parts)}</row>')

    hl_xml = sheet_rels = ""
    if hyperlinks:
        hl_xml = "<hyperlinks>" + "".join(
            f'<hyperlink ref="{ref}" r:id="{rid}"/>' for ref, rid, _ in hyperlinks) + "</hyperlinks>"
        sheet_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                f'officeDocument/2006/relationships/hyperlink" Target="{_xlsx_escape(url)}" '
                'TargetMode="External"/>' for _, rid, url in hyperlinks)
            + "</Relationships>")

    last = _xlsx_col(len(cols) - 1)
    nr = len(all_vals) + 1
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{last}{nr}"/>'
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="A1:{last}{nr}"/>'
        f'{hl_xml}'
        '</worksheet>')
    return _xlsx_package(sheet, _XLSX_STYLES_BOLD, sheet_name="BOM", sheet_rels_xml=sheet_rels)


_REFDES_CATEGORY = {
    "R": "Resistor", "RN": "Resistor", "C": "Capacitor", "L": "Inductor",
    "FB": "Ferrite Bead", "Y": "Crystal", "X": "Crystal", "XTAL": "Crystal",
    "D": "Diode", "LED": "LED", "Q": "Transistor", "U": "IC", "IC": "IC",
    "J": "Connector", "P": "Connector", "CN": "Connector", "SW": "Switch", "S": "Switch",
    "K": "Relay", "F": "Fuse", "T": "Transformer", "BT": "Battery", "M": "Module",
}


def _refdes_category(ref: str) -> str:
    """A clean human category from a refdes prefix (R -> Resistor, U -> IC) for the
    procurement sheet's Description when the part carries no real description."""
    m = re.match(r"[A-Za-z]+", (ref or "").strip())
    return _REFDES_CATEGORY.get(m.group(0).upper(), "") if m else ""


def _vendor_domain(source: str) -> str:
    """The distributor's web domain from its name (Mouser -> mouser.com), matching how a
    purchasing sheet names the vendor. Unknown sources pass through unchanged."""
    s = (source or "").strip().lower()
    return {"mouser": "mouser.com", "digikey": "digikey.com", "digi-key": "digikey.com",
            "lcsc": "lcsc.com", "element14": "element14.com", "newark": "newark.com",
            "oshpark": "oshpark.com", "jlcpcb": "jlcpcb.com"}.get(s, source or "")


def _line_description(r) -> str:
    """The procurement Description for a BOM row: the part's real description when it has one,
    else a category from the refdes prefix, else the value."""
    desc = (r.get("description") or "").strip()
    if desc:
        return desc
    refs = _row_refs(r)
    cat = _refdes_category(refs[0]) if refs else ""
    return cat or (r.get("value") or "").strip()


def _procurement_note(*, priced: bool, spares_added: int, spares_pct: float) -> str:
    """The auto-generated Notes cell for a procurement line - it flags only the exceptions a
    buyer must act on. An unpriced line needs a manual quote; a passive whose QTY was padded
    for attrition says by how much so the inflated count is trusted. '' when priced and
    unpadded."""
    parts = []
    if not priced:
        parts.append("no price, request quote")
    if spares_added > 0:
        parts.append(f"+{spares_added} {'spare' if spares_added == 1 else 'spares'} "
                     f"({spares_pct:g}% attrition)")
    return "; ".join(parts)


def procurement_xlsx(rows, *, boards=1, spares_pct=0, pcb_multiple=3, tax_rate=0.0,
                     shipping=0.0, labour_per_board=0.0, assembly_surcharge_rate=0.0) -> bytes:
    """The buy-side procurement sheet as a clean Excel workbook, AUTO-POPULATED from the
    Mouser/DigiKey data we already fetch - the columns a buyer fills by hand: Description,
    P/N, Electronic Component?, Vendor, QTY, Unit Cost, Cost @ QTY, Tax/Tariff, Shipping,
    Total Cost, Product Link, Notes - with a bold TOTAL row, a frozen header, autofilter, and
    currency-formatted cost cells.

    Quantities model how the boards are actually built: PCBs ship in packs of `pcb_multiple`
    (default 3), so the effective build rounds the board count UP to the next multiple; QTY =
    per-board qty * effective boards, plus the `spares_pct` buffer on SMT passives only.
    Unit Cost is the volume-break price at that QTY. Cost @ QTY = QTY * Unit Cost; Tax/Tariff =
    Cost @ QTY * `tax_rate`; per-line Total = Cost @ QTY + Tax. `shipping` is one order-level
    charge added in the TOTAL row. Landed assembly (both default 0 = off): `labour_per_board`
    billed for the actual board count, `assembly_surcharge_rate` a fraction of the parts
    subtotal; when nonzero a single 'Assembly' line is folded into the grand Total (not taxed).
    Unpriced lines list quantities but leave money cells blank. Pure, offline, stdlib. Returns
    the .xlsx bytes."""
    import math
    n = _board_count(boards)
    try:
        mult = int(pcb_multiple)
    except (TypeError, ValueError):
        mult = 1
    mult = mult if mult >= 1 else 1
    eff_boards = math.ceil(n / mult) * mult  # boards rounded up to a full pack
    try:
        pct = max(0.0, float(spares_pct))
    except (TypeError, ValueError):
        pct = 0.0
    try:
        rate = max(0.0, float(tax_rate))
    except (TypeError, ValueError):
        rate = 0.0
    try:
        ship = max(0.0, float(shipping))
    except (TypeError, ValueError):
        ship = 0.0
    try:
        labour = max(0.0, float(labour_per_board))
    except (TypeError, ValueError):
        labour = 0.0
    try:
        surcharge_rate = max(0.0, float(assembly_surcharge_rate))
    except (TypeError, ValueError):
        surcharge_rate = 0.0

    # (header, kind): 't' text, 'i' integer, 'm' money (currency-styled number).
    cols = [("Description", "t"), ("P/N", "t"), ("Electronic Component?", "t"), ("Vendor", "t"),
            ("QTY", "i"), ("Unit Cost", "m"), ("Cost @ QTY", "m"), ("Tax/Tariff", "m"),
            ("Shipping", "m"), ("Total Cost", "m"), ("Product Link", "t"), ("Notes", "t")]

    def line(r):
        per_board = r.get("qty", r.get("total_qty", 0)) or 0
        try:
            per_board = int(per_board)
        except (TypeError, ValueError):
            per_board = 0
        qty = qty_raw = per_board * eff_boards
        spares_added = 0
        if pct and qty and _row_is_passive(r):  # spares pad passives only
            qty = math.ceil(qty * (1 + pct / 100.0))
            spares_added = qty - qty_raw
        ladder = r.get("price_breaks")
        unit = price_at_qty(ladder, qty) if ladder else None
        if unit is None:
            unit = _coerce_price(r.get("unit_price"))
        else:
            unit = _coerce_price(unit)
        cost = round(unit * qty, 4) if (unit is not None and qty) else None
        tax = round(cost * rate, 4) if cost is not None else None
        total = round(cost + tax, 4) if cost is not None else None
        return {"Description": _line_description(r), "P/N": _dist_pn(r) or (r.get("mpn") or ""),
                "Electronic Component?": "Yes", "Vendor": _vendor_domain(r.get("source")),
                "QTY": qty, "Unit Cost": unit, "Cost @ QTY": cost, "Tax/Tariff": tax,
                "Shipping": None, "Total Cost": total,
                "Product Link": r.get("url") or "",
                "Notes": _procurement_note(priced=unit is not None,
                                           spares_added=spares_added, spares_pct=pct)}

    data = [line(r) for r in rows]
    cost_sum = round(sum(d["Cost @ QTY"] for d in data if d["Cost @ QTY"] is not None), 4)
    tax_sum = round(sum(d["Tax/Tariff"] for d in data if d["Tax/Tariff"] is not None), 4)

    labour_total = round(labour * n, 4)
    surcharge = round(cost_sum * surcharge_rate, 4)
    assembly_total = round(labour_total + surcharge, 4)
    assembly_row = None
    if assembly_total > 0:
        bits = []
        if labour_total > 0:
            bits.append(f"labour ${labour:,.2f}/board x {n}")
        if surcharge > 0:
            bits.append(f"{surcharge_rate * 100:g}% surcharge on parts")
        assembly_row = {"Description": "Assembly", "Electronic Component?": "No",
                        "Cost @ QTY": assembly_total, "Total Cost": assembly_total,
                        "Notes": " + ".join(bits)}

    parts_and_assembly = round(cost_sum + assembly_total, 4)
    total_row = {"Description": "TOTAL", "Cost @ QTY": parts_and_assembly, "Tax/Tariff": tax_sum,
                 "Shipping": ship or None,
                 "Total Cost": round(parts_and_assembly + tax_sum + ship, 4)}

    def cell(ref, kind, raw, *, header=False, bold=False):
        if header:
            return (f'<c r="{ref}" s="1" t="inlineStr"><is>'
                    f'<t xml:space="preserve">{_xlsx_escape(raw)}</t></is></c>')
        if kind in ("i", "m"):
            num = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
            if num is None:
                return f'<c r="{ref}"/>'  # blank, never a text "0"
            if kind == "i":
                s = ' s="1"' if bold else ""
                return f'<c r="{ref}"{s}><v>{int(round(num))}</v></c>'
            s = ' s="3"' if bold else ' s="2"'  # currency (bold in the totals row)
            num = round(float(num), 6)
            text = _xlsx_number(num)
            return f'<c r="{ref}"{s}><v>{text}</v></c>'
        s = ' s="1"' if bold else ""
        txt = "" if raw is None else str(raw)
        if txt == "":
            return f'<c r="{ref}"{s}/>'
        return (f'<c r="{ref}"{s} t="inlineStr"><is>'
                f'<t xml:space="preserve">{_xlsx_escape(txt)}</t></is></c>')

    widths = []
    for name, _k in cols:
        w = len(name)
        for d in data:
            cv = d[name]
            w = max(w, len("" if cv is None else (f"{cv:.2f}" if isinstance(cv, float) else str(cv))))
        widths.append(min(max(w + 2, 10), 60))
    cols_xml = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                       for i, w in enumerate(widths))

    row_xml = ['<row r="1">' + "".join(
        cell(f"{_xlsx_col(i)}1", "t", name, header=True) for i, (name, _k) in enumerate(cols))
        + '</row>']
    for ri, d in enumerate(data, start=2):
        row_xml.append(f'<row r="{ri}">' + "".join(
            cell(f"{_xlsx_col(i)}{ri}", k, d[name]) for i, (name, k) in enumerate(cols)) + '</row>')
    next_r = len(data) + 2
    if assembly_row is not None:
        ar = next_r
        row_xml.append(f'<row r="{ar}">' + "".join(
            cell(f"{_xlsx_col(i)}{ar}",
                 "t" if name in ("Description", "Electronic Component?", "Notes") else k,
                 assembly_row.get(name)) for i, (name, k) in enumerate(cols)) + '</row>')
        next_r += 1
    tr = next_r
    total_cells = []
    for i, (name, kind) in enumerate(cols):
        ref = f"{_xlsx_col(i)}{tr}"
        if name in total_row and total_row[name] is not None:
            total_cells.append(cell(ref, "t" if name == "Description" else "m",
                                    total_row[name], bold=True))
        else:
            total_cells.append(f'<c r="{ref}"/>')
    row_xml.append(f'<row r="{tr}">' + "".join(total_cells) + '</row>')

    last = _xlsx_col(len(cols) - 1)
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}{tr}"/>'
        '<sheetViews><sheetView tabSelected="1" workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        f'<autoFilter ref="A1:{last}{len(data) + 1}"/>'
        '</worksheet>')
    return _xlsx_package(sheet, _XLSX_STYLES_CURRENCY, sheet_name="Procurement")


# ---------------------------------------------------------------------------
# the export dispatcher (router seam)
# ---------------------------------------------------------------------------

_SPREADSHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str) -> str:
    """A filesystem-safe slug of a project name for a download filename ('' -> 'project')."""
    s = _UNSAFE_NAME.sub("_", (name or "").strip()).strip("_")
    return s or "project"


# kind -> (filename suffix, extension, content type, is-binary)
_EXPORT_KINDS = {
    "csv": ("bom", ".csv", "text/csv", False),
    "priced": ("priced", ".csv", "text/csv", False),
    "cart": ("mouser_cart", ".csv", "text/csv", False),
    "jlcpcb": ("jlcpcb_bom", ".csv", "text/csv", False),
    "xlsx": ("bom", ".xlsx", _SPREADSHEET, True),
    "procurement": ("procurement", ".xlsx", _SPREADSHEET, True),
}


def project_bom_export(bom_result, kind, *, boards=None, spares_pct=0, pcb_multiple=3,
                       tax_rate=0.0, shipping=0.0, labour_per_board=0.0,
                       assembly_surcharge_rate=0.0) -> dict:
    """Render a cached project BOM into one export format (M7d). `kind` is one of csv /
    priced / cart / jlcpcb / xlsx / procurement. Returns {filename, content_type, data,
    kind}; `data` is str for a CSV kind, bytes for an XLSX kind. `boards` defaults to the
    build's board count. Raises ValueError for an unknown kind (mapped to 400)."""
    if kind not in _EXPORT_KINDS:
        raise ValueError(
            f"unknown export kind: {kind!r} (expected one of {', '.join(sorted(_EXPORT_KINDS))})"
        )
    rows = bom_result.get("lines") or []
    priced = bool(bom_result.get("priced"))
    n = _board_count(bom_result.get("boards", 1) if boards is None else boards)
    stem, ext, content_type, _binary = _EXPORT_KINDS[kind]
    name = _safe_name(bom_result.get("project", ""))

    if kind == "csv":
        data = bom_csv(rows, mode="project", priced=priced)
    elif kind == "priced":
        data = priced_bom_csv_at_qty(rows, n)["csv"]
    elif kind == "cart":
        data = procurement_cart_csv(rows, n, spares_pct)["csv"]
    elif kind == "jlcpcb":
        data = jlcpcb_bom_csv(rows)["csv"]
    elif kind == "xlsx":
        data = bom_xlsx(rows)
    else:  # procurement
        data = procurement_xlsx(rows, boards=n, spares_pct=spares_pct, pcb_multiple=pcb_multiple,
                                tax_rate=tax_rate, shipping=shipping,
                                labour_per_board=labour_per_board,
                                assembly_surcharge_rate=assembly_surcharge_rate)
    return {"filename": f"{name}_{stem}{ext}", "content_type": content_type,
            "data": data, "kind": kind}
