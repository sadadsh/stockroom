"""Emit the MPN-keyed SQLite data source (stockroom-parts.db) an Altium .DbLib reads
through the SQLite ODBC driver. Stdlib sqlite3. Column names are Altium's reserved names
where one exists, so the DbLib auto-maps.

DERIVED, and NOT committed (Batch 2 item 3, 2026-07-25). It was committed alongside the .DbLib so
a fresh clone was placeable with no regenerate step; `LibraryOps.ensure_altium_datasource` buys that
same property by rebuilding it on boot and on every profile switch, without sharing a binary two
peers can never merge.

On determinism, precisely, because the old docstring here claimed more than is true: the emit IS
byte-deterministic on ONE MACHINE (recreated from scratch, rows sorted, so identical records give
identical bytes, and that is what makes the staleness check a byte comparison). It is NOT
deterministic ACROSS machines: SQLite stamps its own library version number into the file header at
offset 96, so the same records emitted under SQLite 3.45.1 and 3.50.4 differ by two bytes. Measured
2026-07-25 on this machine's two interpreters. Even if that were normalized, two peers who add
DIFFERENT parts still produce genuinely different content in a format git cannot merge, which is
why the answer was to stop committing it rather than to chase byte equality."""
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
    # The durable placement binding Altium copies onto every component placed from this library.
    "Stockroom ID",
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
    altium = record.assets_for("altium")
    sym = altium.symbol
    fp = altium.footprint
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
        "Stockroom ID": record.id or "",
    }


def emit_db(records, out_path) -> int:
    """Write one table ("Parts", all TEXT columns = ALTIUM_COLUMNS), one row per record in
    stable MPN order. Returns the number of rows written.

    Recreated from scratch each emit, so on ONE machine the same records give byte-identical
    output. That is what lets `ensure_altium_datasource` detect staleness with a byte comparison.
    See the module docstring for why this does NOT hold across machines."""
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
