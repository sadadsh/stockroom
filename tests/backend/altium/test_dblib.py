from stockroom.altium.dblib import FIELD_MAP, emit_dblib, render_dblib


_ABS = "C:\\lib\\Stockroom\\altium\\stockroom-parts.db"


def test_render_has_core_sections_and_relative_path():
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_ABS)
    assert "[OutputDatabaseLinkFile]" in text
    assert "[DatabaseLinks]" in text
    assert "DatabasePathRelative=1" in text
    assert "LibraryDatabasePath=.\\stockroom-parts.db" in text
    assert "TableName=Parts" in text
    assert "\r\n" in text  # Altium files are CRLF


def test_render_uses_the_sqlite_odbc_bridge_not_ace():
    # Owner decision 2026-07-22: SQLite + ODBC (MSDASQL bridge), never the ACE/Office
    # provider with its bitness coupling. The database is named absolutely; see the
    # module docstring for the real-Altium measurement behind that.
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_ABS)
    assert "Provider=MSDASQL.1" in text
    assert "DRIVER=SQLite3 ODBC Driver" in text
    assert f"Database={_ABS};" in text
    assert "ACE.OLEDB" not in text
    assert "Excel" not in text


def test_render_maps_reserved_params_and_one_fieldmap_per_column():
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_ABS)
    assert "ParameterName=[Library Ref]" in text
    assert "ParameterName=[Footprint Path]" in text
    assert "ParameterName=[Comment]" in text  # the placed symbol's display value
    assert "ParameterName=Value" in text  # non-bracketed = ordinary parameter
    fieldmaps = text.count("[FieldMap")
    assert fieldmaps == len(FIELD_MAP) == 19  # 18 data columns + the "Stockroom ID" binding


def test_emit_writes_file(tmp_path):
    out = tmp_path / "Stockroom.DbLib"
    emit_dblib("Parts", "stockroom-parts.db", out, db_path=tmp_path / "stockroom-parts.db")
    assert out.read_text(encoding="utf-8").startswith("[OutputDatabaseLinkFile]")


def test_the_dblib_carries_the_stockroom_binding_column():
    """A component placed from this DbLib arrives in the schematic already bound to its library
    part, because Altium copies the column onto the placement. Stockroom cannot write a .SchDoc,
    so this is the only way an Altium placement can carry its own binding."""
    from stockroom.projects.binding import field_for

    field = field_for("altium")
    assert any(col == field and param == field for col, param, _v in FIELD_MAP), FIELD_MAP
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_ABS)
    assert f"FieldNameOnly={field}" in text


# --- The data source must be named by an ABSOLUTE path. -----------------------------------------
# Measured on the owner's real Windows install, 2026-07-26. Altium opened the generated .DbLib,
# parsed every section (it round-tripped our FieldMap entries back verbatim on save) and reported
# "Connection Failed. Check your connection settings." in red. Isolated with a single-variable ADO
# probe against the same driver: a relative `Database=` is resolved by the SQLite ODBC driver
# against the PROCESS working directory, and Altium's is never the .DbLib's folder.
#
#   relative + cwd = the .DbLib's folder   -> OK          (the shape our own probe used to "prove" it)
#   relative + cwd = anywhere else         -> connect failed
#   absolute                               -> OK
#
# Patching the real file to an absolute path and reopening turned "Connection Failed" into
# "Connected" with the field grid populated. Altium's own writer does the same thing: a real
# Altium-authored .DbLib carries an ABSOLUTE Data Source in ConnectionString while keeping
# LibraryDatabasePath relative (verified against two Altium-written files in the wild).

_DB = "C:\\lib\\Stockroom\\altium\\stockroom-parts.db"


def test_the_connection_string_names_the_database_absolutely():
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_DB)
    assert f"Database={_DB};" in text
    # the relative form is the bug, and it must not survive anywhere in the connection
    conn = next(ln for ln in text.splitlines() if ln.startswith("ConnectionString="))
    assert ".\\stockroom-parts.db" not in conn


