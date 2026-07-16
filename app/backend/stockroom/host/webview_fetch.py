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

    def rendered_html(
        self, url: str, timeout: float = 20.0, wait_selector: str | None = None
    ) -> FetchResult:
        window = self._window_provider()
        if window is None:
            # Honest failure, never a silent empty result: an enrich that cannot
            # render must surface, not quietly report "no fields found" (spec 2.2).
            raise RuntimeError("no WebView2 window is running; cannot render a page")
        window.load_url(url)
        # wait for the DOM to settle: a load plus a short quiescence. WebView2 does
        # not surface the HTTP status directly, so status is best-effort 200 and the
        # extraction cascade tolerates a challenge page as an empty result. wait_selector
        # holds for a specific element (a distributor's price table, which loads via a LATER
        # AJAX call than the page shell), so a stable-but-not-yet-priced page is not returned early.
        _wait_for_settle(window, timeout, wait_selector)
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


# Text a bot-manager interstitial (Akamai / Cloudflare) shows while its JS proof of
# work runs, BEFORE it redirects to the real page. If the DOM still reads like this we
# must keep waiting, or we would return the challenge HTML and extract nothing.
_CHALLENGE_MARKERS = (
    "access denied",
    "verifying you are human",
    "checking your browser",
    "enable javascript and cookies",
    "unusual traffic",
    "reference #",
    "please wait while we verify",
)


def _looks_challenged(window) -> bool:
    """True when the current DOM reads like a bot-manager interstitial rather than the
    real product page. Defensive: any evaluate_js failure means "cannot tell", treated
    as NOT challenged, so a page that simply has no body never blocks past readyState
    complete (no regression for a normal page, which carries none of these markers)."""
    try:
        probe = window.evaluate_js(
            "(document.title + ' ' + ((document.body && document.body.innerText) || ''))"
            ".slice(0, 500).toLowerCase()"
        ) or ""
    except Exception:
        return False
    return any(marker in probe for marker in _CHALLENGE_MARKERS)


# A bot interstitial (Akamai / Cloudflare) renders almost no VISIBLE text while its
# JS runs the proof of work, then redirects to the real page. A real product page
# renders thousands of characters. Verified live: the Mouser challenge page has 0 body
# text (readyState already "complete", title just "mouser.com"), then the real page
# loads with ~3500. So the load-detection signal is a substantial, STABLE body of text,
# NOT readyState (which is "complete" on the challenge too) and NOT visible challenge
# wording (this challenge shows none).
_MIN_REAL_TEXT = 400


def _has_selector(window, selector: str) -> bool:
    """True when the live DOM contains an element matching `selector`. Defensive: an
    evaluate_js failure reads as "present" so a JS quirk never hangs the wait past its
    real content (the stable-text gate still applies)."""
    import json as _json

    try:
        return bool(window.evaluate_js(f"!!document.querySelector({_json.dumps(selector)})"))
    except Exception:
        return True


def _wait_for_settle(window, timeout: float, wait_selector: str | None = None) -> None:
    """Return once the page has rendered a substantial, stable body of visible text and
    no longer looks like a bot challenge, or the timeout elapses. Waiting past the
    (text-less) challenge is what lets a real browser reach a page an HTTP client is
    403'd from. On timeout we return whatever is there: a still-challenged page extracts
    to an empty result, surfaced honestly as "nothing came back", never invented data.

    When `wait_selector` is given, the page is not considered settled until that element
    exists too: a distributor's price table loads via a LATER AJAX call than the shell, so
    the body text can stabilize while the prices are still absent - returning then would
    yield a real-but-unpriced page. The stable-text gate still bounds the extra wait."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        ready = window.evaluate_js("document.readyState")
        text_len = window.evaluate_js(
            "(document.body && document.body.innerText || '').length"
        ) or 0
        if (
            ready == "complete"
            and text_len == last
            and text_len >= _MIN_REAL_TEXT
            and not _looks_challenged(window)
            and (wait_selector is None or _has_selector(window, wait_selector))
        ):
            return
        last = text_len
        time.sleep(0.3)


def _default_window():
    # Use a DEDICATED hidden fetch window, NOT the SPA window: the SPA window carries
    # the token-injecting `loaded` handler, so navigating IT to a bot-protected vendor
    # page would leak the token and hijack the user's view. fetch_window() is created
    # lazily (Windows) and is distinct by construction. Imported lazily so importing
    # this module on Linux never requires pywebview.
    from stockroom.host.window import fetch_window

    return fetch_window()
