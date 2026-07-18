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
# non-challenge content, so we wait THROUGH the transparent challenge until it resolves.
_MIN_REAL_BYTES = 20000
_CHALLENGE_MARKERS = ("captcha-delivery.com", "has been denied", "datadome",
                      "verifying you are human", "checking your browser")


def _looks_challenge(html: str) -> bool:
    h = (html or "").lower()
    return any(m in h for m in _CHALLENGE_MARKERS)


class CamoufoxFetcher:
    def __init__(self, headless: bool = True, os_profile: str = "windows"):
        self._headless = headless
        self._os = os_profile
        self._cf = None      # the AsyncCamoufox async-context-manager instance
        self._browser = None

    async def start(self) -> "CamoufoxFetcher":
        from camoufox import DefaultAddons
        from camoufox.async_api import AsyncCamoufox

        # Genuine Windows fingerprint, humanized cursor, GeoIP-consistent locale/timezone,
        # and uBlock DISABLED so anti-bot challenge scripts can run (see module docstring).
        self._cf = AsyncCamoufox(
            headless=self._headless,
            os=self._os,
            humanize=True,
            geoip=True,
            exclude_addons=[DefaultAddons.UBO],
        )
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
        """Wait until the page has rendered substantial, stable, NON-challenge content, so a
        transparent Akamai/DataDome interstitial (a ~2 KB shell) is waited through until it
        auto-solves and the real page loads. Bounded by timeout; never raises."""
        deadline = time.monotonic() + timeout
        last: int | None = None
        while time.monotonic() < deadline:
            try:
                html = await page.content()
            except Exception:  # noqa: BLE001 - a transient read is not a settle signal
                await asyncio.sleep(0.4)
                continue
            length = len(html or "")
            if (not _looks_challenge(html) and last is not None
                    and length == last and length > _MIN_REAL_BYTES):
                return
            last = length
            await asyncio.sleep(0.5)
