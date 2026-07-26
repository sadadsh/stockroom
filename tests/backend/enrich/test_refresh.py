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
    # leader (Mouser) reports "Active" == stored; a later vendor's disagreeing lifecycle must
    # NOT override the leader. First-reports-wins, not first-differs-wins.
    #
    # DELIBERATELY RE-BASELINED for Batch 3: this used to assert `changed is False`, because
    # DigiKey's "Obsolete" was DISCARDED and so nothing happened at all. A distributor calling a
    # part obsolete while another calls it active is exactly the vendor disagreement the owner
    # asked to stop losing, so it is now KEPT as an alternate - which is a real change to the
    # record, hence changed is True. The no-empty-commit invariant that assertion was protecting
    # is proven by the second call below instead: once recorded, re-checking is a true no-op.
    rec = PartRecord(id="p", display_name="P", category="ICs", mpn="X", purchase=[])
    rec.specs["Lifecycle"] = "Active"
    per_vendor = [("Mouser", _result(lifecycle="Active")),
                  ("DigiKey", _result(lifecycle="Obsolete"))]
    assert apply_procurement_refresh(rec, per_vendor, "T") is True
    assert rec.specs["Lifecycle"] == "Active"          # DigiKey never overrode the leader
    # (the shared _result fixture stamps every value "mouser", so only the VALUES vary here)
    assert [a.value for a in rec.alternates["Lifecycle"]] == ["Active", "Obsolete"]
    # the same re-check again learns nothing new, so it must not churn a commit
    assert apply_procurement_refresh(rec, per_vendor, "T") is False


# -- What a rescan stops throwing away (Batch 3, punch 2). Measured before this: the refresh
# lane kept price_breaks / stock / part_number / currency and the Lifecycle spec, and DISCARDED
# every parametric spec, HTS code, lead time, origin, tariff, description, datasheet and product
# URL on every single re-check - even when the record had none of them.


def _rich(vendor="mouser"):
    r = EnrichmentResult()
    r.mpn = Sourced("X", vendor, "high")
    r.price_breaks = [PriceBreak(1, 0.5)]
    r.lifecycle = Sourced("Active", vendor, "high")
    r.lead_time = Sourced("16 Weeks", vendor, "high")
    r.country_of_origin = Sourced("Japan", vendor, "high")
    r.tariff_rate = Sourced(0.0, vendor, "high")
    r.description = Sourced("3A Buck Converter", vendor, "high")
    r.specs["HTS Code (US)"] = Sourced("8542.39.0001", vendor, "high")
    return r


def _record(**kw):
    return PartRecord(id="p1", display_name="P", category="ICs", **kw)


def test_a_refresh_fills_the_procurement_fields_a_record_lacks():
    rec = _record()
    assert apply_procurement_refresh(rec, [("Mouser", _rich())], "NOW") is True
    assert rec.specs["Lead Time"] == "16 Weeks"
    assert rec.specs["Country of Origin"] == "Japan"
    assert rec.specs["US Tariff %"] == 0.0  # 0.0 is a confirmed no-tariff, not a gap
    assert rec.specs["HTS Code (US)"] == "8542.39.0001"
    assert rec.enrichment["Lead Time"].source == "mouser"


def test_a_refresh_never_overwrites_a_spec_already_on_the_record():
    """A rescan is a re-check of VOLATILE data. A parametric spec on the record may have been
    corrected by hand, so filling a gap is right and clobbering is not."""
    rec = _record(specs={"HTS Code (US)": "corrected-by-hand"})
    apply_procurement_refresh(rec, [("Mouser", _rich())], "NOW")
    assert rec.specs["HTS Code (US)"] == "corrected-by-hand"


def test_a_refresh_keeps_a_second_vendors_description_instead_of_dropping_it():
    """punch 9 for a part that is ALREADY in the library: the rescan is where a second
    distributor's description shows up, and it was thrown away with no record at all."""
    rec = _record(description="3A buck, WSON-8")
    changed = apply_procurement_refresh(
        rec, [("DigiKey", _rich("digikey"))], "NOW")
    assert changed is True
    assert rec.description == "3A buck, WSON-8"  # the stored value still stands
    assert [(a.value, a.source) for a in rec.alternates["description"]] == [
        ("3A buck, WSON-8", ""), ("3A Buck Converter", "digikey"),
    ]


def test_a_refresh_that_agrees_with_the_record_records_no_alternate_and_no_change():
    rec = _record(description="3A Buck Converter")
    changed = apply_procurement_refresh(rec, [("Mouser", _rich())], "NOW")
    assert rec.alternates.get("description") is None
    # price/stock still changed, so `changed` is True overall; the point is the description
    # produced no phantom disagreement
    assert changed is True


def test_a_refresh_fills_a_missing_description_rather_than_only_recording_it():
    rec = _record()
    apply_procurement_refresh(rec, [("Mouser", _rich())], "NOW")
    assert rec.description == "3A Buck Converter"
    assert rec.alternates.get("description") is None
