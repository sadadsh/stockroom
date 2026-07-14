"""M7c: the project BOM builder (grouping + KiBoM value-normalization + cost).

Ports the retired app's PROJ-08/09 BOM builder + cost tests behavior-for-behavior onto
Stockroom's sexp-fed reader, and adds the KiBoM value-normalization + exclusion layer
and the enrich->price adapter. Pure compute: no kicad-cli, no network.
"""

from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
from stockroom.projects import kibom
from stockroom.projects.bom import (
    _bom_components,
    _board_count,
    _row_cost_at_qty,
    bom_cost_at_qty,
    bom_cost_by_source,
    bom_cost_summary,
    bom_from_kicad_schematic,
    bom_from_project,
    consolidated_bom,
    enrichment_to_bom_lookup,
    is_basic_part,
    line_extended,
    price_at_qty,
    project_bom,
    _coerce_price,
    _price_rows,
)


def _sym(ref, value, lib="Device:R", mpn=None, mfr=None, fp="", extra=""):
    props = [
        f'    (property "Reference" "{ref}" (at 0 0 0))',
        f'    (property "Value" "{value}" (at 0 0 0))',
    ]
    if fp:
        props.append(f'    (property "Footprint" "{fp}" (at 0 0 0))')
    if mpn:
        props.append(f'    (property "MPN" "{mpn}" (at 0 0 0))')
    if mfr:
        props.append(f'    (property "MANUFACTURER" "{mfr}" (at 0 0 0))')
    body = "\n".join(props)
    return f'  (symbol\n    (lib_id "{lib}")\n{body}\n    {extra}\n  )\n'


def _write_sch(path, *symbols):
    path.write_text("(kicad_sch\n" + "".join(symbols) + ")\n", encoding="utf-8")
    return path


# -- basic-part detection ------------------------------------------------------
def test_is_basic_part_true_for_valued_passive():
    assert is_basic_part("R5", "10k", None) is True
    assert is_basic_part("C12", "100nF", "") is True
    assert is_basic_part("L1", "4.7uH", None) is True


def test_is_basic_part_false_when_mpn_present_or_not_passive():
    assert is_basic_part("R5", "10k", "RC0402FR-0710KL") is False
    assert is_basic_part("U3", "STM32", None) is False
    assert is_basic_part("R5", "", None) is False


def test_bom_rows_carry_basic_flag(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("U1", "TPS2121", lib="Device:U", mpn="TPS2121RUXR", mfr="TI"))
    by_ref = {r["refs"][0]: r for r in bom_from_kicad_schematic(str(f))["rows"]}
    assert by_ref["R1"]["basic"] is True
    assert by_ref["U1"]["basic"] is False


# -- multi-sheet aggregation + identity grouping -------------------------------
def test_bom_from_project_merges_sheets(tmp_path):
    a = _write_sch(tmp_path / "a.kicad_sch", _sym("R1", "10k"))
    b = _write_sch(tmp_path / "b.kicad_sch", _sym("R2", "10k"), _sym("C1", "1uF", lib="Device:C"))
    bom = bom_from_project([str(a), str(b)])
    tenk = [r for r in bom["rows"] if r["value"] == "10k"][0]
    assert tenk["qty"] == 2 and set(tenk["refs"]) == {"R1", "R2"}
    assert bom["component_count"] == 3


