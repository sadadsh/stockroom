"""S5: the bridge from enrichment to the portable scrape engine.

`EngineRenderedDomFetcher` implements enrich's `RenderedDomFetcher` protocol
(`rendered_html(url) -> FetchResult`) by driving `ScrapeEngine.render()` — the pooled,
stealthed, anti-ban-governed headless Chromium — over the `ScrapeRuntime` persistent-loop
bridge (a browser is bound to its creating loop, so the sync enrichment cascade drives it
through the runtime). This replaces the HTTP-only default so JS-rendered distributor pages
resolve on every OS. It NEVER raises: a block or dead page yields an honest empty
FetchResult, so enrichment continues (source-agnostic completeness). The runtime + Chromium
start lazily on the first render, so merely constructing the fetcher is cheap."""

from __future__ import annotations

import threading
from pathlib import Path

from stockroom.enrich.fetch import FetchResult
from stockroom.scrape.model import Page
from stockroom.scrape.runtime import ScrapeRuntime


def _default_engine_factory(cache_dir: Path):
    async def _factory():
        from stockroom.scrape.cache.store import ResponseCache
        from stockroom.scrape.crawl.scheduler import Scheduler
        from stockroom.scrape.engine import ScrapeEngine
        from stockroom.scrape.fetch.camoufox_browser import CamoufoxFetcher

        # Camoufox (genuine-fingerprint Firefox, uBlock disabled) is the render tier: it
        # defeats BOTH Akamai and DataDome on the hardest distributors (Mouser), where
        # patched headless Chromium is hard-blocked. The Scheduler paces per host so the
        # crawler never self-flags a WAF. A PERSISTENT profile under the cache dir keeps the
        # anti-bot clearance cookie across renders/restarts, so a solved challenge is not
        # re-solved on every request (the re-challenge/throttle spiral).
        browser = await CamoufoxFetcher(
            user_data_dir=Path(cache_dir) / "camoufox-profile"
        ).start()
        return ScrapeEngine(
            cache=ResponseCache(Path(cache_dir)),
            browser=browser,
            scheduler=Scheduler(),
        )

    return _factory


class EngineRenderedDomFetcher:
    def __init__(self, cache_dir: Path | str | None = None, runtime: ScrapeRuntime | None = None,
                 run_timeout_buffer: float = 10.0):
        # An injected runtime (tests, or a shared app runtime) is used as-is; otherwise a
        # default browser-backed runtime is built lazily on first use.
        self._runtime = runtime
        self._cache_dir = Path(cache_dir) if cache_dir is not None else Path(".scrape-cache")
        # A wall-clock ceiling on run() = render timeout + this buffer, so an anti-ban cooldown
        # (up to BREAKER_CAP) in engine.render can never pin the calling thread indefinitely.
        self._run_timeout_buffer = run_timeout_buffer
        self._started = False
        # The app shares one fetcher across CONCURRENT enrich requests (FastAPI threadpool),
        # so the lazy start must be serialized or two threads could double-start the runtime.
        self._lock = threading.Lock()

    def _ensure(self) -> ScrapeRuntime:
        with self._lock:
            if self._runtime is None:
                self._runtime = ScrapeRuntime(
                    engine_factory=_default_engine_factory(self._cache_dir)
                )
            if not self._started:
                self._runtime.start()
                self._started = True
            return self._runtime

    def rendered_html(self, url: str, timeout: float = 20.0, on_stage=None) -> FetchResult:
        try:
            runtime = self._ensure()
            # on_stage is invoked on the runtime loop thread (inside engine.render, just
            # before the browser settle). It only puts onto the job's thread-safe event
            # queue, and the sync bridge blocks this thread until the render returns, so
            # the caller's fetching/extracting emits never race the loop's rendering emit.
            # Only threaded through when a sink is present, so the render call keeps its
            # original signature on the default (no-progress) path.
            kw = {"on_stage": on_stage} if on_stage is not None else {}
            outcome = runtime.run(
                lambda engine: engine.render(url, timeout=timeout, **kw),
                timeout=timeout + self._run_timeout_buffer,
            )
        except Exception:  # noqa: BLE001 - enrichment never blocks on a render failure
            return FetchResult(url=url, status=0, text="", content=b"",
                               content_type="", final_url=url)
        if isinstance(outcome, Page):
            return FetchResult(
                url=outcome.url,
                status=outcome.status,
                text=outcome.text,
                content=outcome.content,
                content_type=outcome.content_type,
                final_url=outcome.final_url or url,
            )
        # A typed FetchError: an honest empty result so the enrichment walk continues.
        return FetchResult(url=url, status=getattr(outcome, "status", 0) or 0, text="",
                           content=b"", content_type="", final_url=url)

    def close(self) -> None:
        if self._runtime is not None and self._started:
            self._runtime.stop()
            self._started = False


def default_rendered_dom_fetcher(cache_dir: Path | str) -> EngineRenderedDomFetcher:
    """The app's rendered-DOM fetcher: the portable stealthed engine, Chromium started
    lazily on the first render. Wired by serve.build_context (retiring the HTTP-only
    default and the never-shipped WebView2 seam)."""
    return EngineRenderedDomFetcher(cache_dir=cache_dir)
