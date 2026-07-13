import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.fetch import (
    FetchResult,
    HttpFetcher,
    HttpRenderedDomFetcher,
    RenderedDomFetcher,
)


class _FakeCurlResponse:
    def __init__(self, status, text, headers, url):
        self.status_code = status
        self.text = text
        self.content = text.encode()
        self.headers = headers
        self.url = url


class _FakeSession:
    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc
        self.last_kwargs = None

    def get(self, url, **kwargs):
        self.last_kwargs = kwargs
        if self._raise is not None:
            raise self._raise
        return self._response


def test_http_fetcher_returns_structured_result():
    resp = _FakeCurlResponse(
        200, "<html>ok</html>", {"Content-Type": "text/html; charset=utf-8"},
        "https://example.com/final",
    )
    f = HttpFetcher(session=_FakeSession(resp))
    r = f.get("https://example.com/p", referer="https://example.com/")
    assert isinstance(r, FetchResult)
    assert r.status == 200
    assert r.text == "<html>ok</html>"
    assert r.content_type.startswith("text/html")
    assert r.final_url == "https://example.com/final"


def test_http_fetcher_sends_referer_when_given():
    resp = _FakeCurlResponse(200, "x", {"Content-Type": "text/html"}, "u")
    session = _FakeSession(resp)
    HttpFetcher(session=session).get("https://x/p", referer="https://x/ref")
    assert session.last_kwargs["headers"]["Referer"] == "https://x/ref"


def test_http_fetcher_wraps_transport_error():
    f = HttpFetcher(session=_FakeSession(raise_exc=RuntimeError("tls broke")))
    with pytest.raises(EnrichError):
        f.get("https://x/p")


def test_http_fetcher_returns_non_200_status_without_raising():
    resp = _FakeCurlResponse(403, "blocked", {"Content-Type": "text/html"}, "u")
    r = HttpFetcher(session=_FakeSession(resp)).get("https://x/p")
    assert r.status == 403  # a status is data, not an exception


def test_http_rendered_dom_fetcher_satisfies_the_protocol():
    resp = _FakeCurlResponse(200, "<html>rendered</html>", {"Content-Type": "text/html"}, "u")
    rdf = HttpRenderedDomFetcher(http=HttpFetcher(session=_FakeSession(resp)))
    assert isinstance(rdf, RenderedDomFetcher)  # runtime_checkable Protocol
    r = rdf.rendered_html("https://x/p")
    assert r.text == "<html>rendered</html>"
