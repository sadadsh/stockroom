from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.jlcsearch import JlcHit, JlcSearchClient
from stockroom.enrich.schema import PriceBreak

FIX = Path(__file__).parent / "fixtures"
SAMPLES = json.loads((FIX / "jlcsearch_samples.json").read_text(encoding="utf-8"))


class _StubHttpFetcher:
    """Mirror of the test_pipeline stub: return a FetchResult-like object whose
    .text is the raw JSON for one searched MPN, no network."""

    def __init__(self, payload):
        self._text = json.dumps(payload)
        self.urls: list[str] = []

    def get(self, url, referer="", timeout=15.0):
        from stockroom.enrich.fetch import FetchResult

        self.urls.append(url)
        return FetchResult(url, 200, self._text, self._text.encode(), "application/json", url)


class _RaisingHttpFetcher:
    def get(self, url, referer="", timeout=15.0):
        raise EnrichError(f"fetch failed for {url}")


class _BadJsonHttpFetcher:
    def get(self, url, referer="", timeout=15.0):
        from stockroom.enrich.fetch import FetchResult

        text = "<html>not json</html>"
        self.last = url
        return FetchResult(url, 200, text, text.encode(), "text/html", url)


def test_resistor_search_resolves_lcsc_package_mpn_and_price_breaks():
    fetcher = _StubHttpFetcher(SAMPLES["RC0402FR-0710KL"])
    client = JlcSearchClient(http_fetcher=fetcher)

    hit = client.search("RC0402FR-0710KL")

    assert isinstance(hit, JlcHit)
    assert hit.lcsc == "C60490"
    assert hit.package == "0402"
    assert hit.mpn == "RC0402FR-0710KL"
    assert hit.stock > 0
    assert hit.category == "Resistors"
    assert hit.price_breaks, "expected parsed price breaks"
    first = hit.price_breaks[0]
    assert isinstance(first, PriceBreak)
    assert first.qty == 20
    assert first.currency == "USD"
    assert first.price == pytest.approx(0.000485714)
    # sorted by qty ascending
    qtys = [b.qty for b in hit.price_breaks]
    assert qtys == sorted(qtys)


def test_search_url_is_quoted_and_targets_jlcsearch():
    fetcher = _StubHttpFetcher(SAMPLES["RC0402FR-0710KL"])
    client = JlcSearchClient(http_fetcher=fetcher)
    client.search("RC0402FR/0710 KL")
    url = fetcher.urls[0]
    assert url.startswith("https://jlcsearch.tscircuit.com/components/list.json?search=")
    assert " " not in url
    assert "/0710" not in url  # slash was url-quoted


def test_best_row_prefers_preferred_then_basic_then_stock():
    payload = {
        "components": [
            {"lcsc": 111, "mfr": "LOW", "package": "0402", "stock": 999999,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": False},
            {"lcsc": 222, "mfr": "BASIC", "package": "0402", "stock": 10,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": True, "is_preferred": False},
            {"lcsc": 333, "mfr": "PREF", "package": "0402", "stock": 5,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": True},
        ]
    }
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher(payload))
    hit = client.search("whatever")
    assert hit.lcsc == "C333"  # preferred wins over basic and over high stock


def test_best_row_basic_beats_plain_when_no_preferred():
    payload = {
        "components": [
            {"lcsc": 111, "mfr": "LOW", "package": "0402", "stock": 999999,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": False},
            {"lcsc": 222, "mfr": "BASIC", "package": "0402", "stock": 10,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": True, "is_preferred": False},
        ]
    }
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher(payload))
    assert client.search("x").lcsc == "C222"


def test_in_stock_rows_preferred_over_out_of_stock():
    payload = {
        "components": [
            {"lcsc": 111, "mfr": "OOS_PREF", "package": "0402", "stock": 0,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": True, "is_preferred": True},
            {"lcsc": 222, "mfr": "IN_STOCK", "package": "0402", "stock": 3,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": False},
        ]
    }
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher(payload))
    assert client.search("x").lcsc == "C222"


def test_falls_back_to_out_of_stock_when_none_in_stock():
    payload = {
        "components": [
            {"lcsc": 111, "mfr": "OOS", "package": "0402", "stock": 0,
             "price": "[]", "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": True},
        ]
    }
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher(payload))
    hit = client.search("x")
    assert hit is not None
    assert hit.lcsc == "C111"
    assert hit.stock == 0


def test_empty_components_returns_none():
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher({"components": []}))
    assert client.search("nope") is None


def test_missing_components_key_returns_none():
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher({}))
    assert client.search("nope") is None


@pytest.mark.parametrize("bad_price", ["", None, "not-json", "[{\"price\": 1}]"])
def test_malformed_price_yields_empty_price_breaks(bad_price):
    payload = {
        "components": [
            {"lcsc": 999, "mfr": "X", "package": "0402", "stock": 5,
             "price": bad_price, "category": "R", "subcategory": "Chip",
             "is_basic": False, "is_preferred": False},
        ]
    }
    client = JlcSearchClient(http_fetcher=_StubHttpFetcher(payload))
    hit = client.search("x")
    assert hit.price_breaks == []


def test_transport_failure_propagates_as_enrich_error():
    client = JlcSearchClient(http_fetcher=_RaisingHttpFetcher())
    with pytest.raises(EnrichError):
        client.search("x")


def test_unparseable_json_raises_enrich_error():
    client = JlcSearchClient(http_fetcher=_BadJsonHttpFetcher())
    with pytest.raises(EnrichError):
        client.search("x")