def test_bom_does_not_merge_different_manufacturers(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k", mfr="Yageo"), _sym("R2", "10k", mfr="Vishay"))
    mfrs = {r["manufacturer"] for r in bom_from_kicad_schematic(str(f))["rows"] if r["value"] == "10k"}
    assert mfrs == {"Yageo", "Vishay"}


def test_bom_never_puts_value_in_mpn_for_a_passive(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch", _sym("R1", "10k", mfr="Yageo"))
    r = bom_from_kicad_schematic(str(f))["rows"][0]
    assert r["mpn"] == ""
    assert r["basic"] is True
    assert r["has_real_mpn"] is False


def test_bom_ic_value_is_mpn_when_manufacturer_present(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch", _sym("U1", "TPS2121RUXR", lib="Device:U", mfr="TI"))
    r = bom_from_kicad_schematic(str(f))["rows"][0]
    assert r["mpn"] == "TPS2121RUXR" and r["basic"] is False and r["has_real_mpn"] is True


def test_bom_enriches_manufacturer_from_lookup(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("U1", "TPS2121RUXR", lib="Device:U", mpn="TPS2121RUXR"))
    lookup = lambda mpn: {"manufacturer": "Texas Instruments"} if mpn == "TPS2121RUXR" else None
    u1 = [r for r in bom_from_kicad_schematic(str(f), lookup=lookup)["rows"] if r["refs"] == ["U1"]][0]
    assert u1["manufacturer"] == "Texas Instruments"


# -- KiBoM value normalization + exclusion (M7c-2) -----------------------------
def test_normalize_value_merges_metric_equivalents():
    assert kibom.normalize_value("4.7k") == kibom.normalize_value("4700")
    assert kibom.normalize_value("4.7k") == kibom.normalize_value("4k7")
    assert kibom.normalize_value("100nF") == kibom.normalize_value("0.1uF")
    assert kibom.normalize_value("100nF") == kibom.normalize_value("100n")


def test_normalize_value_keeps_unlike_values_apart_and_falls_back():
    assert kibom.normalize_value("4.7k") != kibom.normalize_value("47k")
    # an unparseable value (an MPN, a label) folds to its case-folded self, never merged
    assert kibom.normalize_value("TPS2121RUXR") == "tps2121ruxr"
    assert kibom.normalize_value("4.7k") != kibom.normalize_value("STM32")


def test_bom_merges_value_normalized_passives(tmp_path):
    # 4.7k and 4700 are the same resistor value: one line, qty 2.
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "4.7k", fp="Resistor_SMD:R_0402"),
                   _sym("R2", "4700", fp="Resistor_SMD:R_0402"))
    rows = [r for r in bom_from_kicad_schematic(str(f))["rows"] if r["footprint"]]
    assert len(rows) == 1 and rows[0]["qty"] == 2 and set(rows[0]["refs"]) == {"R1", "R2"}


def test_bom_merges_c_small_and_cap_by_value_and_footprint(tmp_path):
    # KiBoM groups C and C_Small; Stockroom keys on footprint (not symbol name), so a
    # C_Small 100nF and a C 0.1uF on the same footprint already merge into one line.
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("C1", "100nF", lib="Device:C_Small", fp="Capacitor_SMD:C_0402"),
                   _sym("C2", "0.1uF", lib="Device:C", fp="Capacitor_SMD:C_0402"))
    rows = bom_from_kicad_schematic(str(f))["rows"]
    assert len(rows) == 1 and rows[0]["qty"] == 2 and set(rows[0]["refs"]) == {"C1", "C2"}


def test_bom_excludes_testpoints_fiducials_and_mounting_holes(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("TP1", "TP", lib="Connector:TestPoint"),
                   _sym("FID1", "Fiducial", lib="Connector:Fiducial"),
                   _sym("H1", "MountingHole", lib="Mechanical:MountingHole",
                        fp="MountingHole:MountingHole_3.2mm"))
    refs = {r["refs"][0] for r in bom_from_kicad_schematic(str(f))["rows"]}
    assert refs == {"R1"}


def test_bom_excludes_do_not_fit_parts(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("R2", "DNP", fp="Resistor_SMD:R_0402"),
                   _sym("R3", "10k", fp="Resistor_SMD:R_0402",
                        extra='(property "Config" "DNF" (at 0 0 0))'))
    refs = {r["refs"][0] for r in bom_from_kicad_schematic(str(f))["rows"]}
    assert refs == {"R1"}


