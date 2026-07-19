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


def test_none_when_disabled_or_no_mpn_or_no_url():
    assert resolve_digikey_cad_source("BQ24074", _Adapter(False, "https://x")) is None
    assert resolve_digikey_cad_source("", _Adapter(True, "https://x")) is None
    assert resolve_digikey_cad_source("BQ24074", _Adapter(True, None)) is None
