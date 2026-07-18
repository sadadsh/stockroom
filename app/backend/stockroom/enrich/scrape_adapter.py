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

from pathlib import Path

from stockroom.enrich.fetch import FetchResult
from stockroom.scrape.model import Page
from stockroom.scrape.runtime import ScrapeRuntime


def _default_engine_factory(cache_dir: Path):
    async def _factory():
        from stockroom.scrape.cache.store import ResponseCache
        from stockroom.scrape.crawl.scheduler import Scheduler
        from stockroom.scrape.engine import ScrapeEngine
        from stockroom.scrape.fetch.browser import BrowserFetcher

        browser = await BrowserFetcher().start()
        return ScrapeEngine(
            cache=ResponseCache(Path(cache_dir)),
            browser=browser,
            scheduler=Scheduler(),
        )

    return _factory


class EngineRenderedDomFetcher:
    def __init__(self, cache_dir: Path | str | None = None, runtime: ScrapeRuntime | None = None):
        # An injected runtime (tests, or a shared app runtime) is used as-is; otherwise a
        # default browser-backed runtime is built lazily on first use.
        self._runtime = runtime
        self._cache_dir = Path(cache_dir) if cache_dir is not None else Path(".scrape-cache")
        self._started = False

    def _ensure(self) -> ScrapeRuntime:
        if self._runtime is None:
            self._runtime = ScrapeRuntime(engine_factory=_default_engine_factory(self._cache_dir))
        if not self._started:
            self._runtime.start()
            self._started = True
        return self._runtime

    def rendered_html(self, url: str, timeout: float = 20.0) -> FetchResult:
        try:
            runtime = self._ensure()
            outcome = runtime.run(lambda engine: engine.render(url, timeout=timeout))
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
