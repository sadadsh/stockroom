"""The scrape engine's fetch-result model: a fetched Page or a typed FetchError.

The engine never raises to a caller (spec section 3.1). Every fetch returns a
Page on success or a FetchError describing an honest, non-blocking failure, so a
consumer (enrichment) continues and no bad data is invented."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # type-only; avoids any runtime import cost / cycle risk
    from stockroom.enrich.schema import EnrichmentResult


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    status: int
    content: bytes
    text: str
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False
    render_tier: str = "http"  # "http" | "browser" | "cache"
    fetch_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass(frozen=True)
class FetchError:
    url: str
    reason: str
    kind: str  # "blocked" | "timeout" | "transport" | "http_error"
    status: int = 0
    # A server Retry-After (seconds), parsed from a 429/503 when present, so the anti-ban
    # scheduler can honor exactly how long the host asked us to wait. None = not supplied.
    retry_after: float | None = None

    @property
    def ok(self) -> bool:
        return False


FetchOutcome = Page | FetchError


@dataclass
class ScrapeResult:
    """The engine's general scrape output (spec section 3.1): the fetched Page,
    readability markdown, generic web structured-data blobs, in-page links, and, for
    the part-enrichment consumer, a validated component `product` record. `product` is
    typed against enrich.schema, the SHARED canonical component contract (a pure leaf
    data module); this is the one allowed scrape -> enrich.schema crossing."""

    page: Page
    markdown: str = ""
    structured: dict[str, Any] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)
    product: "EnrichmentResult | None" = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.page.ok