def test_bom_excludes_dnp_and_exclude_from_bom_tokens(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("R2", "10k", fp="Resistor_SMD:R_0402", extra="(dnp yes)"),
                   _sym("R3", "10k", fp="Resistor_SMD:R_0402", extra="(exclude_from_bom yes)"),
                   _sym("R4", "10k", fp="Resistor_SMD:R_0402", extra="(in_bom no)"))
    refs = {r["refs"][0] for r in bom_from_kicad_schematic(str(f))["rows"]}
    assert refs == {"R1"}


def test_bom_components_skips_power_and_hash_refs(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("#PWR01", "GND", lib="power:GND"))
    comps = _bom_components(str(f))
    assert [ref for ref, _ in comps] == ["R1"]


# -- cost roll-up --------------------------------------------------------------
def test_coerce_price_handles_strings_numbers_and_junk():
    assert _coerce_price("$0.10") == 0.10
    assert _coerce_price("1,250.00") == 1250.0
    assert _coerce_price(8) == 8.0
    assert _coerce_price(None) is None
    assert _coerce_price("call for pricing") is None


def test_line_extended_multiplies_or_none():
    assert line_extended("$1.25", 4) == 5.0
    assert line_extended(2.0, 3) == 6.0
    assert line_extended(None, 3) is None
    assert line_extended(2.0, 0) is None
    assert line_extended(2.0, "3") == 6.0
    assert line_extended(2.0, "3.0") == 6.0


def test_bom_cost_summary_totals_priced_and_counts_unpriced():
    rows = [
        {"qty": 4, "unit_price": "$1.25", "extended": 5.0},
        {"qty": 2, "unit_price": 8.0, "extended": 16.0},
        {"qty": 10, "unit_price": None},
    ]
    s = bom_cost_summary(rows)
    assert s["total_cost"] == 21.0
    assert s["priced_lines"] == 2 and s["unpriced_lines"] == 1
    assert s["line_count"] == 3 and s["currency"] == "USD"


def test_summary_recomputes_extended_from_unit_and_total_qty():
    assert bom_cost_summary([{"total_qty": 3, "unit_price": 2.0}])["total_cost"] == 6.0


def test_price_at_qty_picks_applicable_break():
    ladder = [{"qty": 1, "price": 0.10}, {"qty": 10, "price": 0.08}, {"qty": 100, "price": 0.05}]
    assert price_at_qty(ladder, 1) == 0.10
    assert price_at_qty(ladder, 5) == 0.10
    assert price_at_qty(ladder, 10) == 0.08
    assert price_at_qty(ladder, 250) == 0.05
    assert price_at_qty(ladder, "100") == 0.05
    assert price_at_qty([], 5) is None
    assert price_at_qty(ladder, 0) == 0.10


def test_price_at_qty_tolerates_unsorted_ladder():
    ladder = [{"qty": 100, "price": 0.05}, {"qty": 1, "price": 0.10}, {"qty": 10, "price": 0.08}]
    assert price_at_qty(ladder, 50) == 0.08


def test_price_rows_uses_volume_price_for_line_qty():
    rows = [{"mpn": "R-10K", "qty": 100}]
    lookup = lambda m: {"price_breaks": [{"qty": 1, "price": 0.10}, {"qty": 10, "price": 0.08},
                                         {"qty": 100, "price": 0.05}],
                        "unit_price": "$0.10", "stock": 9000}
    _price_rows(rows, lookup, "qty")
    assert rows[0]["unit_price"] == 0.05 and rows[0]["extended"] == 5.0 and rows[0]["price_breaks"]


def test_price_rows_falls_back_to_unit_price_without_ladder():
    rows = [{"mpn": "U1", "qty": 3}]
    _price_rows(rows, lambda m: {"unit_price": 2.0}, "qty")
    assert rows[0]["unit_price"] == 2.0 and rows[0]["extended"] == 6.0


