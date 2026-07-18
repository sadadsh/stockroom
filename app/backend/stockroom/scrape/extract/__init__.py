"""The scrape extraction layer's public surface: the SiteExtractor protocol, the
structured-first product cascade (extract_product / extract_all), and build_scrape_result
which assembles a full ScrapeResult (markdown + structured blobs + links + validated
product). enrich.schema is the shared canonical component contract this layer normalizes
into (the one allowed scrape -> enrich.schema crossing)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from stockroom.enrich.schema import EnrichmentResult
from stockroom.scrape.extract.content import to_markdown
from stockroom.scrape.extract.html import extract_links
from stockroom.scrape.extract.sites import SITE_ADAPTERS
from stockroom.scrape.extract.structured import (
    _heuristic,
    extract_jsonld_product,
    extract_microdata,
    extract_next_data,
    extract_nuxt,
    extract_opengraph,
    structured_blobs,
)
from stockroom.scrape.model import Page, ScrapeResult
from stockroom.scrape.validate import validate_product


@runtime_checkable
class SiteExtractor(Protocol):
    def matches(self, url: str) -> bool: ...
    def extract(self, html: str, url: str) -> EnrichmentResult: ...


def extract_product(html: str, url: str, site_extractors=SITE_ADAPTERS) -> EnrichmentResult:
    """Structured-data-first component cascade (spec section 4 step 4). Order and merge
    rules match the retired enrich.extract_all: JSON-LD (high) seeds, then OpenGraph,
    next_data, NUXT, microdata fill only gaps, then site adapters add site-specific
    extras (a site pricing table's full ladder supersedes a lone generic JSON-LD offer),
    then the title/h1 heuristic fills last."""
    result = extract_jsonld_product(html)
    result.merge_missing(extract_opengraph(html))
    result.merge_missing(extract_next_data(html))
    for ext in site_extractors:
        if ext.matches(url):
            site = ext.extract(html, url)
            # A site pricing table's full ladder supersedes a lone generic offer. This
            # comparison must see only the JSON-LD/next_data price_breaks (as in the proven
            # enrich order), so nuxt/microdata run AFTER the adapters, not before, or a
            # generic single-offer price could raise the threshold and block a real table.
            if len(site.price_breaks) > len(result.price_breaks):
                result.price_breaks = list(site.price_breaks)
            result.merge_missing(site)
    # nuxt + microdata are generic fallbacks below the site adapters: they gap-fill only
    # what a matching adapter did not, so the site-adapter precedence is preserved exactly.
    result.merge_missing(extract_nuxt(html))
    result.merge_missing(extract_microdata(html))
    result.merge_missing(_heuristic(html))
    return result


extract_all = extract_product  # parity name for the retired enrich orchestrator


def build_scrape_result(page: Page, site_extractors=SITE_ADAPTERS) -> ScrapeResult:
    """Assemble the full ScrapeResult from a fetched Page: readability markdown, generic
    structured blobs, in-page links, and the VALIDATED component product. Never raises on
    its own (not only via a caller's guard): any internal failure yields a page-only
    ScrapeResult, so a good fetch is never sunk by an extraction bug (spec section 3.1)."""
    try:
        url = page.final_url or page.url
        html = page.text or ""
        product = validate_product(extract_product(html, url, site_extractors))
        blobs = structured_blobs(html)
        title = blobs.get("meta", {}).get("og:title", "")
        return ScrapeResult(
            page=page,
            markdown=to_markdown(html, base_url=url),
            structured=blobs,
            links=extract_links(html, url),
            product=product,
            metadata={"title": title, "final_url": url},
        )
    except Exception:  # noqa: BLE001 - extraction never sinks a good fetch (spec section 3.1)
        return ScrapeResult(page=page)
