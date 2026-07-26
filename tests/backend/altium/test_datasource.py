import sqlite3

from stockroom.altium.datasource import ALTIUM_COLUMNS, emit_db, row_for
from stockroom.model.part import AssetRef, Datasheet, EdaAssets, PartRecord, Purchase


def _part():
    return PartRecord(
        id="bq24074rgtt", display_name="BQ24074 Charger", category="ICs",
        mpn="BQ24074RGTT", manufacturer="Texas Instruments", value="BQ24074RGTT",
        description="Li-Ion charger, VQFN-16",
        datasheet=Datasheet(source_url="https://ti.com/ds.pdf"),
        purchase=[Purchase(vendor="DigiKey", part_number="296-1", url="https://dk/1", stock=42)],
        eda={"altium": EdaAssets(
            symbol=AssetRef(lib="BQ24074RGTT.SchLib", name="BQ24074RGTT"),
            footprint=AssetRef(lib="BQ24074RGTT.PcbLib", name="VQFN-16"),
        )},
    )


def _passive():
    return PartRecord(
        id="rc0603", display_name="10k Resistor", category="Resistors",
        mpn="RC0603FR-0710KL", manufacturer="Yageo", value="",
        description="10 kOhm 1% 0603",
        specs={"Resistance": "10 kOhms"},
        eda={"altium": EdaAssets(
            symbol=AssetRef(lib="rc0603.SchLib", name="RC0603"),
            footprint=AssetRef(lib="rc0603.PcbLib", name="R0603"),
        )},
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
    assert len(ALTIUM_COLUMNS) == 19  # 18 data columns + the durable "Stockroom ID" binding


def test_emit_writes_parts_table_sorted(tmp_path):
    out = tmp_path / "stockroom-parts.db"
    n = emit_db([_passive(), _part()], out)
    assert n == 2
    cols, rows = _select_all(out)
    assert cols == ALTIUM_COLUMNS
    # sorted by MPN (case-insensitive): BQ24074RGTT before RC0603FR-0710KL
    assert [r[0] for r in rows] == ["BQ24074RGTT", "RC0603FR-0710KL"]


def test_emit_is_deterministic_bytes_on_one_machine(tmp_path):
    # This is what `ensure_altium_datasource` relies on to detect staleness with a byte
    # comparison. It holds on ONE machine only: SQLite stamps its own library version into the
    # header, so the same records under 3.45.1 and 3.50.4 differ by two bytes (measured
    # 2026-07-25). Cross-machine byte equality is deliberately NOT claimed anywhere, and is why
    # the derived .db stopped being committed rather than being chased toward byte stability.
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


def test_the_row_carries_the_stockroom_part_id_so_a_placement_is_born_bound():
    """The id is the RECORD id, not the MPN: a binding must survive an MPN correction, and two
    records can legitimately share an MPN."""
    from stockroom.projects.binding import field_for

    rec = _part()
    row = row_for(rec)
    assert row[field_for("altium")] == rec.id
    assert field_for("altium") in ALTIUM_COLUMNS


def test_a_local_only_datasheet_does_not_become_a_dead_altium_link():
    """A DbLib link column can carry a URL and nothing else.

    `_datasheet_url` fell back to `record.datasheet.file` - a BARE FILENAME like
    "TPD6E05U06RVZR.pdf" - which Altium cannot resolve to anything, while
    `ComponentLink1Description` was set to "Datasheet" beside it. So a part whose datasheet is a
    local PDF advertised a link that goes nowhere, which is worse than no link: the person clicks
    it before finding out.

    KiCad has the opposite capability and keeps the opposite precedence: it resolves
    `${SR_LIB}/datasheets/<file>` through a path variable it holds in its own config, so a local
    file there is BETTER than a URL. The difference is a fact about each tool, so it is registry
    data now (`EdaTool.datasheet_sources`), not two hand-written orders that drifted apart.
    """

    rec = PartRecord(id="x", display_name="X", category="ICs", mpn="X", manufacturer="M")
    rec.datasheet = Datasheet(file="X.pdf", source_url="")
    row = row_for(rec)
    assert row["ComponentLink1URL"] == ""
    assert row["ComponentLink1Description"] == "", (
        "a link description with no link advertises a datasheet that is not there"
    )

    # ...and a URL still works exactly as before.
    rec.datasheet = Datasheet(file="X.pdf", source_url="https://ti.com/ds.pdf")
    row = row_for(rec)
    assert row["ComponentLink1URL"] == "https://ti.com/ds.pdf"
    assert row["ComponentLink1Description"] == "Datasheet"


def test_each_tool_states_which_datasheet_forms_it_can_actually_use():
    """The precedence lives on the adapter as DATA, so adding a third tool is a registry entry."""
    from stockroom.eda.registry import get_tool

    assert get_tool("kicad").datasheet_sources == ("file", "url")
    assert get_tool("altium").datasheet_sources == ("url",)
