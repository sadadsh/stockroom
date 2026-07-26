from stockroom.enrich.cad_source import resolve_digikey_cad_source
from stockroom.enrich.schema import EnrichmentResult, Sourced


class _Adapter:
    def __init__(self, enabled, product_url):
        self.enabled = enabled
        self._url = product_url

    def lookup(self, mpn):
        r = EnrichmentResult()
        if self._url is not None:
            r.product_url = Sourced(self._url, "digikey", "high")
        return r


def test_returns_the_digikey_product_url_for_an_mpn():
    a = _Adapter(True, "https://www.digikey.com/en/products/detail/x/BQ24074/123")
    assert resolve_digikey_cad_source("BQ24074", a) == "https://www.digikey.com/en/products/detail/x/BQ24074/123"


def test_search_fallback_unless_blank_mpn():
    search = "https://www.digikey.com/en/products/result?keywords=BQ24074"
    # disabled adapter -> keyword search fallback (no creds needed to open a page)
    assert resolve_digikey_cad_source("BQ24074", _Adapter(False, "https://x")) == search
    # enabled adapter but no product page -> the same search fallback
    assert resolve_digikey_cad_source("BQ24074", _Adapter(True, None)) == search
    # absent adapter -> the same search fallback, without touching adapter.lookup
    assert resolve_digikey_cad_source("BQ24074", None) == search
    # only a blank mpn returns None
    assert resolve_digikey_cad_source("", _Adapter(True, "https://x")) is None
