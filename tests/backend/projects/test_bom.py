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
    annotate_build_pricing,
    bom_build_rollup,
    reprice_bom,
    bom_cost_at_qty,
    bom_cost_by_source,
    bom_cost_summary,
    bom_from_kicad_schematic,
    bom_from_project,
    consolidated_bom,
    enrichment_to_bom_lookup,
    is_basic_part,
    line_extended,
    line_moq,
    price_at_qty,
    price_line_at_build,
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


def test_normalize_symbol_collapses_kibom_aliases(tmp_path):
    # C == C_Small == Cap, R == R_Small == res, L == inductor, D == diode: one family token.
    assert kibom.normalize_symbol("C") == kibom.normalize_symbol("C_Small")
    assert kibom.normalize_symbol("Cap") == kibom.normalize_symbol("Capacitor")
    assert kibom.normalize_symbol("R") == kibom.normalize_symbol("R_Small") == kibom.normalize_symbol("res")
    assert kibom.normalize_symbol("L") == kibom.normalize_symbol("Inductor")
    assert kibom.normalize_symbol("D") == kibom.normalize_symbol("Diode")
    # but different families stay apart, and a blank degrades to '' (pre-#9 behavior)
    assert kibom.normalize_symbol("R") != kibom.normalize_symbol("L")
    assert kibom.normalize_symbol("") == ""
    # an unknown symbol passes through as its case-folded self
    assert kibom.normalize_symbol("TPS2121") == "tps2121"


def test_bom_splits_resistor_and_inductor_of_the_same_value_and_blank_footprint(tmp_path):
    # Roadmap #9: a Device:R "10k" and a Device:L "10k", both with blank footprint / MPN /
    # manufacturer, are DIFFERENT parts and must not merge into one qty-2 line.
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k", lib="Device:R"),
                   _sym("L1", "10k", lib="Device:L"))
    rows = bom_from_kicad_schematic(str(f))["rows"]
    assert len(rows) == 2
    assert {tuple(r["refs"]) for r in rows} == {("R1",), ("L1",)}


def test_bom_still_merges_same_footprint_symbol_name_variants(tmp_path):
    # Roadmap #9 must NOT over-split: two of the SAME part whose symbol names differ but are
    # not in the alias table (Device:R vs Device:R_US), same value AND footprint, blank
    # MPN/mfr, are one physical part and must stay one line. The symbol token only
    # discriminates when the footprint is blank (the footprint already discriminates otherwise).
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k", lib="Device:R", fp="Resistor_SMD:R_0402"),
                   _sym("R2", "10k", lib="Device:R_US", fp="Resistor_SMD:R_0402"))
    rows = bom_from_kicad_schematic(str(f))["rows"]
    assert len(rows) == 1 and rows[0]["qty"] == 2 and set(rows[0]["refs"]) == {"R1", "R2"}


def test_consolidated_bom_splits_resistor_and_inductor_across_boards(tmp_path):
    ra = _write_sch(tmp_path / "a.kicad_sch", _sym("R1", "10k", lib="Device:R"))
    lb = _write_sch(tmp_path / "b.kicad_sch", _sym("L1", "10k", lib="Device:L"))
    from stockroom.projects.bom import consolidated_bom
    out = consolidated_bom({"A": [str(ra)], "B": [str(lb)]})
    assert out["line_count"] == 2


