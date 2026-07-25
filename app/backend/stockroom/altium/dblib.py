"""Render the Altium Database Library (.DbLib) as deterministic INI text. Committed +
stable; points at the committed stockroom-parts.db by a repo-relative path so the folder
is portable. The connection reaches the SQLite ODBC driver through the OLE DB -> ODBC
bridge (MSDASQL); if real Altium rejects the string the fix is a one-line change here
(fallbacks: a raw ODBC driver string, or a user DSN - see the 2026-07-23 migration spec)."""
from __future__ import annotations

from pathlib import Path

from stockroom.altium.odbc import SQLITE3_ODBC_DRIVER

# (xlsx column, Altium Design Parameter, VisibleOnAdd). A bracketed ParameterName is a
# reserved model/attribute binding; a bare name becomes an ordinary component parameter.
FIELD_MAP: list[tuple[str, str, bool]] = [
    ("MPN", "MPN", True),
    ("Library Ref", "[Library Ref]", False),
    ("Library Path", "[Library Path]", False),
    ("Footprint Ref", "[Footprint Ref]", False),
    ("Footprint Path", "[Footprint Path]", False),
    ("Value", "Value", True),
    ("Manufacturer", "Manufacturer", True),
    ("Description", "[Description]", True),
    ("Comment", "[Comment]", True),
    ("ComponentLink1Description", "ComponentLink1Description", False),
    ("ComponentLink1URL", "ComponentLink1URL", False),
    ("Supplier", "Supplier", False),
    ("SupplierPartNumber", "SupplierPartNumber", False),
    ("SupplierURL", "SupplierURL", False),
    ("Price", "Price", False),
    ("Stock", "Stock", False),
    ("Lifecycle", "Lifecycle", False),
    ("Category", "Category", False),
    # The durable placement binding. Altium copies a DbLib column onto the component it places,
    # so a part placed from this library arrives in the schematic already bound to its Stockroom
    # record with nothing recorded on Stockroom's side. The RECORD id, never the MPN: a binding
    # must survive an MPN correction, and two records can legitimately share an MPN.
    ("Stockroom ID", "Stockroom ID", False),
]

# Columns that are NOT record data fields, and why. Everything else in FIELD_MAP must be declared
# in the Altium tool's `data_fields` (eda/registry.py), which is what the detail sheet's handoff
# band renders; `tests/backend/eda/test_data_fields.py` fails on a column that is neither.
#
# These four exist because a .DbLib column layout is a wire format, not a record-field list: an
# asset reference splits into a Ref + a Path, a datasheet into a link Description + a URL, and the
# placement binding is already registry data on `EdaTool.placement_binding`. Each is the SECOND
# half of a pair whose first half is the declared field, or a value derived from one.
NON_FIELD_COLUMNS: dict[str, str] = {
    "Library Path": "the path half of the symbol reference; the Ref half is the `symbol` field",
    "Footprint Path": "the path half of the footprint reference; the Ref half is the `footprint` field",
    "Comment": "the placed symbol's display value, derived from `value` (spec 2026-07-23)",
    "ComponentLink1Description": "the label half of the datasheet link; the URL half is `datasheet`",
    "Stockroom ID": "the placement binding, declared by EdaTool.placement_binding",
}


def _connection_string(data_filename: str) -> str:
    return (
        "Provider=MSDASQL.1;Persist Security Info=False;"
        f'Extended Properties="DRIVER={SQLITE3_ODBC_DRIVER};'
        f"Database=.\\{data_filename};"
        'LongNames=0;Timeout=1000;NoTXN=0;SyncPragma=NORMAL;StepAPI=0;"'
    )


def render_dblib(table_name: str, data_filename: str) -> str:
    lines = [
        "[OutputDatabaseLinkFile]",
        "Version=1.1",
        "[DatabaseLinks]",
        f"ConnectionString={_connection_string(data_filename)}",
        "AddMode=3", "RemoveMode=1", "UpdateMode=2", "ViewMode=0",
        "LeftQuote=[", "RightQuote=]", "QuoteTableNames=1",
        "UseTableSchemaName=0", "DefaultColumnType=VARCHAR(255)",
        "LibraryDatabaseType=",
        f"LibraryDatabasePath=.\\{data_filename}",
        "DatabasePathRelative=1",
        "LibrarySearchPath=.",
        "[Table1]",
        "SchemaName=",
        f"TableName={table_name}",
        "Enabled=True",
        "UserWhere=0",
        "UserWhereText=",
    ]
    for i, (col, param, visible) in enumerate(FIELD_MAP, start=1):
        options = (
            f"FieldName={table_name}.{col}|TableNameOnly={table_name}|FieldNameOnly={col}"
            f"|FieldType=1|ParameterName={param}|VisibleOnAdd={visible}"
            f"|AddMode=0|RemoveMode=0|UpdateMode=0"
        )
        lines.append(f"[FieldMap{i}]")
        lines.append(f"Options={options}")
    return "\r\n".join(lines) + "\r\n"


def emit_dblib(table_name: str, data_filename: str, out_path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(render_dblib(table_name, data_filename))
