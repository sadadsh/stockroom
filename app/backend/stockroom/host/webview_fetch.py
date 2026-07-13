"""The real WebView2 RenderedDomFetcher (closes the M4 deferral, spec section 6.1
item 1). Loads the page in the actual WebView2 browser context Stockroom already
hosts and reads the RENDERED DOM after JS runs, so Cloudflare/Akamai JS challenges
that fingerprint and block any HTTP client are sailed through. Satisfies the exact
M4 RenderedDomFetcher protocol, so ScrapeSource consumes it unchanged.

pywebview is imported lazily and only in the host layer, never in stockroom.api, so
the API stays a pure headless ASGI app (spec section 2.1). window_provider is
injected so this is protocol-conformance tested on Linux without WebView2."""

from __future__ import annotations

import time
from typing import Callable

from stockroom.enrich.fetch import FetchResult


class WebViewRenderedDomFetcher:
    def __init__(self, window_provider: Callable[[], object] | None = None):
        # window_provider returns a pywebview window; default resolves the running
        # app window lazily so the API layer never imports pywebview.
        self._window_provider = window_provider or _default_window

    def rendered_html(self, url: str, timeout: float = 20.0) -> FetchResult:
        window = self._window_provider()
        if window is None:
            # Honest failure, never a silent empty result: an enrich that cannot
            # render must surface, not quietly report "no fields found" (spec 2.2).
            raise RuntimeError("no WebView2 window is running; cannot render a page")
        window.load_url(url)
        # wait for the DOM to settle: a load plus a short quiescence. WebView2 does
        # not surface the HTTP status directly, so status is best-effort 200 and the
        # extraction cascade tolerates a challenge page as an empty result.
        _wait_for_settle(window, timeout)
        html = window.evaluate_js("document.documentElement.outerHTML") or ""
        final_url = window.evaluate_js("window.location.href") or url
        return FetchResult(
            url=url,
            status=200,
            text=html,
            content=html.encode("utf-8", "replace"),
            content_type="text/html",
            final_url=final_url,
        )


def _wait_for_settle(window, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        ready = window.evaluate_js("document.readyState")
        length = window.evaluate_js("document.documentElement.outerHTML.length")
        if ready == "complete" and length == last:
            return
        last = length
        time.sleep(0.25)


def _default_window():
    # Use a DEDICATED hidden fetch window, NOT the SPA window: the SPA window carries
    # the token-injecting `loaded` handler, so navigating IT to a bot-protected vendor
    # page would leak the token and hijack the user's view. fetch_window() is created
    # lazily (Windows) and is distinct by construction. Imported lazily so importing
    # this module on Linux never requires pywebview.
    from stockroom.host.window import fetch_window

    return fetch_window()
