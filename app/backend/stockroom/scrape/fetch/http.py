"""The async stealth HTTP tier (spec sections 4, 6): a curl_cffi browser
impersonation GET that rotates identity and retries on a block or transport
error, and NEVER raises. Returns a Page on success or a typed FetchError. This is
the direct-download client (datasheet PDFs, JSON APIs, assets) and the fallback
transport; web pages render through the browser tier (S2)."""

from __future__ import annotations

import time
from typing import Any, Callable

from stockroom.scrape.model import FetchError, FetchOutcome, Page
from stockroom.scrape.stealth.fingerprint import FingerprintRotator

# Statuses that mean "the host pushed back", handled by rotating identity and
# retrying rather than surfacing as a hard error on the first try.
_BLOCK_STATUSES = frozenset({403, 429, 503})


def _default_session_factory() -> Any:
    from curl_cffi.requests import AsyncSession

    return AsyncSession()


class HttpClient:
    def __init__(
        self,
        rotator: FingerprintRotator | None = None,
        session_factory: Callable[[], Any] | None = None,
        retries: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._rotator = rotator or FingerprintRotator()
        self._session_factory = session_factory or _default_session_factory
        self._retries = retries
        self._clock = clock

    async def get(self, url: str, referer: str = "", timeout: float = 15.0) -> FetchOutcome:
        fp = self._rotator.current()
        last: FetchError = FetchError(url=url, reason="not attempted", kind="transport")
        for _attempt in range(self._retries + 1):
            headers = dict(fp.headers)
            if referer:
                headers["Referer"] = referer
            t0 = self._clock()
            try:
                async with self._session_factory() as session:
                    resp = await session.get(
                        url, headers=headers, impersonate=fp.impersonate, timeout=timeout
                    )
            except Exception as exc:  # noqa: BLE001 - a transport error is a typed outcome, never a raise
                last = FetchError(url=url, reason=f"transport error: {exc}", kind="transport")
                fp = self._rotator.rotate()
                continue
            status = int(getattr(resp, "status_code", 0))
            if status in _BLOCK_STATUSES:
                last = FetchError(
                    url=url, reason=f"blocked (HTTP {status})", kind="blocked", status=status
                )
                fp = self._rotator.rotate()
                continue
            elapsed_ms = (self._clock() - t0) * 1000.0
            text = getattr(resp, "text", "") or ""
            content = getattr(resp, "content", b"") or text.encode("utf-8", "replace")
            raw_headers = getattr(resp, "headers", {}) or {}
            headers_out = {str(k): str(v) for k, v in dict(raw_headers).items()}
            return Page(
                url=url,
                final_url=str(getattr(resp, "url", url) or url),
                status=status,
                content=content,
                text=text,
                content_type=headers_out.get("Content-Type", ""),
                headers=headers_out,
                render_tier="http",
                fetch_ms=elapsed_ms,
            )
        return last
