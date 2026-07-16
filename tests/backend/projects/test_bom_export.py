"""M7d: BOM / procurement export formats (CSV, XLSX, Mouser cart, JLCPCB, priced-at-qty).

Ports the retired app's export writers behavior-for-behavior. The XLSX writers are pure
stdlib (zipfile + hand-written OOXML), so nothing extra is bundled. Every function is
pure dict-in / str-or-bytes-out.
"""

import io
import zipfile

from stockroom.projects.bom_export import (
    _xlsx_col,
    _xlsx_number,
    bom_csv,
    bom_xlsx,
    jlcpcb_bom_csv,
    priced_bom_csv_at_qty,
    procurement_cart_csv,
    procurement_xlsx,
    project_bom_export,
)

# A small priced project BOM: an MPN'd IC (Mouser, ladder-priced, long lead) and a bare
# passive with no MPN (unpriced, a placement-only line).
_ROWS = [
    {"mpn": "TPS2121RUXR", "manufacturer": "TI", "value": "TPS2121", "footprint": "VQFN-16",
     "refs": ["U1"], "qty": 1, "unit_price": 1.25, "extended": 1.25,
     "price_breaks": [{"qty": 1, "price": 1.25}, {"qty": 100, "price": 0.98}],
     "stock": 5000, "lifecycle": "Active", "lead_time": "16 Weeks", "source": "Mouser",
     "mouser_pn": "595-TPS2121RUXR", "url": "http://mouser/p", "datasheet": "http://d",
     "description": "power mux", "basic": False},
    {"mpn": "", "value": "10k", "footprint": "R_0402", "refs": ["R1", "R2"], "qty": 2,
     "lcsc_pn": "C25804", "basic": True},
]


