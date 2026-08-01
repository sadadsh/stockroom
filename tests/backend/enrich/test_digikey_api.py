import io
import json as _json
import urllib.error
import urllib.request

import pytest

from stockroom.enrich.digikey_api import (
    DigiKeyAdapter,
    DigiKeyClient,
    _default_requester,
    _parse_digikey_part,
    digikey_catalog_from_payload,
    parse_digikey_payload,
    pricing_options_from_payload,
)
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


def test_parse_captures_parameters_photo_category_and_classifications():
    # "use literally everything the token gives us": the 14 electrical parametrics, the image,
    # the leaf category, and the full compliance block (not just RoHS) all flow into specs.
    product = dict(_PRODUCT)
    product["PhotoUrl"] = "https://dk/photo.jpg"
    product["Category"] = {"Name": "Circuit Protection"}
    product["Series"] = {"Name": "-"}
    product["Parameters"] = [
        {"ParameterText": "Type", "ValueText": "Steering (Rail to Rail)"},
        {"ParameterText": "Unidirectional Channels", "ValueText": "6"},
        {"ParameterText": "Capacitance @ Frequency", "ValueText": "-"},  # placeholder -> skipped
    ]
    product["Classifications"] = {
        "RohsStatus": "ROHS3 Compliant", "ReachStatus": "REACH Unaffected",
        "MoistureSensitivityLevel": "1 (Unlimited)", "ExportControlClassNumber": "EAR99",
        "HtsusCode": "8541.10.0080",
    }
    r = _parse_digikey_part(product)
    assert r.specs["Type"].value == "Steering (Rail to Rail)"
    assert r.specs["Unidirectional Channels"].value == "6"
    assert "Capacitance @ Frequency" not in r.specs  # the "-" placeholder is not captured
    assert r.specs["Image"].value == "https://dk/photo.jpg"
    assert r.specs["Product Category"].value == "Circuit Protection"
    assert "Series" not in r.specs  # a "-" series is skipped
    assert r.specs["RoHS"].value == "ROHS3 Compliant"  # still present (existing behavior)
    assert r.specs["REACH"].value == "REACH Unaffected"
    assert r.specs["ECCN"].value == "EAR99"
    assert r.specs["Moisture Sensitivity Level"].value == "1 (Unlimited)"
    assert r.specs["HTS Code (US)"].value == "8541.10.0080"


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


def test_quantity_pricing_is_normalized_and_sorted_without_losing_raw_variants():
    payload = {
        "ProductVariations": [
            {
                "DigiKeyProductNumber": "CUT-ND",
                "PackageType": {"Name": "Cut Tape"},
                "Pricing": [
                    {"RequestedQuantity": 100, "UnitPrice": 0.09, "Currency": "USD"},
                    {"RequestedQuantity": 100, "UnitPrice": 0.09, "Currency": "USD"},
                ],
            },
            {
                "DigiKeyProductNumber": "REEL-ND",
                "Packaging": "Tape & Reel",
                "Quantity": 100,
                "UnitPrice": "0.07",
                "Currency": "USD",
            },
        ]
    }

    assert pricing_options_from_payload(payload) == [
        {
            "product_number": "REEL-ND",
            "packaging": "Tape & Reel",
            "quantity": 100,
            "unit_price": 0.07,
            "currency": "USD",
        },
        {
            "product_number": "CUT-ND",
            "packaging": "Cut Tape",
            "quantity": 100,
            "unit_price": 0.09,
            "currency": "USD",
        },
    ]


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
    def boom(mpn):
        raise EnrichError("dead")

    assert DigiKeyAdapter("id", "s", requester=boom).lookup("X").mpn is None
    assert DigiKeyAdapter("id", "s", requester=lambda m: {"Products": []}).lookup("X").mpn is None


# --- Phase-1b-2b: last_status circuit-breaker signal ------------------------------


