"""Emit the MPN-keyed .xlsx data source an Altium .DbLib reads. Pure openpyxl; a
derived, gitignored artifact regenerated from the JSON records. Column headers are
Altium's reserved names where one exists, so the DbLib auto-maps with no manual work."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

ALTIUM_COLUMNS: list[str] = [
    "MPN", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path",
    "Value", "Manufacturer", "Description",
    "ComponentLink1Description", "ComponentLink1URL",
    "Supplier", "SupplierPartNumber", "SupplierURL",
    "Price", "Stock", "Lifecycle", "Category",
]


def _datasheet_url(record) -> str:
    ds = record.datasheet
    if ds is None:
        return ""
    return ds.source_url or (ds.file or "")


def _first_purchase(record):
    return record.purchase[0] if record.purchase else None


def _price(record) -> str:
    p = _first_purchase(record)
    if p is None or not p.price_breaks:
        return ""
    # lowest unit price across breaks; breaks are [{"qty":.., "price":..}, ...]
    try:
        prices = [
            float(b.get("price"))
            for b in p.price_breaks
            if isinstance(b, dict) and b.get("price") is not None
        ]
        return f"{min(prices):.4f}" if prices else ""
    except (TypeError, ValueError):
        return ""


def row_for(record) -> dict[str, str]:
    sym = record.altium_symbol
    fp = record.altium_footprint
    p = _first_purchase(record)
    return {
        "MPN": record.mpn or "",
        "Library Ref": (sym.name if sym else "") or "",
        "Library Path": (sym.lib if sym else "") or "",
        "Footprint Ref": (fp.name if fp else "") or "",
        "Footprint Path": (fp.lib if fp else "") or "",
        "Value": record.value or "",
        "Manufacturer": record.manufacturer or "",
        "Description": record.description or "",
        "ComponentLink1Description": "Datasheet" if _datasheet_url(record) else "",
        "ComponentLink1URL": _datasheet_url(record),
        "Supplier": (p.vendor if p else "") or "",
        "SupplierPartNumber": (p.part_number if p else "") or "",
        "SupplierURL": (p.url if p else "") or "",
        "Price": _price(record),
        "Stock": "" if (p is None or p.stock is None) else str(p.stock),
        "Lifecycle": str(record.specs.get("Lifecycle", "") or "") if getattr(record, "specs", None) else "",
        "Category": record.category or "",
    }


def emit_xlsx(records, out_path) -> int:
    """Write one worksheet ("Parts"), header row = ALTIUM_COLUMNS, one row per record in
    stable MPN order. Returns the number of data rows written. Deterministic."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Parts"
    ws.append(ALTIUM_COLUMNS)
    n = 0
    for record in sorted(records, key=lambda r: (r.mpn or "").upper()):
        row = row_for(record)
        ws.append([row.get(col, "") for col in ALTIUM_COLUMNS])
        n += 1
    wb.save(out_path)
    return n
