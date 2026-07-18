"""End-to-end stealth proof against a real headless Chromium (the S2 acceptance
gate from the feasibility probe). Serves a local page that writes the live
navigator values into the DOM, renders it through BrowserFetcher, and asserts the
tells are gone: navigator.webdriver is not true, the UA carries no "Headless",
and plugins are spoofed. Skipped cleanly when Chromium cannot launch."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from stockroom.scrape.fetch.browser import BrowserFetcher
from stockroom.scrape.model import Page

pytestmark = pytest.mark.requires_browser

_PROBE_BODY = (
    b"<html><body><script>"
    b"document.body.innerText = 'wd=' + navigator.webdriver + ' ua=' + navigator.userAgent"
    b" + ' plugins=' + navigator.plugins.length + ' ' + 'x'.repeat(600);"
    b"</script></body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_PROBE_BODY)

    def log_message(self, *args):
        pass


def _launch_ok() -> bool:
    async def _try():
        bf = await BrowserFetcher().start()
        await bf.aclose()
        return True

    try:
        return asyncio.run(_try())
    except Exception:
        return False


_AVAILABLE = _launch_ok()
skip_no_browser = pytest.mark.skipif(
    not _AVAILABLE, reason="headless Chromium cannot launch in this environment"
)


@pytest.fixture(scope="module")
def probe_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/probe"
    server.shutdown()


@skip_no_browser
def test_render_returns_browser_page(probe_url):
    async def _scenario():
        bf = await BrowserFetcher().start()
        try:
            return await bf.fetch(probe_url, timeout=15.0)
        finally:
            await bf.aclose()

    out = asyncio.run(_scenario())
    assert isinstance(out, Page)
    assert out.render_tier == "browser"
    assert out.status == 200


@skip_no_browser
def test_stealth_hides_the_headless_tells(probe_url):
    async def _scenario():
        bf = await BrowserFetcher().start()
        try:
            return await bf.fetch(probe_url, timeout=15.0)
        finally:
            await bf.aclose()

    out = asyncio.run(_scenario())
    assert isinstance(out, Page)
    low = out.text.lower()
    assert "wd=true" not in low  # navigator.webdriver no longer true
    assert ("wd=undefined" in low) or ("wd=false" in low)
    assert "plugins=5" in out.text  # plugins spoofed to a realistic length
    assert "Headless" not in out.text  # UA de-Headlessed