def test_price_rows_threads_source_and_does_not_clobber():
    rows = [{"mpn": "U1", "qty": 1}, {"mpn": "U2", "qty": 1, "source": "Mouser"}]
    _price_rows(rows, lambda m: {"unit_price": 1.0, "source": "LCSC"}, "qty")
    assert rows[0]["source"] == "LCSC"
    assert rows[1]["source"] == "Mouser"  # a source already set stands


def test_bom_cost_by_source_splits_priced_lines_and_sums_to_total():
    rows = [
        {"source": "Mouser", "qty": 4, "unit_price": "$1.25"},
        {"source": "Mouser", "qty": 2, "unit_price": 8.0},
        {"source": "LCSC", "qty": 10, "unit_price": 0.10},
        {"source": "", "qty": 3},
    ]
    split = bom_cost_by_source(rows)["sources"]
    assert split["Mouser"] == {"total_cost": 21.0, "lines": 2}
    assert split["LCSC"] == {"total_cost": 1.0, "lines": 1}
    assert "Unsourced" not in split
    assert sum(s["total_cost"] for s in split.values()) == bom_cost_summary(rows)["total_cost"]


def test_bom_cost_at_qty_scales_and_reprices():
    ladder = [{"qty": 1, "price": 0.10}, {"qty": 10, "price": 0.08}, {"qty": 100, "price": 0.05}]
    rows = [{"qty": 2, "unit_price": 0.10, "price_breaks": ladder}]
    assert bom_cost_at_qty(rows, 1)["total_cost"] == 0.20
    assert bom_cost_at_qty(rows, 50)["total_cost"] == 5.0


def test_bom_cost_at_qty_bad_board_counts_and_no_mutation():
    rows = [{"qty": 2, "unit_price": 1.0}]
    before = dict(rows[0])
    for bad in (0, -3, None, "x"):
        r = bom_cost_at_qty(rows, bad)
        assert r["boards"] == 1 and r["total_cost"] == 2.0
    assert rows[0] == before


def test_row_cost_at_qty_and_board_count():
    ladder = [{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.05}]
    r = {"qty": 2, "unit_price": 0.10, "price_breaks": ladder}
    assert _row_cost_at_qty(r, 1) == (2, 0.10, 0.20)
    assert _row_cost_at_qty(r, 50) == (100, 0.05, 5.0)
    assert _row_cost_at_qty({"qty": 3}, 5) == (15, None, None)
    for bad in (0, -3, None, "x"):
        assert _board_count(bad) == 1
    assert _board_count("25") == 25


# -- enrich -> price adapter (M7c-3) -------------------------------------------
def test_enrichment_to_bom_lookup_maps_price_stock_manufacturer_and_source():
    result = EnrichmentResult()
    result.mpn = Sourced("R-10K", "mouser", "high")
    result.manufacturer = Sourced("Yageo", "mouser", "high")
    result.stock = Sourced(9000, "mouser", "high")
    result.price_breaks = [PriceBreak(qty=1, price=0.10), PriceBreak(qty=100, price=0.05)]
    row = enrichment_to_bom_lookup(result)
    assert row["price_breaks"] == [{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.05}]
    assert row["unit_price"] == 0.10
    assert row["stock"] == 9000
    assert row["manufacturer"] == "Yageo"
    assert row["source"] == "Mouser"


def test_enrichment_to_bom_lookup_none_for_empty_result():
    assert enrichment_to_bom_lookup(EnrichmentResult()) is None
    assert enrichment_to_bom_lookup(None) is None


def test_enrichment_to_bom_lookup_blank_source_for_non_distributor():
    result = EnrichmentResult()
    result.mpn = Sourced("X", "scrape", "medium")
    result.price_breaks = [PriceBreak(qty=1, price=1.0)]
    row = enrichment_to_bom_lookup(result)
    assert "source" not in row  # a scrape is not a distributor -> Unsourced downstream


