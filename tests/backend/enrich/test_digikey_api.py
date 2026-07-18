import io
import json as _json
import urllib.request

import pytest

from stockroom.enrich.digikey_api import _parse_digikey_part, DigiKeyAdapter, _default_requester
from stockroom.enrich.errors import EnrichError

_PRODUCT = {
    "ManufacturerProductNumber": "SN74LVC1G08DBVR",
    "Manufacturer": {"Name": "Texas Instruments"},
    "Description": {"ProductDescription": "AND Gate IC 1 Channel SOT-23-5"},
    "DatasheetUrl": "https://www.ti.com/lit/gpn/sn74lvc1g08",
    "ProductStatus": {"Status": "Active"},
    "QuantityAvailable": 273814,
    "ManufacturerLeadWeeks": "16 Weeks",
    "ProductUrl": "https://www.digikey.com/en/products/detail/ti/SN74LVC1G08DBVR/385718",
    "Classifications": {"RohsStatus": "ROHS3 Compliant"},
    "ProductVariations": [
        {"DigiKeyProductNumber": "296-11601-2-ND",
         "StandardPricing": [
             {"BreakQuantity": 1, "UnitPrice": 0.12},
             {"BreakQuantity": 100, "UnitPrice": 0.077},
             {"BreakQuantity": 10, "UnitPrice": 0.099},
         ]},
    ],
}


def test_parse_maps_every_field():
    r = _parse_digikey_part(_PRODUCT)
    assert r.mpn.value == "SN74LVC1G08DBVR" and r.mpn.source == "digikey"
    assert r.manufacturer.value == "Texas Instruments"
    assert r.description.value == "AND Gate IC 1 Channel SOT-23-5"
    assert r.datasheet_url.value == "https://www.ti.com/lit/gpn/sn74lvc1g08"
    assert r.lifecycle.value == "Active"
    assert r.stock.value == 273814
    assert r.lead_time.value == "16 Weeks"
    assert r.dist_pns["digikey"] == "296-11601-2-ND"
    assert r.specs["RoHS"].value == "ROHS3 Compliant"
    # price ladder sorted ascending by qty
    assert [(b.qty, b.price) for b in r.price_breaks] == [(1, 0.12), (10, 0.099), (100, 0.077)]


def test_parse_tolerates_bare_strings_and_missing_fields():
    # v4 sometimes returns Manufacturer/Description/ProductStatus as plain strings, and a part
    # may omit fields entirely; the parser must never raise and must skip absent fields.
    r = _parse_digikey_part({"ManufacturerProductNumber": "X", "Manufacturer": "ACME",
                             "Description": "a part", "ProductStatus": ""})
    assert r.mpn.value == "X" and r.manufacturer.value == "ACME"
    assert r.description.value == "a part"
    assert r.lifecycle is None                # empty/absent status => honest None, never fabricated
    assert r.stock is None and r.price_breaks == []


def test_parse_maps_a_real_non_active_status():
    r = _parse_digikey_part({"ProductStatus": {"Status": "Obsolete"}})
    assert r.lifecycle.value == "Obsolete" and r.lifecycle.source == "digikey"


def test_parse_never_raises_on_garbage_shapes():
    for product in [{}, {"Manufacturer": 5}, {"ProductVariations": "x"},
                    {"ProductVariations": [{"StandardPricing": 7}]},
                    {"Classifications": "x"}]:
        assert _parse_digikey_part(product) is not None   # must not raise


_BODY = {"Products": [
    {"ManufacturerProductNumber": "SN74LVC1G08DBVR", "Manufacturer": {"Name": "TI"},
     "ProductStatus": {"Status": "Active"}},
    {"ManufacturerProductNumber": "OTHER-PART", "Manufacturer": {"Name": "TI"}},
]}


def test_lookup_picks_the_exact_mpn():
    a = DigiKeyAdapter("id", "secret", requester=lambda mpn: _BODY)
    r = a.lookup("sn74lvc1g08dbvr")   # case-insensitive exact match
    assert r.mpn.value == "SN74LVC1G08DBVR" and r.mpn.source == "digikey"
    assert r.mpn.confidence == "high"


def test_lookup_downgrades_confidence_without_exact_match():
    body = {"Products": [{"ManufacturerProductNumber": "CLOSE-BUT-NOT-IT",
                          "Manufacturer": {"Name": "TI"}}]}
    r = DigiKeyAdapter("id", "secret", requester=lambda mpn: body).lookup("WANTED")
    assert r.mpn.value == "CLOSE-BUT-NOT-IT" and r.mpn.confidence == "low"


def test_lookup_disabled_without_creds_makes_no_call():
    calls = []
    a = DigiKeyAdapter("", "", requester=lambda mpn: calls.append(mpn) or {})
    assert a.enabled is False
    assert a.lookup("X").mpn is None and calls == []


def test_lookup_never_raises_on_requester_failure_or_empty():
    from stockroom.enrich.errors import EnrichError

    def boom(mpn):
        raise EnrichError("dead")

    assert DigiKeyAdapter("id", "s", requester=boom).lookup("X").mpn is None
    assert DigiKeyAdapter("id", "s", requester=lambda m: {"Products": []}).lookup("X").mpn is None


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(token_body, search_body, calls):
    def _open(req, timeout=8):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        calls.append(url)
        payload = token_body if "oauth2/token" in url else search_body
        return _Resp(_json.dumps(payload).encode())
    return _open


def test_requester_fetches_token_once_then_searches(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        _fake_urlopen({"access_token": "TOK"},
                                      {"Products": [{"ManufacturerProductNumber": "X"}]}, calls))
    req = _default_requester("id", "secret")
    body = req("X")
    assert body["Products"][0]["ManufacturerProductNumber"] == "X"
    # second lookup reuses the cached token: no second oauth call
    req("Y")
    assert sum("oauth2/token" in u for u in calls) == 1
    assert sum("search/keyword" in u for u in calls) == 2


def test_requester_raises_enricherror_on_transport_failure(monkeypatch):
    def _boom(req, timeout=8):
        raise OSError("network down")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    with pytest.raises(EnrichError):
        _default_requester("id", "secret")("X")