def test_bom_row_carries_the_symbol_part_name(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch", _sym("U1", "STM32", lib="MCU:STM32F4"))
    rows = bom_from_kicad_schematic(str(f))["rows"]
    assert rows[0]["part_name"] == "STM32F4"


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
    assert [ref for ref, _lib, _props in comps] == ["R1"]
    assert comps[0][1] == "Device:R"  # lib_id is carried for library matching


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


# --- Build-quantity + tax/tariff line economics (owner ask 2026-07-15) ---

def test_line_moq_is_the_smallest_break_or_none():
    assert line_moq([{"qty": 10, "price": 0.08}, {"qty": 1, "price": 0.10}]) == 1
    assert line_moq([{"qty": 100, "price": 0.05}]) == 100
    assert line_moq([]) is None
    assert line_moq(None) is None


def test_price_line_at_build_rounds_up_to_moq_and_prices_at_final_qty():
    # 2 per board x 10 boards = 20 needed, but the part's MOQ (smallest break) is 100.
    ladder = [{"qty": 100, "price": 0.05}, {"qty": 500, "price": 0.03}]
    row = {"qty": 2, "price_breaks": ladder, "unit_price": 0.10}
    line = price_line_at_build(row, build_qty=10, tax_rate=8.25)
    assert line["moq"] == 100
    assert line["final_qty"] == 100                 # raised from 20 up to the MOQ
    assert line["final_unit_price"] == 0.05         # priced AT the 100-qty break
    assert line["final_extended"] == 5.0            # 0.05 * 100
    assert line["tax_tariff"] == round(5.0 * 8.25 / 100, 4)   # 0.4125
    assert line["line_total"] == round(5.0 + 0.4125, 4)      # 5.4125
    assert row == {"qty": 2, "price_breaks": ladder, "unit_price": 0.10}  # never mutated


def test_price_line_at_build_uses_need_when_it_exceeds_moq():
    ladder = [{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.05}]
    # 30 per board x 5 boards = 150 needed, above the MOQ of 1
    line = price_line_at_build({"qty": 30, "price_breaks": ladder}, build_qty=5, tax_rate=0)
    assert line["final_qty"] == 150
    assert line["final_unit_price"] == 0.05         # the 100-qty volume break applies
    assert line["final_extended"] == 7.5
    assert line["tax_tariff"] == 0.0                # a 0 rate adds nothing
    assert line["line_total"] == 7.5


def test_price_line_at_build_unpriced_line_keeps_qty_but_no_money():
    line = price_line_at_build({"qty": 3}, build_qty=4, tax_rate=8.0)
    assert line["final_qty"] == 12 and line["moq"] is None
    assert line["final_unit_price"] is None
    assert line["final_extended"] is None
    assert line["tax_tariff"] is None and line["line_total"] is None


def test_bom_build_rollup_subtotal_tax_and_grand_total():
    rows = [
        {"qty": 2, "price_breaks": [{"qty": 100, "price": 0.05}]},   # -> 100 @ 0.05 = 5.00
        {"qty": 1, "price_breaks": [{"qty": 1, "price": 2.00}]},     # -> 10  @ 2.00 = 20.00
        {"qty": 5, "unit_price": None},                              # unpriced
    ]
    roll = bom_build_rollup(rows, build_qty=10, tax_rate=10)
    assert roll["build_qty"] == 10 and roll["tax_rate"] == 10.0
    assert roll["subtotal"] == 25.0
    assert roll["tax_total"] == 2.5
    assert roll["grand_total"] == 27.5
    assert roll["priced_lines"] == 2 and roll["unpriced_lines"] == 1


def test_annotate_build_pricing_writes_the_columns_onto_each_row():
    rows = [{"qty": 2, "price_breaks": [{"qty": 100, "price": 0.05}]}]
    roll = annotate_build_pricing(rows, boards=10, tax_rate=8.25)
    r = rows[0]
    assert r["moq"] == 100 and r["final_qty"] == 100
    assert r["final_unit_price"] == 0.05 and r["final_extended"] == 5.0
    assert r["line_total"] == round(5.0 + 5.0 * 8.25 / 100, 4)
    assert roll["grand_total"] == round(5.0 + 5.0 * 8.25 / 100, 2)


def test_reprice_bom_recomputes_over_cached_lines_without_a_rebuild():
    cached = {
        "project": "P", "priced": True, "boards": 1, "line_count": 2, "component_count": 3,
        "lines": [
            {"mpn": "A", "qty": 2, "price_breaks": [{"qty": 100, "price": 0.05}]},
            {"mpn": "B", "qty": 1, "price_breaks": [{"qty": 1, "price": 2.00}]},
        ],
        "summary": {"total_cost": 2.1}, "by_source": None, "cost_at_qty": None,
    }
    out = reprice_bom(cached, boards=10, tax_rate=10)
    assert out["boards"] == 10 and out["tax_rate"] == 10.0
    # per-line columns reflect the new build quantity
    assert out["lines"][0]["final_qty"] == 100 and out["lines"][0]["final_extended"] == 5.0
    assert out["lines"][1]["final_qty"] == 10 and out["lines"][1]["final_extended"] == 20.0
    # the roll-up totals the re-costed lines + tax
    assert out["build"]["subtotal"] == 25.0 and out["build"]["grand_total"] == 27.5
    # the source result is not mutated (a new dict + copied rows)
    assert cached["boards"] == 1 and "final_qty" not in cached["lines"][0]


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


def test_enrichment_to_bom_lookup_carries_procurement_fields():  # M7d
    result = EnrichmentResult()
    result.mpn = Sourced("TPS62130RGTR", "mouser", "high")
    result.stock = Sourced(4200, "mouser", "high")
    result.lifecycle = Sourced("Active", "mouser", "high")
    result.lead_time = Sourced("16 Weeks", "mouser", "high")
    result.product_url = Sourced("http://x/exact", "mouser", "high")
    result.dist_pns = {"mouser": "595-TPS62130RGTR", "lcsc": "C123"}
    row = enrichment_to_bom_lookup(result)
    assert row["lifecycle"] == "Active"
    assert row["lead_time"] == "16 Weeks"
    assert row["url"] == "http://x/exact"
    assert row["mouser_pn"] == "595-TPS62130RGTR"
    assert row["lcsc_pn"] == "C123"


def test_enrichment_to_bom_lookup_omits_absent_procurement_fields():  # M7d: honest, no blanks
    result = EnrichmentResult()
    result.mpn = Sourced("X", "mouser", "high")
    result.price_breaks = [PriceBreak(qty=1, price=1.0)]
    row = enrichment_to_bom_lookup(result)
    for absent in ("lifecycle", "lead_time", "url", "mouser_pn", "lcsc_pn", "digikey_pn"):
        assert absent not in row


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
# -- review-fix regressions ----------------------------------------------------
def test_do_not_fit_matches_multiword_config_spellings():
    # A multi-word DNF phrase in Config must match as a whole (a naive [ ,]+ split would
    # shred "do not fit" into words that are not in the DNF set) - KiBoM isFitted parity.
    for phrase in ("do not fit", "do not place", "do not load", "not fitted",
                   "not loaded", "not placed", "no stuff"):
        assert kibom.is_do_not_fit({"Config": phrase}) is True, phrase
    assert kibom.is_do_not_fit({"Config": "variantA, do not fit"}) is True
    assert kibom.is_do_not_fit({"Config": "DNF"}) is True
    assert kibom.is_do_not_fit({"Config": "populate"}) is False
    assert kibom.is_do_not_fit({"Value": "10k"}) is False


def test_bom_excludes_a_multiword_config_dnf_part(tmp_path):
    f = _write_sch(tmp_path / "s.kicad_sch",
                   _sym("R1", "10k"),
                   _sym("R2", "10k", fp="Resistor_SMD:R_0402",
                        extra='(property "Config" "do not fit" (at 0 0 0))'))
    refs = {r["refs"][0] for r in bom_from_kicad_schematic(str(f))["rows"]}
    assert refs == {"R1"}


def test_row_cost_at_qty_coerces_string_ladder_prices():
    # A string ladder price must cost like a float one, not raise round(str * qty).
    float_ladder = [{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.05}]
    str_ladder = [{"qty": 1, "price": "$0.10"}, {"qty": 100, "price": "$0.05"}]
    rf = {"qty": 2, "price_breaks": float_ladder}
    rs = {"qty": 2, "price_breaks": str_ladder}
    assert _row_cost_at_qty(rs, 50) == _row_cost_at_qty(rf, 50) == (100, 0.05, 5.0)
    assert bom_cost_at_qty([rs], 50)["total_cost"] == 5.0
    assert bom_cost_by_source([{**rs, "source": "Mouser"}], 50)["sources"]["Mouser"]["total_cost"] == 5.0


def test_project_bom_summary_agrees_with_by_source_and_cost_at_qty_for_multi_board(tmp_path):
    # For boards>1 the headline summary must be projected at the run quantity so it equals
    # the per-source split and cost_at_qty (never a per-board figure beside a run figure).
    _write_sch(tmp_path / "root.kicad_sch",
               _sym("U1", "STM32", lib="Device:U", mpn="STM32F407VGT6", mfr="ST"))
    ladder = {"price_breaks": [{"qty": 1, "price": 8.0}, {"qty": 100, "price": 5.0}], "source": "Mouser"}
    res = project_bom(tmp_path, "root.kicad_pro", ["root.kicad_sch"], name="Demo",
                      boards=100, price_lookup=lambda m: ladder if m == "STM32F407VGT6" else None)
    total = res["summary"]["total_cost"]
    assert total == 500.0
    assert total == res["cost_at_qty"]["total_cost"]
    assert total == sum(s["total_cost"] for s in res["by_source"]["sources"].values())


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


# -- library combining (schematic + library) -----------------------------------

from stockroom.model.part import Datasheet, LibRef, PartRecord, Purchase  # noqa: E402
from stockroom.projects.bom import (  # noqa: E402
    combined_price_lookup,
    library_enrich,
    library_match_index,
    library_price_index,
    library_spec_index,
    package_from_footprint,
    rohs_from_specs,
)
from stockroom.projects.procurement import annotate_procurement_fields  # noqa: E402


def _lib_resistor():
    return PartRecord(
        id="r10k", display_name="10k 0402", category="Resistors",
        description="10k 1% 0402", mpn="RC0402FR-0710KL", manufacturer="Yageo",
        symbol=LibRef(lib="SR-Resistors", name="R_10k"),
        footprint=LibRef(lib="SR-Resistors", name="R_0402"),
        datasheet=Datasheet(file="r.pdf", source_url="https://yageo.com/r.pdf"),
        purchase=[Purchase(vendor="Mouser", url="https://mouser.com/r10k",
                           price_breaks=[{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.02}],
                           stock=50000)],
    )


def test_library_enrich_fills_blank_identity_from_the_matched_part():
    # a schematic component carrying ONLY a lib_id (no MPN) gets its MPN + manufacturer from the
    # library, matched by symbol name.
    index = library_match_index([_lib_resistor()])
    comps = [("R1", "SR-Resistors:R_10k", {"Reference": "R1", "Value": "10k"})]
    _ref, _lib, props = library_enrich(comps, index)[0]
    assert props["MPN"] == "RC0402FR-0710KL" and props["Manufacturer"] == "Yageo"


def test_library_enrich_never_overwrites_a_schematic_value():
    index = library_match_index([_lib_resistor()])
    comps = [("R1", "SR-Resistors:R_10k",
              {"Reference": "R1", "Value": "10k", "MPN": "USER-CHOSEN"})]
    _ref, _lib, props = library_enrich(comps, index)[0]
    assert props["MPN"] == "USER-CHOSEN"  # a deliberate schematic override stands


def test_library_enrich_passes_an_unmatched_component_through(tmp_path):
    index = library_match_index([_lib_resistor()])
    comps = [("R9", "Device:R", {"Reference": "R9", "Value": "47k"})]  # no library match
    _ref, _lib, props = library_enrich(comps, index)[0]
    assert "MPN" not in props  # nothing fabricated


def test_library_price_index_maps_mpn_to_stored_price():
    idx = library_price_index([_lib_resistor()])
    entry = idx["RC0402FR-0710KL"]
    assert entry["source"] == "library" and entry["unit_price"] == 0.10 and entry["stock"] == 50000
    assert entry["price_breaks"] == [{"qty": 1, "price": 0.10}, {"qty": 100, "price": 0.02}]


def test_library_price_index_skips_a_part_with_no_price_or_stock():
    bare = PartRecord(id="x", display_name="x", category="Resistors", mpn="NOPRICE")
    assert "NOPRICE" not in library_price_index([bare])


def test_combined_price_lookup_prefers_library_then_enrich():
    def enrich(mpn):
        return {"unit_price": 9.99, "source": "mouser"} if mpn == "OTHER" else None

    lookup = combined_price_lookup([_lib_resistor()], enrich)
    assert lookup("RC0402FR-0710KL")["source"] == "library"  # library wins
    assert lookup("OTHER")["source"] == "mouser"             # falls back to the enrich layer
    assert lookup("UNKNOWN") is None                         # neither can price it


def test_project_bom_combines_library_identity_and_price(tmp_path):
    # end to end: two schematic resistors carrying ONLY a lib_id become one complete, quantity-2,
    # library-priced line, with the manufacturer + price pulled from the library.
    _write_sch(tmp_path / "b.kicad_sch",
               _sym("R1", "10k", lib="SR-Resistors:R_10k"),
               _sym("R2", "10k", lib="SR-Resistors:R_10k"))
    result = project_bom(str(tmp_path), None, ["b.kicad_sch"], name="B", boards=1,
                         library_parts=[_lib_resistor()])
    assert result["priced"] is True
    line = next(r for r in result["lines"] if r.get("mpn") == "RC0402FR-0710KL")
    assert line["qty"] == 2 and line["manufacturer"] == "Yageo"
    assert line["source"] == "library" and line["unit_price"] == 0.10
    assert result["by_source"]["sources"].get("library") is not None


# -- wide-BOM fields: package / rohs / category + folded procurement (M7 wide table) ---


def test_package_from_footprint_reads_passive_eia_and_ic_family():
    assert package_from_footprint("Resistor_SMD:R_0603_1608Metric") == "0603"
    assert package_from_footprint("Capacitor_SMD:C_0402_1005Metric") == "0402"
    assert package_from_footprint("Resistor_SMD:R_0402") == "0402"  # no metric suffix
    assert package_from_footprint("L_1210_3225Metric") == "1210"  # bare name, no lib prefix
    assert package_from_footprint("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm") == "SOIC-8"
    assert package_from_footprint("Package_TO_SOT_SMD:SOT-23") == "SOT-23"
    assert package_from_footprint("Package_QFP:TQFP-100_14x14mm_P0.5mm") == "TQFP-100"
    # a single-letter device-class prefix (diodes) hides the package in the next token
    assert package_from_footprint("Diode_SMD:D_SOD-123") == "SOD-123"
    assert package_from_footprint("Diode_SMD:D_SOD-323") == "SOD-323"
    assert package_from_footprint("Diode_SMD:D_SMA") == "SMA"
    assert package_from_footprint("Diode_SMD:D_MELF") == "MELF"
    assert package_from_footprint("MountingHole:MountingHole_3.2mm") == ""  # not a package
    assert package_from_footprint("Device:Crystal") == ""  # a bare word is not a package
    assert package_from_footprint("") == ""


def test_rohs_from_specs_normalizes_compliance():
    assert rohs_from_specs({"RoHS": "RoHS3 Compliant"}) == "Yes"
    assert rohs_from_specs({"RoHS Status": "Lead Free"}) == "Yes"
    assert rohs_from_specs({"EU RoHS": "Compliant"}) == "Yes"
    assert rohs_from_specs({"RoHS": "Non-Compliant"}) == "No"
    assert rohs_from_specs({"RoHS": "Not Compliant"}) == "No"
    # a compliant value that merely opens with "non" is not non-compliance
    assert rohs_from_specs({"RoHS": "Nonhalogenated, RoHS Compliant"}) == "Yes"
    # an unknown / not-specified status is unknown, never a guessed "No"
    assert rohs_from_specs({"RoHS Status": "Not Applicable"}) == ""
    assert rohs_from_specs({"RoHS Status": "None"}) == ""
    assert rohs_from_specs({"RoHS Status": "Not Reviewed"}) == ""
    assert rohs_from_specs({"RoHS Status": "Unknown"}) == ""
    assert rohs_from_specs({"Package": "0402"}) == ""  # no RoHS key -> blank
    assert rohs_from_specs({"RoHS": ""}) == ""  # blank value -> blank
    assert rohs_from_specs({}) == ""
    assert rohs_from_specs(None) == ""


def test_enrichment_to_bom_lookup_carries_package_rohs_and_category():
    result = EnrichmentResult()
    result.category = "Resistors"
    result.mpn = Sourced("ERJ-P03F1101V", "mouser", "high")
    result.package = Sourced("0603", "mouser", "high")
    result.price_breaks = [PriceBreak(qty=1, price=0.10)]
    result.specs = {"RoHS": Sourced("RoHS Compliant", "mouser", "high")}
    row = enrichment_to_bom_lookup(result)
    assert row["package"] == "0603"
    assert row["rohs"] == "Yes"
    assert row["category"] == "Resistors"


def test_price_rows_overrides_footprint_package_and_fills_rohs():
    # the enrich spec-table package (authoritative) wins over the footprint-derived baseline;
    # rohs/category fill only when the row does not already carry them.
    rows = [{"mpn": "X", "qty": 1, "package": "SOIC-8", "rohs": "", "category": ""}]
    _price_rows(rows, lambda m: {"unit_price": 1.0, "package": "SO-8", "rohs": "Yes",
                                 "category": "ICs"}, "qty")
    assert rows[0]["package"] == "SO-8"  # enrich overrides the baseline
    assert rows[0]["rohs"] == "Yes"
    assert rows[0]["category"] == "ICs"


def test_price_rows_keeps_footprint_package_when_enrich_has_none():
    rows = [{"mpn": "X", "qty": 1, "package": "0603", "rohs": "Yes"}]
    _price_rows(rows, lambda m: {"unit_price": 1.0, "rohs": "No"}, "qty")
    assert rows[0]["package"] == "0603"  # no enrich package -> baseline stands
    assert rows[0]["rohs"] == "Yes"  # a rohs already set is not clobbered


def test_bom_rows_carry_package_from_footprint(tmp_path):
    _write_sch(tmp_path / "b.kicad_sch",
               _sym("R1", "10k", fp="Resistor_SMD:R_0603_1608Metric"))
    rows = bom_from_project([str(tmp_path / "b.kicad_sch")])["rows"]
    assert rows[0]["package"] == "0603"
    assert rows[0]["rohs"] == "" and rows[0]["category"] == ""


def test_library_price_index_carries_package_rohs_category():
    p = PartRecord(id="r", display_name="10k", category="Resistors", mpn="RC0402FR-0710KL",
                   specs={"Package": "0402", "RoHS": "RoHS Compliant"},
                   purchase=[Purchase(vendor="Mouser", url="u",
                                      price_breaks=[{"qty": 1, "price": 0.1}], stock=100)])
    entry = library_price_index([p])["RC0402FR-0710KL"]
    assert entry["package"] == "0402" and entry["rohs"] == "Yes"
    assert entry["category"] == "Resistors"


def test_library_spec_index_maps_mpn_to_package_rohs_category():
    p = PartRecord(id="u", display_name="MCU", category="ICs", mpn="STM32",
                   specs={"Package": "LQFP-48", "RoHS Status": "Compliant"})
    idx = library_spec_index([p])
    assert idx["STM32"] == {"package": "LQFP-48", "rohs": "Yes", "category": "ICs"}
    # a part with no mpn is not indexed
    assert library_spec_index([PartRecord(id="x", display_name="x", category="C")]) == {}


def test_annotate_procurement_fields_mutates_rows_and_returns_rollups():
    rows = [{"mpn": "A", "qty": 2, "unit_price": 1.0, "extended": 2.0, "stock": 0,
             "lead_time": "10 Weeks"}]
    roll = annotate_procurement_fields(rows, boards=1)
    assert rows[0]["stock_risk"]["kind"] == "err"
    assert rows[0]["orderable"] is False
    assert roll["risks"]["no_stock"] == 1
    assert roll["lead"]["max_weeks"] == 10


def test_project_bom_folds_procurement_and_library_specs(tmp_path):
    # a library part carries specs (Package/RoHS) that no schematic prop or footprint gives; the
    # built BOM line surfaces them, plus the folded per-line stock risk + orderable + the roll-ups.
    _write_sch(tmp_path / "b.kicad_sch",
               _sym("U1", "STM32F103", lib="MCU:STM32", mpn="STM32F103", mfr="ST"))
    part = PartRecord(id="u", display_name="MCU", category="ICs", mpn="STM32F103",
                      manufacturer="ST",
                      specs={"Package": "LQFP-48", "RoHS": "Compliant"},
                      purchase=[Purchase(vendor="Mouser", url="https://mouser.com/u",
                                         price_breaks=[{"qty": 1, "price": 2.0}], stock=0)])
    result = project_bom(str(tmp_path), None, ["b.kicad_sch"], name="B", boards=1,
                         library_parts=[part])
    line = next(r for r in result["lines"] if r.get("mpn") == "STM32F103")
    assert line["package"] == "LQFP-48"
    assert line["rohs"] == "Yes"
    assert line["category"] == "ICs"
    # folded procurement: 0 stock -> stock risk err, not orderable
    assert line["stock_risk"]["kind"] == "err"
    assert line["orderable"] is False
    # top-level risk/lead roll-ups fold onto the result
    assert result["risks"]["no_stock"] == 1
    assert result["lead"]["any"] is False


def test_reprice_bom_refolds_procurement_risk():
    cached = {
        "project": "P", "priced": True, "boards": 1, "line_count": 1, "component_count": 1,
        "lines": [{"mpn": "A", "qty": 40, "unit_price": 0.05, "stock": 100,
                   "price_breaks": [{"qty": 1, "price": 0.05}]}],
        "summary": {}, "by_source": None, "cost_at_qty": None,
    }
    # at 1 board (qty 40, stock 100) it is covered; at 4 boards (qty 160 > 100) it is short.
    out1 = reprice_bom(cached, boards=1, tax_rate=0)
    assert out1["lines"][0]["stock_risk"]["kind"] is None
    assert out1["risks"]["insufficient_stock"] == 0
    out4 = reprice_bom(cached, boards=4, tax_rate=0)
    assert out4["lines"][0]["stock_risk"]["kind"] == "warn"
    assert out4["risks"]["insufficient_stock"] == 1
