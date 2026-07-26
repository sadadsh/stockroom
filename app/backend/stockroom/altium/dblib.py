"""Render the Altium Database Library (.DbLib) as deterministic INI text.

The connection reaches the SQLite ODBC driver through the OLE DB -> ODBC bridge (MSDASQL),
and it names the database by an ABSOLUTE path. That is not a style choice:

**Measured against real Altium (AD26 26.8.1) on the owner's machine, 2026-07-26.** With the
repo-relative `Database=.\\stockroom-parts.db` this file had shipped with, Altium opened the
document, parsed every section correctly, and reported "Connection Failed. Check your connection
settings." A single-variable ADO probe against the same driver isolated why: the SQLite ODBC
driver resolves a relative `Database=` against the PROCESS working directory, and Altium's is
never the .DbLib's own folder.

    relative + cwd = the .DbLib's folder  -> connects
    relative + cwd = anywhere else        -> connect failed
    absolute                              -> connects

Rewriting the real file with an absolute path and reopening it turned the red "Connection Failed"
into "Connected", with the field grid populated. Altium's own writer does exactly this: an
Altium-authored .DbLib carries an ABSOLUTE data source in ConnectionString while keeping
`LibraryDatabasePath` relative beside it (checked against two Altium-written files in the wild).

Because the connection is therefore machine-specific, the .DbLib is a DERIVED artifact, rebuilt
locally like the `.db` it points at, rather than shared through git. See `eda.registry` `_ALTIUM`.
"""
from __future__ import annotations

import re
from pathlib import Path

from stockroom.altium.odbc import SQLITE3_ODBC_DRIVER

# The column Altium indexes the table BY. Exactly one per table, emitted as `FieldType=0` while
# every other column is `FieldType=1`.
#
# MEASURED 2026-07-26 in real AD26 on the owner's library, through `IDatabaseLibDocument`: with
# every column emitted as FieldType=1, Altium reported `GetKeyFieldCount=0` and
# `GetAllComponentKeys` returned ZERO components. The library connected, parsed, and populated its
# field grid, and not one part could be browsed or placed, because a table with no key field has
# nothing to index rows by. Connecting is not indexing, and only the first half was ever measured.
#
# Confirmed against an Altium-authored library in the wild (Wurth Elektronik's official
# Altium-Library): exactly one FieldType=0 per table, and it is the Manufacturer Part Number.
KEY_COLUMN = "MPN"

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


def _connection_string(db_path: str) -> str:
    return (
        "Provider=MSDASQL.1;Persist Security Info=False;"
        f'Extended Properties="DRIVER={SQLITE3_ODBC_DRIVER};'
        f"Database={db_path};"
        'LongNames=0;Timeout=1000;NoTXN=0;SyncPragma=NORMAL;StepAPI=0;"'
    )


def render_dblib(table_name: str, data_filename: str, *, db_path: str) -> str:
    """`db_path` is the ABSOLUTE path of the SQLite file, and is required: see the module
    docstring for the measurement that makes a relative one a connection failure. Keeping it
    required means no caller can quietly re-emit the broken form."""
    lines = [
        "[OutputDatabaseLinkFile]",
        "Version=1.1",
        "[DatabaseLinks]",
        f"ConnectionString={_connection_string(str(db_path))}",
        "AddMode=3", "RemoveMode=1", "UpdateMode=2", "ViewMode=0",
        "LeftQuote=[", "RightQuote=]", "QuoteTableNames=1",
        "UseTableSchemaName=0", "DefaultColumnType=VARCHAR(255)",
        "LibraryDatabaseType=",
        # Relative, beside the absolute connection: this is the path Altium re-relativizes
        # against the .DbLib's own folder, and matching Altium's convention is what keeps a
        # regenerate and an Altium save from fighting over the file.
        f"LibraryDatabasePath=.\\{data_filename}",
        "DatabasePathRelative=1",
        # The four keys below plus LastFocusedTable are what Altium ITSELF writes into this
        # section on save (measured from a real AD26 save, 2026-07-26). Emitting them means an
        # owner who opens the library in Altium and saves produces no diff at all.
        "TopPanelCollapsed=0",
        "LibrarySearchPath=.",
        "OrcadMultiValueDelimiter=,",
        "SearchSubDirectories=1",
        "SchemaName=",
        f"LastFocusedTable={table_name}",
        "[Table1]",
        "SchemaName=",
        f"TableName={table_name}",
        "Enabled=True",
        "UserWhere=0",
        "UserWhereText=",
    ]
    for i, (col, param, visible) in enumerate(FIELD_MAP, start=1):
        # FieldType 0 marks the table's key column, 1 an ordinary mapped field. See KEY_COLUMN:
        # a table with no key field indexes zero components, however healthy it otherwise looks.
        field_type = 0 if col == KEY_COLUMN else 1
        options = (
            f"FieldName={table_name}.{col}|TableNameOnly={table_name}|FieldNameOnly={col}"
            f"|FieldType={field_type}|ParameterName={param}|VisibleOnAdd={visible}"
            f"|AddMode=0|RemoveMode=0|UpdateMode=0"
        )
        lines.append(f"[FieldMap{i}]")
        lines.append(f"Options={options}")
    return "\r\n".join(lines) + "\r\n"


def absolute_data_source(db_path) -> str:
    """`db_path` as an absolute string Altium can open, or a ValueError naming the problem.

    This used to be `str(Path(db_path).resolve())`, and that is a silent corruption off the host
    it was written for: `Path("C:\\lib\\x.db").resolve()` on Linux is not a Windows path, it is the
    CURRENT WORKING DIRECTORY with the Windows path glued on the end. Measured 2026-07-26, it
    rewrote the owner's real library as
    `Database=/home/sadad/git/stockroom/C:\\stockroom-fresh-device\\...`, which parses fine, looks
    plausible, and fails at connect time with the very error the absolute-path fix removed.

    So a Windows-absolute path is passed through UNTOUCHED on every host, a native absolute path is
    accepted, and anything relative is REFUSED. Refusing is the point: this file is only ever
    consumed by Windows Altium, and a wrong path here surfaces far from its cause.
    """
    text = str(db_path)
    # `C:\...` or `\\server\share\...`: already absolute for the only program that reads this file.
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\"):
        return text
    path = Path(text)
    if path.is_absolute():
        return str(path)
    raise ValueError(
        f"the Altium data source path must be absolute, got {text!r}. A relative path is resolved "
        "by the SQLite ODBC driver against the process working directory, which is never the "
        "library folder, so Altium would answer it with 'Connection Failed'."
    )


def emit_dblib(table_name: str, data_filename: str, out_path, *, db_path) -> None:
    """`db_path` is the data source's real location; its absolute form is what the connection
    string carries, so no caller has to know how to spell a machine-specific path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(render_dblib(table_name, data_filename, db_path=absolute_data_source(db_path)))