def test_the_library_database_path_stays_relative():
    """Altium's own convention, and what makes the file re-relativizable: the connection is
    absolute, the display/portability path beside it is not."""
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_DB)
    assert "LibraryDatabasePath=.\\stockroom-parts.db" in text
    assert "DatabasePathRelative=1" in text


def test_render_carries_every_key_altium_writes_back():
    """Altium rewrites the whole file on save. Emitting exactly the keys it writes means an
    owner who opens the library and saves does not produce a diff, so a regenerate and an
    Altium save converge instead of fighting. Measured from a real save on AD26 (26.8.1)."""
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_DB)
    for key in ("TopPanelCollapsed=0", "OrcadMultiValueDelimiter=,",
                "SearchSubDirectories=1", "LastFocusedTable=Parts"):
        assert key in text, key


def test_emit_writes_the_absolute_path_of_the_db_beside_it(tmp_path):
    """The emitter derives the absolute path from where the .db actually is, so no caller has
    to know it and no machine-specific value is ever typed by hand."""
    out = tmp_path / "Stockroom.DbLib"
    db = tmp_path / "stockroom-parts.db"
    db.write_bytes(b"")
    emit_dblib("Parts", db.name, out, db_path=db)
    text = out.read_text(encoding="utf-8")
    assert f"Database={db}" in text


# -- the key field: what makes Altium INDEX the table rather than merely connect to it ----


def test_exactly_one_column_is_the_key_field_and_it_is_the_MPN():
    """`FieldType=0` marks a table's KEY field; every other column is `FieldType=1`.

    MEASURED 2026-07-26 in real AD26 on the owner's library, through
    `IDatabaseLibDocument`: with every column emitted as FieldType=1, Altium reported
    `GetKeyFieldCount=0` and `GetAllComponentKeys` returned ZERO components, so nothing could be
    browsed or placed even though the connection was green and the field grid populated. That is
    the second time this library looked healthy while being unusable: connecting is not indexing.

    Confirmed against an Altium-authored library in the wild (Wurth Elektronik's official
    Altium-Library, `WE - Active Components.DbLib`): exactly one FieldType=0 per table, and it is
    the Manufacturer Part Number.
    """
    text = render_dblib("Parts", "stockroom-parts.db", db_path=_ABS)
    keys = [ln for ln in text.splitlines() if "FieldType=0" in ln]
    assert len(keys) == 1, f"a table needs exactly one key field, found {len(keys)}"
    assert "FieldNameOnly=MPN|" in keys[0]
    # And nothing else may claim to be one.
    assert text.count("FieldType=1") == len(FIELD_MAP) - 1


def test_a_path_that_cannot_be_made_absolute_here_is_REFUSED_not_silently_mangled():
    """`emit_dblib` used to call `Path(db_path).resolve()`, which on a non-Windows host prepends
    the CURRENT WORKING DIRECTORY to a Windows path.

    This is not hypothetical: on 2026-07-26 it silently rewrote the owner's real library with
    `Database=/home/sadad/git/stockroom/C:\\stockroom-fresh-device\\...`, which parses, looks
    plausible, and fails at connect time with the exact error the absolute-path fix existed to
    remove. A machine-specific artifact must refuse a path it cannot spell rather than emit a
    broken one, because the breakage surfaces far from its cause.
    """
    import pytest

    with pytest.raises(ValueError, match="absolute"):
        emit_dblib("Parts", "stockroom-parts.db", "/tmp/x.DbLib", db_path="stockroom-parts.db")


def test_an_already_absolute_windows_path_survives_verbatim(tmp_path):
    """The complement, so the guard cannot be satisfied by refusing everything: a Windows-absolute
    path must reach the connection string byte-identical, on any host."""
    out = tmp_path / "Stockroom.DbLib"
    emit_dblib("Parts", "stockroom-parts.db", out, db_path="C:\\lib\\Stockroom\\stockroom-parts.db")
    assert "Database=C:\\lib\\Stockroom\\stockroom-parts.db;" in out.read_text(encoding="utf-8")
