"""The Camoufox fetcher must return an honest BLOCK (not the challenge shell as a status-200
page) when the anti-bot challenge never clears within the timeout - otherwise the shell's
"Access to this page has been denied." text is read downstream as the part's description, and
the engine's per-host breaker never learns to back off (spec 2.2 honest degradation)."""
from __future__ import annotations

import asyncio

from stockroom.scrape.fetch.camoufox_browser import CamoufoxFetcher
from stockroom.scrape.model import FetchError, Page


class _Resp:
    status = 200


class _FakePage:
    def __init__(self, html: str):
        self._html = html
        self.url = "https://www.mouser.com/final"

    async def goto(self, url, **kw):
        return _Resp()

    async def content(self):
        return self._html

    async def close(self):
        pass


class _FakeBrowser:
    def __init__(self, html: str):
        self._html = html

    async def new_page(self):
        return _FakePage(self._html)


def _fetch(html: str):
    f = CamoufoxFetcher()
    f._browser = _FakeBrowser(html)
    return asyncio.run(f.fetch("https://www.mouser.com/en/ProductDetail/x", timeout=0.4))


def test_unsolved_challenge_returns_a_blocked_error_not_a_page():
    out = _fetch("<html><body>Access to this page has been denied.</body></html>")
    assert isinstance(out, FetchError)
    assert out.kind == "blocked"  # feeds the engine's breaker + negative cache


def test_real_page_still_returns_a_page():
    real = "<html><body>" + ("x" * 30000) + " BQ24074 charger</body></html>"
    out = _fetch(real)
    assert isinstance(out, Page)
    assert out.status == 200
    assert "denied" not in out.text.lower()
