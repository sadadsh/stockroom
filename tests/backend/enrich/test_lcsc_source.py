"""LcscSource end-to-end over REAL fixtures (jlcsearch + LCSC product page): only the
network transport is stubbed, so the jlcsearch client, the __NEXT_DATA__ extractor,
and the source's merge logic all run for real. This is the path the current suite
never exercised (it stubbed the fetcher), which is how the dead LCSC search URL
shipped green - so this test drives the thing under test, not a stub of it."""

from __future__ import annotations

import json
from pathlib import Path

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.pipeline import LcscSource
from stockroom.enrich.registry import DEFAULT_WANT

FIX = Path(__file__).parent / "fixtures"


class _LcscStubHttp:
    """One HttpFetcher stub for both GETs: the jlcsearch JSON, then the product HTML."""

    def __init__(self, jlc_json: str, product_html: str):
        self._jlc = jlc_json
        self._html = product_html
        self.gets: list[str] = []

    def get(self, url, referer="", timeout=15.0):
        from stockroom.enrich.fetch import FetchResult

        self.gets.append(url)
        body = self._html if "product-detail" in url else self._jlc
        return FetchResult(url, 200, body, body.encode(), "text/html", url)


def _product_html() -> str:
    nextdata = json.loads((FIX / "lcsc_nextdata_C60490.json").read_text(encoding="utf-8"))
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(nextdata)
        + "</script></html>"
    )


def _jlc_json(mpn: str) -> str:
    samples = json.loads((FIX / "jlcsearch_samples.json").read_text(encoding="utf-8"))
    return json.dumps(samples[mpn])


def test_lcsc_source_fills_full_data_from_the_catalog():
    http = _LcscStubHttp(_jlc_json("RC0402FR-0710KL"), _product_html())
    r = LcscSource(http_fetcher=http).enrich(
        "RC0402FR-0710KL", "Resistors", set(DEFAULT_WANT)
    )
    # jlcsearch leg: LCSC id + package + price breaks + stock
    assert r.dist_pns["lcsc"] == "C60490"
    assert r.package.value == "0402"
    assert r.price_breaks and r.price_breaks[0].price > 0
    assert r.stock.value == 4377117  # live jlcsearch stock (the page's own is a spec)
    assert r.specs["Stock"].value == "857900"  # product-page stockNumber, also captured
    # product-page leg: manufacturer + datasheet PDF + the full spec set
    assert r.manufacturer.value == "YAGEO"
    assert ".pdf" in r.datasheet_url.value
    assert r.specs["Resistance"].value == "10kΩ"
    assert r.specs["HTS Code (US)"].value == "8533210020"
    assert r.specs["ECCN"].value == "EAR99"
    # a purchase link is buildable (the product_url spec drives the Purchase that
    # carries the price breaks -> this is what makes Build & Cost work)
    assert "product_url" in r.specs


def test_lcsc_source_is_empty_on_a_catalog_miss():
    http = _LcscStubHttp(json.dumps({"components": []}), _product_html())
    r = LcscSource(http_fetcher=http).enrich("NOTATHING", "ICs", set(DEFAULT_WANT))
    assert r.package is None and not r.specs and not r.price_breaks
    # a miss must not even fetch a product page
    assert not any("product-detail" in u for u in http.gets)


def test_lcsc_source_never_raises_on_network_death():
    class _Dead:
        def get(self, url, referer="", timeout=15.0):
            raise EnrichError("dead")

    r = LcscSource(http_fetcher=_Dead()).enrich(
        "RC0402FR-0710KL", "Resistors", set(DEFAULT_WANT)
    )
    assert r.package is None  # empty result, the registry walk continues
