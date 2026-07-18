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
