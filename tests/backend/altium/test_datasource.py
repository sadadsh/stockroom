import sqlite3

from stockroom.altium.datasource import ALTIUM_COLUMNS, emit_db, row_for
from stockroom.model.part import AltiumRef, Datasheet, PartRecord, Purchase


def _part():
    return PartRecord(
        id="bq24074rgtt", display_name="BQ24074 Charger", category="ICs",
        mpn="BQ24074RGTT", manufacturer="Texas Instruments", value="BQ24074RGTT",
        description="Li-Ion charger, VQFN-16",
        datasheet=Datasheet(source_url="https://ti.com/ds.pdf"),
        purchase=[Purchase(vendor="DigiKey", part_number="296-1", url="https://dk/1", stock=42)],
        altium_symbol=AltiumRef(lib="BQ24074RGTT.SchLib", name="BQ24074RGTT"),
        altium_footprint=AltiumRef(lib="BQ24074RGTT.PcbLib", name="VQFN-16"),
    )


def _passive():
    return PartRecord(
        id="rc0603", display_name="10k Resistor", category="Resistors",
        mpn="RC0603FR-0710KL", manufacturer="Yageo", value="",
        description="10 kOhm 1% 0603",
        specs={"Resistance": "10 kOhms"},
        altium_symbol=AltiumRef(lib="rc0603.SchLib", name="RC0603"),
        altium_footprint=AltiumRef(lib="rc0603.PcbLib", name="R0603"),
    )


def _select_all(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("Parts")')]
        rows = list(conn.execute('SELECT * FROM "Parts"'))
        return cols, rows
    finally:
        conn.close()


def test_row_maps_reserved_and_field_columns():
    row = row_for(_part())
    assert row["MPN"] == "BQ24074RGTT"
    assert row["Library Ref"] == "BQ24074RGTT"
    assert row["Library Path"] == "BQ24074RGTT.SchLib"
    assert row["Footprint Ref"] == "VQFN-16"
    assert row["Footprint Path"] == "BQ24074RGTT.PcbLib"
    assert row["Value"] == "BQ24074RGTT"
    assert row["Manufacturer"] == "Texas Instruments"
    assert row["Description"] == "Li-Ion charger, VQFN-16"
    assert row["ComponentLink1URL"] == "https://ti.com/ds.pdf"
    assert row["ComponentLink1Description"] == "Datasheet"
    assert row["SupplierPartNumber"] == "296-1"
    assert row["Stock"] == "42"


def test_row_comment_is_mpn_for_actives_and_value_for_passives():
    # [Comment] is what the placed symbol displays: an active reads as its MPN, a passive
    # as its parametric value (the schematic convention), mirroring the Value derivation.
    assert row_for(_part())["Comment"] == "BQ24074RGTT"
    assert row_for(_passive())["Comment"] == "10k"


def test_columns_carry_comment_after_description():
    i = ALTIUM_COLUMNS.index("Description")
    assert ALTIUM_COLUMNS[i + 1] == "Comment"
    assert len(ALTIUM_COLUMNS) == 18


def test_emit_writes_parts_table_sorted(tmp_path):
    out = tmp_path / "stockroom-parts.db"
    n = emit_db([_passive(), _part()], out)
    assert n == 2
    cols, rows = _select_all(out)
    assert cols == ALTIUM_COLUMNS
    # sorted by MPN (case-insensitive): BQ24074RGTT before RC0603FR-0710KL
    assert [r[0] for r in rows] == ["BQ24074RGTT", "RC0603FR-0710KL"]


def test_emit_is_deterministic_bytes(tmp_path):
    # The .db is COMMITTED to the library repo, so re-emitting unchanged records must
    # produce identical bytes (no churn commits, and regenerate stays idempotent).
    a = tmp_path / "a.db"
    b = tmp_path / "b.db"
    emit_db([_part(), _passive()], a)
    emit_db([_part(), _passive()], b)
    assert a.read_bytes() == b.read_bytes()


def test_emit_overwrites_a_previous_larger_file(tmp_path):
    out = tmp_path / "stockroom-parts.db"
    emit_db([_part(), _passive()], out)
    n = emit_db([_part()], out)
    assert n == 1
    _, rows = _select_all(out)
    assert len(rows) == 1