def _unzip(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert not z.testzip()  # a valid, uncorrupted archive
        return {n: z.read(n).decode() for n in z.namelist()}


# -- xlsx primitives -----------------------------------------------------------
def test_xlsx_col_letters():
    assert _xlsx_col(0) == "A"
    assert _xlsx_col(25) == "Z"
    assert _xlsx_col(26) == "AA"


def test_xlsx_number_never_scientific():
    assert _xlsx_number(5.0) == "5"
    assert _xlsx_number(0.00001) == "0.00001"  # never '1e-05', which Excel rejects


# -- bom_xlsx ------------------------------------------------------------------
def test_bom_xlsx_is_a_valid_workbook_with_numeric_cells():
    data = bom_xlsx(_ROWS)
    parts = _unzip(data)
    assert "xl/worksheets/sheet1.xml" in parts
    assert "[Content_Types].xml" in parts
    sheet = parts["xl/worksheets/sheet1.xml"]
    assert "TPS2121RUXR" in sheet
    assert "595-TPS2121RUXR" in sheet  # the Dist P/N column (priced build)
    # the Ext Price is a real number cell (<v>), not inline text, so Excel can sum it
    assert "<v>1.25</v>" in sheet


def test_bom_xlsx_unpriced_build_drops_the_priced_columns():
    rows = [{"mpn": "", "value": "10k", "refs": ["R1"], "qty": 1, "basic": True}]
    sheet = _unzip(bom_xlsx(rows))["xl/worksheets/sheet1.xml"]
    assert "Unit Price" not in sheet
    assert "Lifecycle" not in sheet
    assert "Final Qty" not in sheet  # no build economics on a value-only row


def test_bom_xlsx_includes_the_build_economics_columns():
    # A BOM built for a board count carries final_qty etc.; the XLSX (the primary deliverable)
    # must expose the order quantity + its cost + tariff + total, the numbers you order and budget
    # from - plus Package/RoHS. Numbers are real <v> cells so Excel can sum them.
    rows = [{"mpn": "ERJ-P03F1101V", "value": "100", "refs": ["R1", "R2"], "qty": 2,
             "unit_price": 0.10, "moq": 100, "final_qty": 100, "final_unit_price": 0.05,
             "final_extended": 5.0, "tax_tariff": 0.4125, "line_total": 5.4125,
             "package": "0603", "rohs": "Yes"}]
    sheet = _unzip(bom_xlsx(rows))["xl/worksheets/sheet1.xml"]
    for col in ("Package", "RoHS", "Min Qty", "Final Qty", "Cost @ Qty", "Tax/Tariff", "Total Cost"):
        assert col in sheet, f"missing XLSX column: {col}"
    assert "<v>100</v>" in sheet     # Final Qty (order quantity) as a real number
    assert "<v>5.4125</v>" in sheet  # Total Cost as a real number Excel can sum


def test_bom_xlsx_carries_mouser_link_origin_and_tariff():
    # The Full BOM must surface the purchase link (canonical Mouser ProductDetail), the
    # manufacturing country of origin, and the page's own per-part US import-tariff % - the
    # real fields the owner buys and budgets from. A priced China-origin build carries all three.
    rows = [{"mpn": "2N7002", "value": "2N7002", "refs": ["Q1"], "qty": 1, "unit_price": 1.09,
             "source": "Mouser", "mouser_pn": "512-2N7002",
             "url": "https://www.mouser.com/en/ProductDetail/onsemi/2N7002",
             "country_of_origin": "China", "moq": 1, "final_qty": 3, "final_unit_price": 1.09,
             "final_extended": 3.27, "tariff_rate": 7.98, "tax_tariff": 0.26, "line_total": 3.53}]
    sheet = _unzip(bom_xlsx(rows))["xl/worksheets/sheet1.xml"]
    for col in ("Mouser Link", "Country of Origin", "Tariff %"):
        assert col in sheet, f"missing XLSX column: {col}"
    assert "https://www.mouser.com/en/ProductDetail/onsemi/2N7002" in sheet
    assert "China" in sheet
    assert "<v>7.98</v>" in sheet  # tariff % as a real number Excel can sort/sum


# -- procurement_xlsx ----------------------------------------------------------
def test_procurement_xlsx_totals_and_tax():
    data = procurement_xlsx(_ROWS, boards=1, pcb_multiple=1, tax_rate=0.10, shipping=5.0)
    sheet = _unzip(data)["xl/worksheets/sheet1.xml"]
    assert "TOTAL" in sheet
    assert "http://mouser/p" in sheet  # the Product Link column
    # parts subtotal 1.25 (only the IC is priced) + 10% tax + $5 shipping -> a bold total
    assert "<v>1.375</v>" in sheet or "<v>6.375</v>" in sheet


def test_procurement_xlsx_is_a_valid_zip():
    assert not zipfile.ZipFile(io.BytesIO(procurement_xlsx(_ROWS))).testzip()


# -- mouser cart ---------------------------------------------------------------
def test_procurement_cart_csv_skips_no_mpn_and_scales_by_boards():
    out = procurement_cart_csv(_ROWS, boards=3)
    assert out["skipped_no_mpn"] == 1  # the bare passive has no MPN
    assert out["line_count"] == 1
    lines = out["csv"].strip().splitlines()
    assert lines[0] == "Mouser Part Number,Manufacturer Part Number,Quantity,Customer Reference"
    # the IC: 1 per board * 3 boards, with its Mouser P/N
    assert "595-TPS2121RUXR,TPS2121RUXR,3,U1" in out["csv"]


def test_procurement_cart_csv_pads_passives_with_spares():
    rows = [{"mpn": "RC0402", "value": "10k", "refs": ["R1"], "qty": 10}]
    out = procurement_cart_csv(rows, boards=1, spares_pct=10)
    assert out["padded_lines"] == 1
    assert ",11," in out["csv"]  # 10 + 10% -> 11 (rounded up)


# -- jlcpcb --------------------------------------------------------------------
def test_jlcpcb_bom_csv_places_by_designator_with_lcsc_pn():
    out = jlcpcb_bom_csv(_ROWS)
    assert out["line_count"] == 2  # both placed (assembly places passives too)
    assert out["with_lcsc"] == 1  # the passive carries an lcsc_pn
    lines = out["csv"].strip().splitlines()
    assert lines[0] == "Comment,Designator,Footprint,LCSC Part #"
    assert '10k,"R1,R2",R_0402,C25804' in out["csv"]


# -- priced-at-qty -------------------------------------------------------------
def test_priced_bom_csv_at_qty_scales_and_ranks():
    out = priced_bom_csv_at_qty(_ROWS, boards=100)
    assert out["boards"] == 100
    # the IC re-prices onto the 100-qty break (0.98) at order qty 100
    assert "0.9800" in out["csv"]
    assert out["priced_lines"] == 1
    assert out["unpriced_lines"] == 1


# -- bom_csv dispatcher --------------------------------------------------------
def test_bom_csv_project_mode_matches_the_builder_schema():
    csv = bom_csv(_ROWS, mode="project", priced=True)
    assert csv.splitlines()[0].startswith("Refs,Qty,Value,MPN,Manufacturer,Footprint")
    assert "Source" in csv.splitlines()[0]


# -- the export dispatcher -----------------------------------------------------
def _bom_result():
    return {"project": "Demo", "ran_at": "2026-07-13T00:00:00Z", "boards": 1,
            "priced": True, "line_count": 2, "component_count": 3, "lines": _ROWS,
            "summary": {"priced": True}}


def test_project_bom_export_dispatch_all_kinds():
    for kind, ext, is_binary in [
        ("csv", ".csv", False), ("priced", ".csv", False), ("cart", ".csv", False),
        ("jlcpcb", ".csv", False), ("xlsx", ".xlsx", True), ("procurement", ".xlsx", True),
    ]:
        out = project_bom_export(_bom_result(), kind)
        assert out["filename"].endswith(ext), kind
        assert "Demo" in out["filename"]
        if is_binary:
            assert isinstance(out["data"], (bytes, bytearray))
            assert out["content_type"] == (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            assert isinstance(out["data"], str)
            assert out["content_type"] == "text/csv"


def test_project_bom_export_rejects_an_unknown_kind():
    import pytest

    with pytest.raises(ValueError):
        project_bom_export(_bom_result(), "pdf")


def test_project_bom_export_passes_boards_to_the_quantity_scaled_kinds():
    out = project_bom_export(_bom_result(), "cart", boards=5)
    assert ",5,U1" in out["data"]  # the IC scaled to a run of 5
