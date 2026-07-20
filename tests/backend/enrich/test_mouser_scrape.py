"""The keyless Mouser data adapter for the bulk rescan: it scrapes the part's ALREADY-STORED
Mouser product link (no MPN->URL guessing) via the rendered-DOM fetcher, runs the Mouser web
extractor, and returns an EnrichmentResult in the rescan adapter shape (.enabled/.lookup/
.last_status/.vendor). A block (empty render) trips the rescan circuit breaker; a missing link
or a thin page is an honest not_found that does not trip it."""

from __future__ import annotations

from pathlib import Path

from stockroom.enrich.fetch import FetchResult
from stockroom.enrich.mouser_scrape import MouserScrapeAdapter
from stockroom.enrich.refresh import _has_data

FIXTURE = Path(__file__).parent / "fixtures" / "mouser_full.html"


class FakeFetcher:
    """A stand-in RenderedDomFetcher: records the URLs it was asked to render and returns a
    canned FetchResult, so the adapter is tested without a live browser."""

    def __init__(self, result: FetchResult):
        self._result = result
        self.calls: list[str] = []

    def rendered_html(self, url, timeout=20.0, on_stage=None) -> FetchResult:
        self.calls.append(url)
        return self._result


def _fr(text: str, final_url: str = "https://www.mouser.com/x", status: int = 200) -> FetchResult:
    return FetchResult(
        url=final_url, status=status, text=text, content=b"",
        content_type="text/html", final_url=final_url,
    )


def test_lookup_scrapes_the_stored_link_and_extracts_procurement():
    html = FIXTURE.read_text(encoding="utf-8")
    url = "https://www.mouser.com/en/ProductDetail/Panasonic/ERJ-P03F1101V?qs=abc"
    fetcher = FakeFetcher(_fr(html, final_url=url))
    a = MouserScrapeAdapter(fetcher, url_for=lambda m: {"erj-p03f1101v": url}.get(m))

    r = a.lookup("erj-p03f1101v")

    assert fetcher.calls == [url]  # scraped the STORED link verbatim; no /c/?q= search
    assert a.vendor == "Mouser"
    assert a.last_status == "ok"
    assert r.stock is not None and r.stock.value == 5616
    assert len(r.price_breaks) == 9
    assert r.dist_pns.get("mouser") == "667-ERJ-P03F1101V"
    assert r.lifecycle is not None and r.lifecycle.value == "Active"


def test_missing_link_is_not_found_and_never_fetches():
    fetcher = FakeFetcher(_fr("<html/>"))
    a = MouserScrapeAdapter(fetcher, url_for=lambda m: None)

    r = a.lookup("no-link-part")

    assert a.last_status == "not_found"
    assert not _has_data(r)
    assert fetcher.calls == []  # no link -> no network


def test_blocked_empty_render_trips_the_breaker():
    fetcher = FakeFetcher(_fr("", status=0))  # a WAF block collapses to empty text
    a = MouserScrapeAdapter(fetcher, url_for=lambda m: "https://www.mouser.com/x")

    r = a.lookup("m")

    assert a.last_status == "rate_limited"  # exactly the token RescanEngine._lookup trips on
    assert not _has_data(r)


def test_thin_page_is_not_found_without_tripping():
    fetcher = FakeFetcher(_fr("<html><body>nothing procurement here</body></html>"))
    a = MouserScrapeAdapter(fetcher, url_for=lambda m: "https://www.mouser.com/x")

    r = a.lookup("m")

    assert a.last_status == "not_found"
    assert not _has_data(r)


def test_disabled_when_no_fetcher_is_wired():
    a = MouserScrapeAdapter(None, url_for=lambda m: "https://www.mouser.com/x")
    assert a.enabled is False
    assert not _has_data(a.lookup("m"))


# --- API fallback (owner 2026-07-19: crawler primary, Mouser API rescues blocks/errors) ---
from stockroom.enrich.schema import EnrichmentResult, Sourced  # noqa: E402


class _FakeApi:
    def __init__(self, result, status="ok"):
        self._result, self._status = result, status
        self.enabled = True
        self.last_status = ""
        self.calls: list[str] = []

    def lookup(self, mpn):
        self.calls.append(mpn)
        self.last_status = self._status
        return self._result


def _api_result():
    r = EnrichmentResult()
    r.stock = Sourced(42, "mouser", "high")
    return r


def test_api_fallback_rescues_a_blocked_crawler():
    blocked = FakeFetcher(_fr("", status=0))  # crawler WAF-blocked -> empty render
    api = _FakeApi(_api_result())
    a = MouserScrapeAdapter(blocked, url_for=lambda m: "https://www.mouser.com/x", api_fallback=api)
    r = a.lookup("MPN")
    assert api.calls == ["MPN"]       # the API was consulted
    assert a.last_status == "ok"      # rescued -> breaker does NOT trip
    assert r.stock is not None and r.stock.value == 42


def test_crawler_success_does_not_call_the_api():
    html = FIXTURE.read_text(encoding="utf-8")
    ok = FakeFetcher(_fr(html, final_url="https://www.mouser.com/p"))
    api = _FakeApi(_api_result())
    a = MouserScrapeAdapter(ok, url_for=lambda m: "https://www.mouser.com/p", api_fallback=api)
    a.lookup("erj-p03f1101v")
    assert a.last_status == "ok"
    assert api.calls == []            # crawler served it; the API quota is untouched


def test_blocked_crawler_goes_api_only_for_the_rest_of_the_run():
    blocked = FakeFetcher(_fr("", status=0))
    api = _FakeApi(_api_result())
    a = MouserScrapeAdapter(blocked, url_for=lambda m: "https://www.mouser.com/x", api_fallback=api)
    a.lookup("A")
    a.lookup("B")
    assert blocked.calls == ["https://www.mouser.com/x"]  # crawler tried ONCE, then skipped
    assert api.calls == ["A", "B"]                        # both served by the API


def test_api_only_when_no_crawler_fetcher():
    api = _FakeApi(_api_result())
    a = MouserScrapeAdapter(None, url_for=lambda m: "x", api_fallback=api)
    assert a.enabled is True          # the API alone enables it
    r = a.lookup("MPN")
    assert api.calls == ["MPN"] and r.stock.value == 42


def test_both_exhausted_reports_rate_limited_to_trip_the_breaker():
    blocked = FakeFetcher(_fr("", status=0))
    api = _FakeApi(EnrichmentResult(), status="rate_limited")  # API also rate-limited
    a = MouserScrapeAdapter(blocked, url_for=lambda m: "https://www.mouser.com/x", api_fallback=api)
    a.lookup("MPN")
    assert a.last_status == "rate_limited"  # both exhausted -> breaker trips