# -- project orchestrator (M7c-4) ----------------------------------------------
def test_project_bom_builds_grouped_rows_offline(tmp_path):
    _write_sch(tmp_path / "root.kicad_sch",
               _sym("R1", "10k"), _sym("R2", "10k"),
               _sym("U1", "TPS2121", lib="Device:U", mpn="TPS2121RUXR", mfr="TI"))
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Demo")
    assert res["project"] == "Demo" and res["ran_at"]
    assert res["priced"] is False
    assert res["line_count"] == 2  # the two 10k resistors group to one line
    r10k = [ln for ln in res["lines"] if ln["value"] == "10k"][0]
    assert r10k["qty"] == 2
    assert res["summary"]["state"] == "built"
    assert res["summary"]["unpriced_lines"] == 2


def test_project_bom_prices_with_a_lookup(tmp_path):
    _write_sch(tmp_path / "root.kicad_sch",
               _sym("R1", "10k"),
               _sym("U1", "TPS2121", lib="Device:U", mpn="TPS2121RUXR", mfr="TI"))
    price = lambda m: {"unit_price": 1.25, "stock": 5000, "source": "Mouser"} if m == "TPS2121RUXR" else None
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Demo",
                      boards=1, price_lookup=price)
    assert res["priced"] is True
    u1 = [ln for ln in res["lines"] if ln["mpn"] == "TPS2121RUXR"][0]
    assert u1["unit_price"] == 1.25 and u1["extended"] == 1.25 and u1["source"] == "Mouser"
    assert res["summary"]["total_cost"] == 1.25 and res["summary"]["priced_lines"] == 1
    # the bare passive has no MPN -> stays unpriced, so one line is unpriced -> partial
    assert res["summary"]["state"] == "partial"
    assert res["by_source"]["sources"]["Mouser"]["total_cost"] == 1.25


def test_project_bom_honest_unpriced_when_lookup_misses(tmp_path):
    _write_sch(tmp_path / "root.kicad_sch",
               _sym("U1", "TPS2121", lib="Device:U", mpn="TPS2121RUXR", mfr="TI"))
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Demo",
                      price_lookup=lambda m: None)
    assert res["priced"] is True
    assert res["summary"]["state"] == "unpriced"
    assert res["summary"]["total_cost"] == 0.0 and res["summary"]["priced_lines"] == 0


def test_project_bom_empty_project_is_not_costed(tmp_path):
    _write_sch(tmp_path / "root.kicad_sch")  # no symbols
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Empty")
    assert res["line_count"] == 0
    assert res["summary"]["state"] == "empty"


def test_project_bom_costs_at_multiple_boards(tmp_path):
    _write_sch(tmp_path / "root.kicad_sch",
               _sym("U1", "STM32", lib="Device:U", mpn="STM32F407VGT6", mfr="ST"))
    ladder = {"price_breaks": [{"qty": 1, "price": 8.0}, {"qty": 100, "price": 5.0}]}
    price = lambda m: ladder if m == "STM32F407VGT6" else None
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Demo",
                      boards=100, price_lookup=price)
    assert res["cost_at_qty"]["boards"] == 100
    assert res["cost_at_qty"]["total_cost"] == 500.0  # 100 @ the 5.0 volume break


# -- consolidated across boards ------------------------------------------------
def test_consolidated_bom_sums_across_boards(tmp_path):
    parent = _write_sch(tmp_path / "p.kicad_sch",
                        _sym("U1", "STM32", lib="Device:U", mpn="STM32F407VGT6", mfr="ST"))
    card = _write_sch(tmp_path / "c.kicad_sch",
                      _sym("U1", "STM32", lib="Device:U", mpn="STM32F407VGT6", mfr="ST"))
    con = consolidated_bom({"Parent": [str(parent)], "Card": [str(card)]},
                           price_lookup=lambda m: {"unit_price": 8.0})
    r = con["rows"][0]
    assert r["total_qty"] == 2 and r["extended"] == 16.0
    assert con["cost"]["total_cost"] == 16.0
