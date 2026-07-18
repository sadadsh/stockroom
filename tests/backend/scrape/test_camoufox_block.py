"""The Camoufox fetcher must return an honest BLOCK (not the challenge shell as a status-200
page) when the anti-bot challenge never clears within the timeout - otherwise the shell's
"Access to this page has been denied." text is read downstream as the part's description, and
the engine's per-host breaker never learns to back off (spec 2.2 honest degradation)."""
from __future__ import annotations

import asyncio

from stockroom.scrape.fetch.camoufox_browser import CamoufoxFetcher, _looks_challenge
from stockroom.scrape.model import FetchError, Page


def test_looks_challenge_catches_every_vendor_interstitial():
    # The leaked descriptions seen in the wild were Cloudflare's "Just a moment..." and Akamai's
    # "Access to this page has been denied." Every anti-bot interstitial the distributors use must
    # be caught so its text is never returned as a page (spec 2.2 honest degradation).
    shells = [
        "<title>Just a moment...</title>",                                   # Cloudflare
        "<html><body>Access to this page has been denied.</body></html>",    # Akamai
        "<h1>Access Denied</h1>You don't have permission",                   # Akamai short
        "<p>Enable JavaScript and cookies to continue</p>",                  # Cloudflare
        "<h1>Attention Required! | Cloudflare</h1>",                         # Cloudflare
        "<div>Verifying you are human. This may take a few seconds.</div>",  # generic
        "<div>Verify you are human by completing the action</div>",         # generic
        "<div>Checking your browser before accessing</div>",                 # generic
        "<script src='https://ct.captcha-delivery.com/c.js'></script>",     # DataDome
    ]
    for shell in shells:
        assert _looks_challenge(shell) is True, shell


def test_looks_challenge_does_not_flag_a_real_product_page():
    real = ("<title>BQ24074RGTT Texas Instruments | Mouser</title>"
            "<body>Battery Management charger IC, 4.2 V, VQFN-16, RoHS. In stock.</body>")
    assert _looks_challenge(real) is False
    assert _looks_challenge("") is False


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


def _fake_asynccamoufox(monkeypatch, captured, fail_first=False):
    import camoufox.async_api

    class FakeCF:
        def __init__(self, **kw):
            captured.append(kw)
            if fail_first and len(captured) == 1:
                raise RuntimeError("profile locked")

        async def __aenter__(self):
            return "CTX"

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(camoufox.async_api, "AsyncCamoufox", FakeCF)


def test_a_profile_dir_launches_a_persistent_trust_context(monkeypatch, tmp_path):
    # Given a user_data_dir, the fetcher launches camoufox in persistent-context mode so the anti-bot
    # clearance cookie persists across renders/restarts (the trust profile).
    captured: list = []
    _fake_asynccamoufox(monkeypatch, captured)
    asyncio.run(CamoufoxFetcher(user_data_dir=tmp_path / "profile").start())
    assert captured[0].get("persistent_context") is True
    assert captured[0].get("user_data_dir") == str(tmp_path / "profile")


def test_no_profile_dir_stays_ephemeral(monkeypatch):
    captured: list = []
    _fake_asynccamoufox(monkeypatch, captured)
    asyncio.run(CamoufoxFetcher().start())
    assert "persistent_context" not in captured[0]


def test_a_locked_profile_degrades_to_ephemeral_instead_of_wedging(monkeypatch, tmp_path):
    # A persistent launch that fails (a concurrent app holds the Firefox profile lock) must fall
    # back to an ephemeral browser, not break scraping.
    captured: list = []
    _fake_asynccamoufox(monkeypatch, captured, fail_first=True)
    asyncio.run(CamoufoxFetcher(user_data_dir=tmp_path / "profile").start())
    assert len(captured) == 2                                   # persistent tried, then retried
    assert captured[0].get("persistent_context") is True        # first attempt was persistent
    assert "persistent_context" not in captured[1]              # fallback is ephemeral
