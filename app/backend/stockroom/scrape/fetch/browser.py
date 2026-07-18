"""The headless-Chromium render tier (spec sections 4, 6): the PRIMARY page
fetcher. Loads a page in a stealthed Playwright Chromium context, blocks heavy
resources for speed, waits until real content settles (past any bot
interstitial), and returns the rendered DOM as a Page(render_tier="browser"). It
never raises: a render failure is a typed FetchError, so enrichment continues.

The pure decision helpers (settle / challenge / resource-block) are split out so
they unit-test offline; BrowserFetcher orchestrates them with a real browser."""

from __future__ import annotations

import asyncio
import time

from stockroom.scrape.model import FetchError, FetchOutcome, Page
from stockroom.scrape.stealth.patches import (
    STEALTH_INIT_SCRIPT,
    real_user_agent,
    stealth_context_options,
    stealth_launch_args,
)

# Text a bot-manager interstitial (Akamai / Cloudflare) shows while its JS proof
# of work runs, before it redirects to the real page.
_CHALLENGE_MARKERS = (
    "access denied",
    "verifying you are human",
    "checking your browser",
    "enable javascript and cookies",
    "unusual traffic",
    "please wait while we verify",
)
# A real product page renders thousands of characters; a challenge shell renders
# almost none. The settle signal is a substantial, STABLE body of text.
_MIN_REAL_TEXT = 400
# Resource types that never carry content but cost latency and detection surface.
_BLOCK_TYPES = frozenset({"image", "media", "font"})
_BLOCK_HOSTS = (
    "googletagmanager.com",
    "google-analytics.com",
    "doubleclick.net",
    "facebook.net",
    "adservice.google.com",
)


def is_challenge_text(probe: str) -> bool:
    p = (probe or "").lower()
    return any(marker in p for marker in _CHALLENGE_MARKERS)


def looks_settled(
    ready_state: str, text_len: int, last_text_len: int | None, challenged: bool
) -> bool:
    """True once the page has rendered a substantial, stable body of visible text and
    no longer looks like a bot challenge. Waiting past the (text-less) challenge is
    what lets a real browser reach a page an HTTP client is 403'd from."""
    return (
        ready_state == "complete"
        and last_text_len is not None
        and text_len == last_text_len
        and text_len >= _MIN_REAL_TEXT
        and not challenged
    )


def should_block_resource(resource_type: str, url: str) -> bool:
    if resource_type in _BLOCK_TYPES:
        return True
    u = (url or "").lower()
    return any(host in u for host in _BLOCK_HOSTS)


class BrowserFetcher:
    def __init__(self, headless: bool = True):
        self._headless = headless
        self._pw = None
        self._browser = None
        self._ua = ""

    async def start(self) -> "BrowserFetcher":
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless, args=stealth_launch_args()
        )
        # Compute the de-Headless UA once from the real engine UA, so every context
        # presents a coherent Chrome identity.
        ctx = await self._browser.new_context()
        page = await ctx.new_page()
        default_ua = await page.evaluate("() => navigator.userAgent")
        await ctx.close()
        self._ua = real_user_agent(default_ua or "")
        return self

    async def aclose(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass

    async def fetch(self, url: str, timeout: float = 20.0) -> FetchOutcome:
        if self._browser is None:
            return FetchError(url=url, reason="browser not started", kind="transport")
        ctx = None
        try:
            ctx = await self._browser.new_context(**stealth_context_options(self._ua))
            await ctx.add_init_script(STEALTH_INIT_SCRIPT)
            page = await ctx.new_page()

            async def _route(route):
                req = route.request
                if should_block_resource(req.resource_type, req.url):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", _route)
            t0 = time.monotonic()
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            await self._settle(page, timeout)
            html = await page.evaluate("() => document.documentElement.outerHTML") or ""
            final_url = await page.evaluate("() => location.href") or url
            status = int(resp.status) if resp is not None else 200
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            return Page(
                url=url,
                final_url=final_url,
                status=status,
                content=html.encode("utf-8", "replace"),
                text=html,
                content_type="text/html",
                render_tier="browser",
                fetch_ms=elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001 - a render failure is a typed outcome, never a raise
            return FetchError(url=url, reason=f"render failed: {exc}", kind="timeout")
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _settle(self, page, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        last: int | None = None
        while time.monotonic() < deadline:
            try:
                ready = await page.evaluate("() => document.readyState")
                text_len = await page.evaluate(
                    "() => (document.body && document.body.innerText || '').length"
                )
                probe = await page.evaluate(
                    "() => (document.title + ' ' + ((document.body && document.body.innerText) || ''))"
                    ".slice(0, 500)"
                )
            except Exception:  # noqa: BLE001 - a transient eval error is not a settle signal
                await asyncio.sleep(0.3)
                continue
            if looks_settled(ready, int(text_len or 0), last, is_challenge_text(probe or "")):
                return
            last = int(text_len or 0)
            await asyncio.sleep(0.3)
