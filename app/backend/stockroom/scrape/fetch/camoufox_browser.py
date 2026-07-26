"""The Camoufox render tier: the maximum-stealth page fetcher (spec section 6; owner:
"ultra undetectable"). Camoufox is a Firefox fork with C++-level anti-detection and
genuine, self-consistent BrowserForge fingerprints; unlike patched Chromium it defeats
BOTH Akamai (the _abck/sensor layer) AND DataDome (the transparent captcha-delivery
challenge) on the hardest targets (proven live against Mouser: full price ladder + stock
+ specs in ~6-8s). It is drop-in with BrowserFetcher's interface (start / aclose / fetch
-> Page | FetchError, never raises), so ScrapeEngine.render uses it unchanged.

CRITICAL own-code lesson (verified): Camoufox ships uBlock Origin, which BLOCKS DataDome's
own challenge script (ct.captcha-delivery.com) and so PREVENTS the transparent challenge
from ever completing -> a permanent challenge page. uBO is therefore DISABLED here, which
is the difference between "hard CAPTCHA forever" and a clean solve. Resources are NOT
blocked either, so every anti-bot script the challenge needs can run."""

from __future__ import annotations

import asyncio
import time

from stockroom.scrape.model import FetchError, FetchOutcome, Page

# A real product page is hundreds of KB; the Akamai "access denied" and DataDome
# captcha-delivery challenge SHELLS are ~2 KB. Settling requires substantial, stable,
# non-challenge content, so we wait THROUGH the transparent challenge until it resolves. The
# interstitial markers live in the shared challenge module so every fetcher uses one vetted list.
_MIN_REAL_BYTES = 20000
from stockroom.scrape.fetch.challenge import looks_challenge as _looks_challenge  # noqa: E402


class CamoufoxFetcher:
    def __init__(self, headless: bool = True, os_profile: str = "windows",
                 user_data_dir=None):
        self._headless = headless
        self._os = os_profile
        # A PERSISTENT profile dir turns the fetcher into a trust-accumulating browser: the anti-bot
        # clearance cookie (DataDome/Cloudflare) a solved challenge sets is stored here and REUSED on
        # every later render and every restart, instead of throwing away a fresh context per page and
        # re-solving the challenge from zero each time (the cause of the re-challenge/throttle spiral).
        # None keeps the old ephemeral-per-render behavior (tests, callers that opt out).
        self._user_data_dir = user_data_dir
        self._cf = None      # the AsyncCamoufox async-context-manager instance
        self._browser = None

    async def start(self) -> "CamoufoxFetcher":
        from camoufox import DefaultAddons
        from camoufox.async_api import AsyncCamoufox

        # Genuine Windows fingerprint, humanized cursor, GeoIP-consistent locale/timezone,
        # and uBlock DISABLED so anti-bot challenge scripts can run (see module docstring). Camoufox
        # applies the fingerprint at LAUNCH level, so a persistent context carries the SAME
        # fingerprint AND persists cookies/storage - the trust profile (see __init__).
        opts = dict(headless=self._headless, os=self._os, humanize=True, geoip=True,
                    exclude_addons=[DefaultAddons.UBO])
        if self._user_data_dir is not None:
            import os as _os_mod

            _os_mod.makedirs(str(self._user_data_dir), exist_ok=True)
            opts.update(persistent_context=True, user_data_dir=str(self._user_data_dir))
        try:
            self._cf = AsyncCamoufox(**opts)
            self._browser = await self._cf.__aenter__()
        except Exception:  # noqa: BLE001 - a locked/unusable profile must never wedge the fetcher
            # A persistent-profile launch can fail (a concurrent app holds the Firefox profile lock,
            # or the dir is unwritable). Degrade to the ephemeral browser rather than break scraping.
            if self._user_data_dir is None:
                raise
            self._cf = AsyncCamoufox(headless=self._headless, os=self._os, humanize=True,
                                     geoip=True, exclude_addons=[DefaultAddons.UBO])
            self._browser = await self._cf.__aenter__()
        return self

    async def aclose(self) -> None:
        try:
            if self._cf is not None:
                await self._cf.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001 - teardown never raises
            pass
        self._browser = None
        self._cf = None

    async def fetch(self, url: str, timeout: float = 30.0) -> FetchOutcome:
        if self._browser is None:
            return FetchError(url=url, reason="camoufox not started", kind="transport")
        page = None
        try:
            page = await self._browser.new_page()
            t0 = time.monotonic()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            await self._settle(page, timeout)
            html = await page.content() or ""
            if _looks_challenge(html):
                # The challenge never cleared within the timeout (a hard block): return an honest
                # "blocked", NOT the ~2 KB challenge SHELL as a status-200 page. Otherwise its
                # "Access to this page has been denied." text is read downstream as the part's
                # description (spec 2.2 honest degradation), and the engine's per-host breaker
                # never learns to back off. _settle only returns via its success path once the
                # page is already unchallenged, so this fires exactly on the settle-timeout case.
                return FetchError(url=url, reason="anti-bot challenge did not clear", kind="blocked")
            final_url = page.url or url
            status = int(resp.status) if resp is not None else 200
            return Page(
                url=url,
                final_url=final_url,
                status=status,
                content=html.encode("utf-8", "replace"),
                text=html,
                content_type="text/html",
                render_tier="browser",
                fetch_ms=(time.monotonic() - t0) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001 - a render failure is a typed outcome
            return FetchError(url=url, reason=f"camoufox render failed: {exc}", kind="timeout")
        finally:
            if page is not None:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _settle(self, page, timeout: float) -> None:
        """Wait until the page has rendered substantial, NON-challenge content, so a
        transparent Akamai/DataDome interstitial (a ~2 KB shell) is waited through until it
        auto-solves and the real page loads. Returns as soon as the real page is present
        (a short grace lets late hydration finish) rather than requiring exact byte-stability
        a live page rarely reaches. Bounded by timeout; never raises."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                html = await page.content()
            except Exception:  # noqa: BLE001 - a transient read is not a settle signal
                await asyncio.sleep(0.4)
                continue
            if not _looks_challenge(html) and len(html or "") > _MIN_REAL_BYTES:
                await asyncio.sleep(1.0)   # brief grace for late-hydrating content
                return
            await asyncio.sleep(0.5)
