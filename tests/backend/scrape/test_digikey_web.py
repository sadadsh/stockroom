"""DigiKey product-page extractor. DigiKey is a Next.js app that embeds the full product record
as JSON in <script id="__NEXT_DATA__">; the extractor parses that structured envelope to reach
Mouser-parity depth (identity, the full parametric spec table, the price-break ladder, stock,
datasheet, lead time, the DigiKey order P/N, part status = lifecycle, and the RoHS/compliance
block), with a bare-cell <td> regex kept as a fallback for a page that lacks the JSON."""
from __future__ import annotations

import json

from stockroom.scrape.extract.sites.digikey_web import DigiKeyWebSite

_URL = "https://www.digikey.com/en/products/detail/yageo/RC0603FR-0710KL/726880"

# A compact __NEXT_DATA__ envelope exercising every section the real page carries.
_NEXT = {
    "props": {"pageProps": {"envelope": {"data": {
        "productOverview": {
            "manufacturerProductNumber": "RC0603FR-0710KL",
            "manufacturer": "YAGEO",
            "description": "10 kOhms Chip Resistor",
            "detailedDescription": "10 kOhms +-1% 0.1W, 1/10W Chip Resistor 0603 Thick Film",
            "datasheetUrl": "https://yageogroup.com/datasheet/RC0603.pdf",
            "standardLeadTime": "17 Weeks",
            "digikeyProductNumbers": {"value": [{"label": "311-10.0KHRTR-ND",
                                                 "value": "311-10.0KHRTR-ND"}]},
        },
        "priceQuantity": {"qtyAvailable": "6,196,975"},
        "quantityTable": [
            {"breakQty": 100, "unitPrice": 0.0122},
            {"breakQty": 1, "unitPrice": 0.10},
            {"breakQty": 10, "unitPrice": 0.05},
        ],
        "productAttributes": {"attributes": [
            {"label": "Resistance", "values": [{"value": "10 kOhms"}]},
            {"label": "Tolerance", "values": [{"value": "+-1%"}]},
            {"label": "Part Status", "values": [{"value": "Active"}]},
            {"label": "Package / Case", "values": [{"value": "0603 (1608 Metric)"}]},
            {"label": "Packaging", "values": [{"value": "Tape & Reel (TR)"},
                                              {"value": "Cut Tape (CT)"}]},
            {"label": "Failure Rate", "values": [{"value": "-"}]},
            {"label": "Mfr", "values": [{"value": "YAGEO"}]},
        ]},
        "environmental": {"dataRows": [
            {"dataCells": [{"data": {"value": {"value": "RoHS Status"}}},
                           {"data": {"value": {"value": "ROHS3 Compliant"}}}]},
            {"dataCells": [{"data": {"value": {"value": "ECCN"}}},
                           {"data": {"value": {"value": "EAR99"}}}]},
        ]},
    }}}}
}


