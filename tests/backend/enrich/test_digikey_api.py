from stockroom.enrich.digikey_api import _parse_digikey_part, DigiKeyAdapter

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