def test_last_status_is_rate_limited_on_a_429():
    def boom(mpn):
        raise EnrichError("throttled", status_code=429)

    a = DigiKeyAdapter("id", "secret", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "rate_limited"
    assert r.mpn is None  # a failed lookup still returns an empty result


def test_last_status_is_auth_error_on_a_401():
    def boom(mpn):
        raise EnrichError("unauthorized", status_code=401)

    a = DigiKeyAdapter("id", "secret", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "auth_error"
    assert r.mpn is None


def test_last_status_is_auth_error_on_a_403():
    def boom(mpn):
        raise EnrichError("forbidden", status_code=403)

    a = DigiKeyAdapter("id", "secret", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "auth_error"
    assert r.mpn is None


def test_last_status_is_error_on_a_generic_failure():
    def boom(mpn):
        raise EnrichError("dead")  # no status_code: not HTTP-coded

    a = DigiKeyAdapter("id", "secret", requester=boom)
    r = a.lookup("X")
    assert a.last_status == "error"
    assert r.mpn is None


def test_last_status_is_ok_on_a_matching_part():
    a = DigiKeyAdapter("id", "secret", requester=lambda mpn: _BODY)
    a.lookup("SN74LVC1G08DBVR")
    assert a.last_status == "ok"


def test_last_status_is_not_found_on_no_products():
    a = DigiKeyAdapter("id", "secret", requester=lambda mpn: {"Products": []})
    a.lookup("NOPE")
    assert a.last_status == "not_found"


def test_last_status_defaults_to_empty_before_any_lookup():
    assert DigiKeyAdapter("id", "secret").last_status == ""


# ------------------------------------------------------------------------ fetch_payload
#
# Regression pin for cold-eyes finding 1 (2026-07-27), the DigiKey twin of the Mouser test. See
# tests/backend/enrich/test_mouser.py's block comment for the full story.

def test_fetch_payload_is_NOT_FOUND_and_returns_NONE_on_empty_results():
    a = DigiKeyAdapter("id", "secret", requester=lambda mpn: {"Products": []})
    got = a.fetch_payload("ZZZNOTAREALPART123")
    assert got is None
    assert a.last_status == "not_found"


def test_fetch_payload_is_ok_on_a_real_hit():
    a = DigiKeyAdapter("id", "secret", requester=lambda mpn: {"Products": [
        {"ManufacturerProductNumber": "TPS62130RGTR", "Description": {"ProductDescription": "x"}}
    ]})
    got = a.fetch_payload("TPS62130RGTR")
    assert got is not None
    assert a.last_status == "ok"


def test_lookup_never_raises_on_a_non_dict_products_entry():
    # a garbled API response with non-dict Products entries must not raise (never-raises constraint)
    body = {"Products": ["error", None, {"ManufacturerProductNumber": "X"}]}
    r = DigiKeyAdapter("id", "s", requester=lambda m: body).lookup("X")
    assert r.mpn.value == "X"                       # the real dict entry is still found
    r2 = DigiKeyAdapter("id", "s", requester=lambda m: {"Products": ["x", None]}).lookup("X")
    assert r2 is not None and r2.mpn is None        # all-garbage degrades to empty, not a crash


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
    with pytest.raises(EnrichError) as exc_info:
        _default_requester("id", "secret")("X")
    assert exc_info.value.status_code is None


def test_requester_raises_enricherror_with_status_code_on_http_error(monkeypatch):
    def _open(req, timeout=8):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if "oauth2/token" in url:
            return _Resp(_json.dumps({"access_token": "TOK"}).encode())
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    with pytest.raises(EnrichError) as exc_info:
        _default_requester("id", "secret")("X")
    assert exc_info.value.status_code == 429


def test_a_401_at_the_token_endpoint_trips_the_breaker_via_lookup(monkeypatch):
    # the token fetch itself fails auth (bad/expired DigiKey credential) - that must surface
    # through DigiKeyAdapter.lookup as auth_error, same as a 401 on the product search call.
    def _open(req, timeout=8):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        assert "oauth2/token" in url  # the search endpoint must never be reached without a token
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    a = DigiKeyAdapter("id", "secret")
    r = a.lookup("X")
    assert a.last_status == "auth_error"
    assert r.mpn is None  # a failed lookup still returns an empty result, never raises


def test_a_429_at_the_token_endpoint_trips_the_breaker_via_lookup(monkeypatch):
    def _open(req, timeout=8):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    a = DigiKeyAdapter("id", "secret")
    r = a.lookup("X")
    assert a.last_status == "rate_limited"
    assert r.mpn is None


def test_a_failed_token_is_not_cached_so_the_next_call_retries(monkeypatch):
    state = {"token_calls": 0}

    def _open(req, timeout=8):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        if "oauth2/token" in url:
            state["token_calls"] += 1
            if state["token_calls"] == 1:
                raise OSError("token endpoint down")   # first token fetch fails
            return _Resp(_json.dumps({"access_token": "TOK"}).encode())
        return _Resp(_json.dumps({"Products": [{"ManufacturerProductNumber": "X"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    req = _default_requester("id", "secret")
    with pytest.raises(EnrichError):
        req("X")                              # first call: token fetch failed -> EnrichError
    body = req("X")                           # second call: retries token, succeeds
    assert body["Products"][0]["ManufacturerProductNumber"] == "X"
    assert state["token_calls"] == 2          # the failed token was NOT memoized


def test_a_digikey_description_reads_as_prose_not_as_a_catalogue_abbreviation():
    """DigiKey serves TWO descriptions and they are not interchangeable.

    `ProductDescription` is the abbreviated string DigiKey prints in a search listing;
    `DetailedDescription` is the readable one. MEASURED on the owner's real library, 2026-07-27:
    both are present on all 158 parts, and the difference is
    "CAP CER 0.47UF 10V X7R 0402" against "0.47 uF +/-10% 10V Ceramic Capacitor X7R 0402".
    Both strings below are verbatim from `sourced/grm155r71a474ke01d-*/digikey.json`.
    """
    product = {
        "ManufacturerProductNumber": "GRM155R71A474KE01D",
        "Description": {
            "ProductDescription": "CAP CER 0.47UF 10V X7R 0402",
            "DetailedDescription": "0.47 µF ±10% 10V Ceramic Capacitor X7R 0402 (1005 Metric)",
        },
    }
    got = _parse_digikey_part(product).description.value
    assert got == "0.47 µF ±10% 10V Ceramic Capacitor X7R 0402 (1005 Metric)"


def test_the_listing_description_is_still_used_when_it_is_the_only_one_there():
    """The fallback is not dropped: a payload carrying only the abbreviated string must still
    produce a description rather than none."""
    product = {
        "ManufacturerProductNumber": "X",
        "Description": {"ProductDescription": "CAP CER 0.47UF 10V X7R 0402"},
    }
    assert _parse_digikey_part(product).description.value == "CAP CER 0.47UF 10V X7R 0402"


def test_complete_bundle_prefers_product_details_and_exposes_media_model_facts():
    bundle = {
        "schema_version": 1,
        "product_number": "296-39349-1-ND",
        "keyword_search": {"Products": [{
            "ManufacturerProductNumber": "TPD6E05U06RVZR",
            "Manufacturer": {"Name": "Texas Instruments"},
            "Description": {"ProductDescription": "short"},
            "ProductVariations": [{"DigiKeyProductNumber": "296-39349-1-ND"}],
        }]},
        "product_details": {"Product": {
            "ManufacturerProductNumber": "TPD6E05U06RVZR",
            "Manufacturer": {"Name": "Texas Instruments"},
            "Description": {"DetailedDescription": "Six-channel ESD protection diode"},
            "ProductUrl": "https://www.digikey.com/en/products/detail/ti/x/1",
            "ProductVariations": [{"DigiKeyProductNumber": "296-39349-1-ND"}],
        }},
        "media": {"MediaLinks": [
            {"MediaType": "EDA Models", "Title": "Ultra Librarian CAD Models",
             "Url": "https://app.ultralibrarian.com/details/example"},
            {"MediaType": "EDA Models", "Title": "SnapEDA CAD Models",
             "Url": "https://www.snapeda.com/parts/example"},
            {"MediaType": "Datasheets", "Title": "Datasheet",
             "Url": "https://example.test/data.pdf"},
        ]},
        "has_cad_model_search": {"Products": [
            {"ManufacturerProductNumber": "TPD6E05U06RVZR"}
        ]},
        "has_3d_model_search": {"Products": [
            {"ManufacturerProductNumber": "TPD6E05U06RVZR"}
        ]},
        "alternate_packaging": {"ProductVariations": [{"DigiKeyProductNumber": "296-X-2-ND"}]},
        "substitutions": {"Products": [{"ManufacturerProductNumber": "SUB"}]},
        "recommended_products": {"Products": [{"ManufacturerProductNumber": "REC"}]},
        "associations": {"Products": [{"ManufacturerProductNumber": "MATE"}]},
    }
    result = parse_digikey_payload(bundle, "TPD6E05U06RVZR")
    assert result.description.value == "Six-channel ESD protection diode"
    catalog = result.catalog["digikey"]
    assert catalog["availability"] == {
        "cad_model": True,
        "three_d_model": True,
        "providers": ["SnapMagic", "Ultra Librarian"],
    }
    assert {item["media_type"] for item in catalog["media"]} == {"EDA Models", "Datasheets"}
    assert catalog["alternate_packaging"]["ProductVariations"][0]["DigiKeyProductNumber"] == "296-X-2-ND"
    assert catalog["substitutions"]["Products"][0]["ManufacturerProductNumber"] == "SUB"


def test_catalog_keeps_unknown_availability_honest_when_a_probe_failed():
    bundle = {
        "keyword_search": {"Products": [{
            "ManufacturerProductNumber": "X",
            "ProductVariations": [{"DigiKeyProductNumber": "X-ND"}],
        }]},
        "product_details": {"Product": {"ManufacturerProductNumber": "X"}},
        "media": {"MediaLinks": []},
        "has_cad_model_search": {"_status": "rate_limited"},
        "has_3d_model_search": {"_status": "rate_limited"},
    }
    availability = digikey_catalog_from_payload(bundle, "X")["availability"]
    assert availability["cad_model"] is None
    assert availability["three_d_model"] is None


def test_client_maps_every_approved_product_information_endpoint(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def _open(req, timeout=8):
        url = req.full_url
        if "oauth2/token" in url:
            return _Resp(_json.dumps({"access_token": "TOK"}).encode())
        body = _json.loads(req.data.decode()) if req.data else None
        calls.append((req.get_method(), url, body))
        return _Resp(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    client = DigiKeyClient("id", "secret")
    client.keyword_search("X", search_options=("HasCadModel",))
    client.product_details("X/1")
    client.media("X")
    client.product_pricing("X")
    client.alternate_packaging("X")
    client.recommended_products("X")
    client.substitutions("X")
    client.associations("X")
    client.pricing_options_by_quantity("X", 125)
    client.digireel_pricing("X", 250)
    client.manufacturers()
    client.categories()
    client.category(32)

    urls = [url for _, url, _ in calls]
    assert calls[0][2]["FilterOptionsRequest"] == {"SearchOptions": ["HasCadModel"]}
    assert any("/X%2F1/productdetails" in url for url in urls)
    assert any("/media" in url for url in urls)
    assert any("/pricing" in url for url in urls)
    assert any("/alternatepackaging" in url for url in urls)
    assert any("/recommendedproducts" in url for url in urls)
    assert any("/substitutions" in url for url in urls)
    assert any("/associations" in url for url in urls)
    assert any("/pricingbyquantity/125" in url for url in urls)
    assert any("/digireelpricing?requestedQuantity=250" in url for url in urls)
    assert any(url.endswith("/search/manufacturers") for url in urls)
    assert any(url.endswith("/search/categories") for url in urls)
    assert any(url.endswith("/search/categories/32") for url in urls)
    assert sum("oauth2/token" in url for _, url, _ in calls) == 0
