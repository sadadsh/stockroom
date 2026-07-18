"""The scrape engine's fetch-result model: a fetched Page or a typed FetchError.

The engine never raises to a caller (spec section 3.1). Every fetch returns a
Page on success or a FetchError describing an honest, non-blocking failure, so a
consumer (enrichment) continues and no bad data is invented."""

from __future__ import annotations

from dataclasses import dataclass, field


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

    @property
    def ok(self) -> bool:
        return False


FetchOutcome = Page | FetchError
