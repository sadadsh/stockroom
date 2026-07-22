from stockroom.enrich.asset_source import AssetPage, resolve_asset_page
from stockroom.enrich.errors import EnrichError
from stockroom.enrich.fetch import FetchResult


class _StubFetcher:
    def __init__(self, html: str):
        self._html = html

    def get(self, url, referer="", timeout=15.0):
        return FetchResult(
            url=url,
            status=200,
            text=self._html,
            content=b"",
            content_type="text/html",
            final_url=url,
        )


class _RaisingFetcher:
    def get(self, url, referer="", timeout=15.0):
        raise EnrichError("blocked")


def test_empty_mpn_returns_none():
    assert resolve_asset_page("") is None
    assert resolve_asset_page("   ") is None


def test_default_vendor_is_ultralibrarian_search():
    page = resolve_asset_page("BQ24074RGWR")
    assert isinstance(page, AssetPage)
    assert page.vendor == "UltraLibrarian"
    assert page.needs_login is True
    assert "ultralibrarian.com" in page.url and "BQ24074RGWR" in page.url


def test_snapeda_vendor_search():
    page = resolve_asset_page("BQ24074RGWR", vendor="snapeda")
    assert page.vendor == "SnapEDA"
    assert "snapeda.com" in page.url


def test_unknown_vendor_returns_none():
    assert resolve_asset_page("BQ24074RGWR", vendor="mouser") is None


def test_snapeda_direct_page_upgrade_when_fetch_succeeds():
    html = '<a href="/parts/bq24074rgwr/texas-instruments/">BQ24074</a>'
    page = resolve_asset_page("BQ24074RGWR", vendor="snapeda", http_fetcher=_StubFetcher(html))
    assert page.url == "https://www.snapeda.com/parts/bq24074rgwr/texas-instruments/"


def test_upgrade_falls_back_to_search_on_fetch_error():
    page = resolve_asset_page("BQ24074RGWR", vendor="snapeda", http_fetcher=_RaisingFetcher())
    assert "/search/" in page.url
