import json
from pathlib import Path

from stockroom.enrich.mouser import MouserAdapter

FIX = Path(__file__).parent / "fixtures"


def test_adapter_is_off_by_default_with_no_key():
    a = MouserAdapter()
    assert a.enabled is False
    r = a.lookup("TPS62130RGTR")
    assert r.filled_fields() == set()  # no network, empty result


def test_adapter_enabled_only_with_a_key():
    assert MouserAdapter(api_key="k").enabled is True


def test_lookup_prefers_the_exact_mpn_row_not_parts_zero():
    body = json.loads((FIX / "mouser_partnumber.json").read_text())

    def requester(mpn):
        return body  # the saved API response; no network

    a = MouserAdapter(api_key="k", requester=requester)
    r = a.lookup("TPS62130RGTR")
    # parts[0] is the "-NEAR" near-match; the exact MPN row must win
    assert r.mpn.value == "TPS62130RGTR"
    assert r.manufacturer.value == "Texas Instruments"
    assert r.mpn.confidence == "high"
    assert r.datasheet_url.value == "http://x/exact.pdf"
    assert r.stock.value == 4200
    assert [b.qty for b in r.price_breaks] == [1, 100]
    assert r.price_breaks[0].price == 1.23


def test_lookup_returns_empty_on_no_parts():
    a = MouserAdapter(api_key="k", requester=lambda mpn: {"SearchResults": {"Parts": []}})
    assert a.lookup("NOPE").filled_fields() == set()
