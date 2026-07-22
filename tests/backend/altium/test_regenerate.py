from openpyxl import load_workbook

from stockroom.model.part import AltiumRef, PartRecord


def _place_ready(pid, mpn):
    return PartRecord(
        id=pid, display_name=pid, category="ICs", mpn=mpn, manufacturer="TI",
        description="d", value=mpn,
        altium_symbol=AltiumRef(lib=f"{pid}.SchLib", name=mpn),
        altium_footprint=AltiumRef(lib=f"{pid}.PcbLib", name="FP"),
    )


def test_regenerate_emits_only_place_ready(library_ops):
    ops = library_ops
    ops.lib.parts_dir.mkdir(parents=True, exist_ok=True)
    (ops.lib.parts_dir / "a.json").write_text(_place_ready("a", "AAA").dumps(), encoding="utf-8")
    # not place-ready: no altium refs
    (ops.lib.parts_dir / "b.json").write_text(
        PartRecord(id="b", display_name="b", category="ICs", mpn="BBB").dumps(), encoding="utf-8")

    result = ops.regenerate_altium_dblib()

    assert result["emitted"] == 1
    assert "b" in result["skipped"]
    assert result["dblib"].exists()
    assert result["xlsx"].exists()
    ws = load_workbook(result["xlsx"])["Parts"]
    mpns = [row[0].value for row in ws.iter_rows(min_row=2)]
    assert mpns == ["AAA"]
