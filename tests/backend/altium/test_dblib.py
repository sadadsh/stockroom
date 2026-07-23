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
    assert fieldmaps == len(FIELD_MAP) == 18


def test_emit_writes_file(tmp_path):
    out = tmp_path / "Stockroom.DbLib"
    emit_dblib("Parts", "stockroom-parts.db", out)
    assert out.read_text(encoding="utf-8").startswith("[OutputDatabaseLinkFile]")
