"""The URL fetch layer.

Enrichment loads pages with a real, Chrome-impersonating TLS fingerprint
(curl_cffi), not a plain HTTP client, so Cloudflare/Akamai's client checks that
fingerprint-and-ban a bare requests call pass (spec section 6.1, item 1). The
full JS-rendered DOM is behind the RenderedDomFetcher protocol seam, which M5
wires to a real WebView2 engine; M4 ships an HTTP-only default impl of it so the
seam is real and the pipeline is wired end-to-end today (documented deferral).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from stockroom.enrich.errors import EnrichError

# Default headers a real browser sends. Referer is added per-request when the
# datasheet or product link came from a known landing page.
_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    content: bytes
    content_type: str
    final_url: str


def _make_session(impersonate: str) -> Any:
    # Imported lazily so the module (and its Protocol) import even where curl_cffi
    # is not installed (e.g. a schema-only unit run); construction is what needs it.
    from curl_cffi import requests as curl_requests

    return curl_requests.Session(impersonate=impersonate)


class HttpFetcher:
    def __init__(self, impersonate: str = "chrome", session: Any = None):
        self._impersonate = impersonate
        self._session = session

    def _session_obj(self) -> Any:
        if self._session is None:
            self._session = _make_session(self._impersonate)
        return self._session

    def get(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchResult:
        headers = dict(_DEFAULT_HEADERS)
        if referer:
            headers["Referer"] = referer
        try:
            resp = self._session_obj().get(url, headers=headers, timeout=timeout)
        except EnrichError:
            raise
        except Exception as exc:  # curl_cffi transport error
            raise EnrichError(f"fetch failed for {url}: {exc}") from exc
        content = getattr(resp, "content", b"") or resp.text.encode()
        return FetchResult(
            url=url,
            status=int(resp.status_code),
            text=resp.text,
            content=content,
            content_type=(resp.headers.get("Content-Type", "") or ""),
            final_url=str(getattr(resp, "url", url)),
        )


@runtime_checkable
class RenderedDomFetcher(Protocol):
    """The M5 seam: return the page's HTML as a browser would see it AFTER JS runs.

    M5 wires a real WebView2 engine behind this. M4 ships HttpRenderedDomFetcher,
    which returns the raw HTTP HTML (no JS execution). Every enrichment path that
    consumes a RenderedDomFetcher therefore works today; only JS rendering is
    deferred to M5 (spec section 6.1, item 1)."""

    def rendered_html(self, url: str, timeout: float = 20.0) -> FetchResult: ...


class HttpRenderedDomFetcher:
    """M4 default RenderedDomFetcher: serve the static HTTP HTML, no JS. Honest:
    it does not claim to render JS. Sufficient for the structured-data-first
    cascade, whose targets (JSON-LD, OpenGraph, meta) sit in the initial HTML."""

    def __init__(self, http: HttpFetcher | None = None):
        self._http = http or HttpFetcher()

    def rendered_html(self, url: str, timeout: float = 20.0) -> FetchResult:
        return self._http.get(url, timeout=timeout)
