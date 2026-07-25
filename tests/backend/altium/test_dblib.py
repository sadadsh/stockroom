from stockroom.altium.dblib import FIELD_MAP, emit_dblib, render_dblib


def test_render_has_core_sections_and_relative_path():
    text = render_dblib("Parts", "stockroom-parts.db")
    assert "[OutputDatabaseLinkFile]" in text
    assert "[DatabaseLinks]" in text
    assert "DatabasePathRelative=1" in text
    assert "LibraryDatabasePath=.\\stockroom-parts.db" in text
    assert "TableName=Parts" in text
    assert "\r\n" in text  # Altium files are CRLF


def test_render_uses_the_sqlite_odbc_bridge_not_ace():
    # Owner decision 2026-07-22: SQLite + ODBC (MSDASQL bridge), never the ACE/Office
    # provider with its bitness coupling.
    text = render_dblib("Parts", "stockroom-parts.db")
    assert "Provider=MSDASQL.1" in text
    assert "DRIVER=SQLite3 ODBC Driver" in text
    assert "Database=.\\stockroom-parts.db" in text
    assert "ACE.OLEDB" not in text
    assert "Excel" not in text


def test_render_maps_reserved_params_and_one_fieldmap_per_column():
    text = render_dblib("Parts", "stockroom-parts.db")
    assert "ParameterName=[Library Ref]" in text
    assert "ParameterName=[Footprint Path]" in text
    assert "ParameterName=[Comment]" in text  # the placed symbol's display value
    assert "ParameterName=Value" in text  # non-bracketed = ordinary parameter
    fieldmaps = text.count("[FieldMap")
    assert fieldmaps == len(FIELD_MAP) == 19  # 18 data columns + the "Stockroom ID" binding


def test_emit_writes_file(tmp_path):
    out = tmp_path / "Stockroom.DbLib"
    emit_dblib("Parts", "stockroom-parts.db", out)
    assert out.read_text(encoding="utf-8").startswith("[OutputDatabaseLinkFile]")


def test_the_dblib_carries_the_stockroom_binding_column():
    """A component placed from this DbLib arrives in the schematic already bound to its library
    part, because Altium copies the column onto the placement. Stockroom cannot write a .SchDoc,
    so this is the only way an Altium placement can carry its own binding."""
    from stockroom.projects.binding import field_for

    field = field_for("altium")
    assert any(col == field and param == field for col, param, _v in FIELD_MAP), FIELD_MAP
    text = render_dblib("Parts", "stockroom-parts.db")
    assert f"FieldNameOnly={field}" in text
