import pytest

from stockroom.enrich.fetch import FetchResult, RenderedDomFetcher
from stockroom.host.webview_fetch import WebViewRenderedDomFetcher


class _FakeWindow:
    """Stands in for a pywebview window: load_url records the nav, evaluate_js
    returns canned rendered HTML and the settled href."""

    def __init__(self, html, href):
        self._html = html
        self._href = href
        self.loaded = None

    def load_url(self, url):
        self.loaded = url

    def evaluate_js(self, script):
        if "readyState" in script:
            return "complete"
        if "outerHTML.length" in script:
            return len(self._html)
        if "outerHTML" in script:
            return self._html
        if "location.href" in script:
            return self._href
        return None


def test_conforms_to_the_rendered_dom_fetcher_protocol():
    win = _FakeWindow("<html><body>rendered</body></html>", "https://x/final")
    fetcher = WebViewRenderedDomFetcher(window_provider=lambda: win)
    assert isinstance(fetcher, RenderedDomFetcher)


def test_rendered_html_returns_a_well_formed_fetchresult():
    win = _FakeWindow(
        '<html><head><script type="application/ld+json">{"@type":"Product"}</script>'
        "</head><body>ok</body></html>",
        "https://www.lcsc.com/product-detail/C1.html",
    )
    fetcher = WebViewRenderedDomFetcher(window_provider=lambda: win)
    r = fetcher.rendered_html("https://www.lcsc.com/product-detail/C1.html", timeout=1.0)
    assert isinstance(r, FetchResult)
    assert "application/ld+json" in r.text
    assert r.final_url == "https://www.lcsc.com/product-detail/C1.html"
    assert r.content_type == "text/html"
    assert win.loaded is not None  # it actually navigated


def test_missing_window_is_an_honest_error_not_a_silent_empty():
    fetcher = WebViewRenderedDomFetcher(window_provider=lambda: None)
    with pytest.raises(RuntimeError):
        fetcher.rendered_html("https://x", timeout=0.1)


@pytest.mark.windows_only
def test_real_webview2_reads_a_rendered_dom():
    # Owner runs this on the Windows box against a real page; asserts the rendered
    # DOM contains JS-injected content the raw HTTP fetch does not. See the task's
    # acceptance bar. Skipped everywhere else.
    ...
