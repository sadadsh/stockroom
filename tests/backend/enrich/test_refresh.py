from stockroom.enrich.refresh import apply_procurement_refresh, refresh_via_adapters
from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced
from stockroom.model.part import PartRecord, Purchase


class _Adapter:
    def __init__(self, vendor, enabled, result):
        self.vendor, self.enabled, self._result = vendor, enabled, result

    def lookup(self, mpn):
        return self._result


def _priced(mpn):
    r = EnrichmentResult()
    r.mpn = Sourced(mpn, "x", "high")
    r.price_breaks = [PriceBreak(1, 0.5)]
    return r


def test_returns_one_pair_per_enabled_adapter_with_data():
    a = _Adapter("Mouser", True, _priced("X"))
    b = _Adapter("DigiKey", True, _priced("X"))
    out = refresh_via_adapters("X", [a, b])
    assert [v for v, _ in out] == ["Mouser", "DigiKey"]


def test_skips_disabled_and_empty_adapters():
    disabled = _Adapter("Mouser", False, _priced("X"))
    empty = _Adapter("DigiKey", True, EnrichmentResult())  # nothing found
    assert refresh_via_adapters("X", [disabled, empty]) == []


def test_no_mpn_returns_nothing():
    assert refresh_via_adapters("", [_Adapter("Mouser", True, _priced("X"))]) == []


def test_carries_a_lifecycle_only_result_through_the_adapters():
    # a result with ONLY lifecycle (no mpn/price/stock) must still be surfaced - it feeds the
    # record's Lifecycle spec. Before _has_data counted lifecycle this was silently dropped.
    r = EnrichmentResult()
    r.lifecycle = Sourced("Obsolete", "mouser", "high")
    out = refresh_via_adapters("X", [_Adapter("Mouser", True, r)])
    assert [v for v, _ in out] == ["Mouser"]
    assert out[0][1].lifecycle.value == "Obsolete"


def _result(stock=None, lifecycle=None, breaks=(), dk_pn=None):
    r = EnrichmentResult()
    if stock is not None:
        r.stock = Sourced(stock, "mouser", "high")
    if lifecycle is not None:
        r.lifecycle = Sourced(lifecycle, "mouser", "high")
    r.price_breaks = [PriceBreak(q, p) for q, p in breaks]
    if dk_pn:
        r.dist_pns["mouser"] = dk_pn
    return r


def test_updates_matching_vendor_purchase_in_place_and_stamps_fetched_at():
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X",
                     purchase=[Purchase(vendor="Mouser", url="u", stock=10, fetched_at="")])
    changed = apply_procurement_refresh(
        rec, [("Mouser", _result(stock=42, lifecycle="Active", breaks=[(1, 0.5)], dk_pn="595-X"))],
        "2026-07-18T00:00:00+00:00")
    assert changed is True
    p = rec.purchase[0]
    assert p.stock == 42 and p.part_number == "595-X" and p.fetched_at == "2026-07-18T00:00:00+00:00"
    assert p.price_breaks == [{"qty": 1, "price": 0.5}]
    assert rec.specs["Lifecycle"] == "Active"        # the dropped Sourced field, now written


def test_appends_a_new_vendor_and_keeps_untouched_ones():
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X",
                     purchase=[Purchase(vendor="LCSC", url="lcsc", stock=5, fetched_at="t0")])
    apply_procurement_refresh(rec, [("DigiKey", _result(stock=7))], "T")
    vendors = {p.vendor for p in rec.purchase}
    assert vendors == {"LCSC", "DigiKey"}
    lcsc = next(p for p in rec.purchase if p.vendor == "LCSC")
    assert lcsc.stock == 5 and lcsc.fetched_at == "t0"   # untouched vendor preserved


def test_no_change_returns_false():
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X", purchase=[])
    assert apply_procurement_refresh(rec, [("Mouser", EnrichmentResult())], "T") is False


def test_identical_data_under_a_later_clock_is_a_no_op_and_keeps_fetched_at():
    # fetched_at means "when the data last CHANGED" - re-fetching the same values with a fresh
    # (later) timestamp, as the live endpoint always does, must NOT re-stamp or report a change.
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X",
                     purchase=[Purchase(vendor="Mouser", stock=42, currency="USD",
                                        price_breaks=[{"qty": 1, "price": 0.5}],
                                        fetched_at="t0")])
    same = _result(stock=42, breaks=[(1, 0.5)])
    assert apply_procurement_refresh(rec, [("Mouser", same)], "t1-later") is False
    assert rec.purchase[0].fetched_at == "t0"          # clock advanced, data did not: no re-stamp


def test_a_result_with_only_identity_never_creates_an_empty_purchase():
    # an MPN-only (no price/stock/PN) answer must not spawn a bare vendor row.
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X", purchase=[])
    r = EnrichmentResult()
    r.mpn = Sourced("X", "mouser", "high")
    assert apply_procurement_refresh(rec, [("Mouser", r)], "T") is False
    assert rec.purchase == []


def test_lifecycle_only_result_writes_the_spec_without_a_purchase():
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X", purchase=[])
    changed = apply_procurement_refresh(rec, [("Mouser", _result(lifecycle="Active"))], "T")
    assert changed is True
    assert rec.specs["Lifecycle"] == "Active"
    assert rec.purchase == []                          # lifecycle alone is not purchase data


def test_first_vendor_with_a_lifecycle_wins_even_when_it_matches_the_stored_value():
    # leader (Mouser) reports "Active" == stored, so nothing changes; a later vendor's disagreeing
    # lifecycle must NOT override the leader. First-reports-wins, not first-differs-wins.
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X", purchase=[])
    rec.specs["Lifecycle"] = "Active"
    changed = apply_procurement_refresh(
        rec, [("Mouser", _result(lifecycle="Active")),
              ("DigiKey", _result(lifecycle="Obsolete"))], "T")
    assert changed is False
    assert rec.specs["Lifecycle"] == "Active"          # DigiKey never overrode the leader