def _html(next_data: dict) -> str:
    return ('<html><head><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(next_data) + "</script></head><body></body></html>")


def _result():
    return DigiKeyWebSite().extract(_html(_NEXT), _URL)


def test_identity_from_next_data():
    r = _result()
    assert r.mpn.value == "RC0603FR-0710KL"
    assert r.manufacturer.value == "YAGEO"
    assert r.description.value.startswith("10 kOhms +-1%")
    assert r.datasheet_url.value == "https://yageogroup.com/datasheet/RC0603.pdf"
    assert r.lead_time.value == "17 Weeks"
    assert r.dist_pns["digikey"] == "311-10.0KHRTR-ND"


def test_stock_and_price_ladder_sorted_and_complete():
    r = _result()
    assert r.stock.value == 6196975
    assert [(b.qty, b.price) for b in r.price_breaks] == [(1, 0.10), (10, 0.05), (100, 0.0122)]


def test_spec_table_package_lifecycle_and_multivalue():
    r = _result()
    assert r.specs["Resistance"].value == "10 kOhms"
    assert r.specs["Tolerance"].value == "+-1%"
    # Package / Case promotes to the package field, not a stray spec
    assert r.package.value == "0603 (1608 Metric)"
    assert "Package / Case" not in r.specs and "Package/Case" not in r.specs
    # Part Status becomes the canonical lifecycle field + a "Lifecycle" spec (the bom/corpus key)
    assert r.lifecycle.value == "Active"
    assert r.specs["Lifecycle"].value == "Active"
    assert "Part Status" not in r.specs
    # multi-value attribute joins its options
    assert r.specs["Packaging"].value == "Tape & Reel (TR); Cut Tape (CT)"


def test_empty_dashes_and_redundant_mfr_are_cleaned():
    r = _result()
    # DigiKey uses "-" for an empty attribute -> dropped, never a "-" spec
    assert "Failure Rate" not in r.specs
    # the redundant "Mfr" attribute is folded to the canonical "Manufacturer" key
    assert r.specs["Manufacturer"].value == "YAGEO"
    assert "Mfr" not in r.specs


def test_environmental_rohs_is_canonical():
    r = _result()
    assert r.specs["RoHS"].value == "ROHS3 Compliant"
    assert r.specs["ECCN"].value == "EAR99"
    assert "RoHS Status" not in r.specs


def test_matches_only_registrable_digikey_domain():
    m = DigiKeyWebSite()
    assert m.matches("https://www.digikey.com/en/products/detail/x/y/1")
    assert m.matches("https://www.digikey.de/de/products/detail/x/y/1")
    assert m.matches("https://digikey.co.uk/x")
    assert not m.matches("https://digikey.evil.com/x")
    assert not m.matches("https://www.mouser.com/x")
    assert not m.matches("https://example.com/?ref=www.digikey.com/x")


def test_datasheet_redirect_gotourl_is_unwrapped():
    # DigiKey wraps some manufacturer datasheets in a TI-style redirect; the REAL datasheet is the
    # gotoUrl param. Unwrap it and trust DigiKey's explicit datasheet field (the PDF is validated
    # at fetch time, so the generic ".pdf"/"datasheet" URL heuristic must not reject a real one).
    nd = json.loads(json.dumps(_NEXT))
    nd["props"]["pageProps"]["envelope"]["data"]["productOverview"]["datasheetUrl"] = (
        "https://www.ti.com/general/docs/suppproductinfo.tsp?distId=10&gotoUrl="
        "https%3A%2F%2Fwww.ti.com%2Flit%2Fgpn%2Fsn74lvc1g08")
    r = DigiKeyWebSite().extract(_html(nd), _URL)
    assert r.datasheet_url.value == "https://www.ti.com/lit/gpn/sn74lvc1g08"


def test_no_next_data_falls_back_to_bare_cell_rows():
    # a page without the JSON blob still yields something via the <td> fallback (older/blocked)
    html = "<table><tr><td>Resistance</td><td>10 kOhms</td></tr></table>"
    r = DigiKeyWebSite().extract(html, _URL)
    assert r.specs.get("Resistance") is not None and r.specs["Resistance"].value == "10 kOhms"


def test_never_raises_on_malformed_envelope_shapes():
    # Untrusted distributor JSON of arbitrary shape must NEVER crash extract() (the never-raises
    # contract): a truthy non-dict where a dict is expected, a P/N list of bare strings, a scalar
    # where a table/list is expected. Each degrades to a result, not an exception.
    bad_envelopes = [
        {"productOverview": "Not Found"},
        {"productOverview": {"digikeyProductNumbers": {"value": ["296-1234-ND"]}}},
        {"quantityTable": 5, "productAttributes": "x", "environmental": 7, "priceQuantity": 9},
        {"productAttributes": {"attributes": "x"}},
        {"productAttributes": {"attributes": [{"label": "R", "values": 3}]}},
    ]
    for data in bad_envelopes:
        nd = {"props": {"pageProps": {"envelope": {"data": data}}}}
        r = DigiKeyWebSite().extract(_html(nd), _URL)  # must not raise
        assert r is not None


def test_package_prefers_the_clean_supplier_device_package():
    # An IC lists both "Package / Case" (verbose "SC-74A, SOT-753") and "Supplier Device Package"
    # (clean "SOT-23-5"); the clean token wins regardless of attribute order.
    nd = json.loads(json.dumps(_NEXT))
    nd["props"]["pageProps"]["envelope"]["data"]["productAttributes"]["attributes"] = [
        {"label": "Package / Case", "values": [{"value": "SC-74A, SOT-753"}]},
        {"label": "Supplier Device Package", "values": [{"value": "SOT-23-5"}]},
    ]
    r = DigiKeyWebSite().extract(_html(nd), _URL)
    assert r.package.value == "SOT-23-5"
    # the verbose "Package / Case" case detail is kept as a spec (no depth lost)
    assert r.specs["Package / Case"].value == "SC-74A, SOT-753"


def test_currency_from_price_symbol_not_hardcoded_usd():
    # A regional storefront prices in EUR/GBP; the currency is the symbol in the pricing tiers, so
    # the ladder must not be mislabeled USD (the BOM cost layer would sum a EUR price as dollars).
    nd = json.loads(json.dumps(_NEXT))
    nd["props"]["pageProps"]["envelope"]["data"]["priceQuantity"]["pricing"] = [
        {"mergedPricingTiers": [{"brkQty": "1", "unitPrice": "€0.12"}]}]
    r = DigiKeyWebSite().extract(_html(nd), _URL)
    assert r.price_breaks and all(b.currency == "EUR" for b in r.price_breaks)


def test_protocol_relative_datasheet_is_kept():
    nd = json.loads(json.dumps(_NEXT))
    nd["props"]["pageProps"]["envelope"]["data"]["productOverview"]["datasheetUrl"] = (
        "//media.digikey.com/pdf/x.pdf")
    r = DigiKeyWebSite().extract(_html(nd), _URL)
    assert r.datasheet_url.value == "https://media.digikey.com/pdf/x.pdf"
