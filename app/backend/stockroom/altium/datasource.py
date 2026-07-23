"""Emit the MPN-keyed SQLite data source (stockroom-parts.db) an Altium .DbLib reads
through the SQLite ODBC driver. Stdlib sqlite3, deterministic bytes, COMMITTED to the
library repo with the .DbLib so a fresh clone is placeable with no regenerate step.
Column names are Altium's reserved names where one exists, so the DbLib auto-maps."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from stockroom.ingest.component_naming import derive_value

ALTIUM_COLUMNS: list[str] = [
    "MPN", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path",
    "Value", "Manufacturer", "Description", "Comment",
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
        # A persisted record.value wins; otherwise derive it (a passive's parametric value, an
        # active's MPN). Nothing in the real pipeline persists value yet, so deriving here is what
        # makes the Value column populate + keeps the emitter independent of that field.
        "Value": record.value or derive_value(record),
        "Manufacturer": record.manufacturer or "",
        "Description": record.description or "",
        # [Comment] is the placed symbol's display value: an active reads as its MPN, a
        # passive as its parametric value - the same derivation as Value (spec 2026-07-23).
        "Comment": record.value or derive_value(record),
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


def emit_db(records, out_path) -> int:
    """Write one table ("Parts", all TEXT columns = ALTIUM_COLUMNS), one row per record in
    stable MPN order. Returns the number of rows written. Deterministic BYTES: the file is
    recreated from scratch each emit (same records -> identical file, so the committed .db
    never churns and regenerate stays idempotent)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)  # recreate from scratch: deterministic page layout
    cols = ", ".join(f'"{c}" TEXT' for c in ALTIUM_COLUMNS)
    placeholders = ", ".join("?" for _ in ALTIUM_COLUMNS)
    conn = sqlite3.connect(out_path)
    try:
        conn.execute(f'CREATE TABLE "Parts" ({cols})')
        n = 0
        for record in sorted(records, key=lambda r: (r.mpn or "").upper()):
            row = row_for(record)
            conn.execute(
                f'INSERT INTO "Parts" VALUES ({placeholders})',
                [row.get(col, "") for col in ALTIUM_COLUMNS],
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n
