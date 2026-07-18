"""The crawl frontier (spec section 5): an async work queue with URL canonicalization,
URL + content-hash dedup, and scope / depth / max-pages bounds. robots.txt is IGNORED per
the private-tool posture (owner directive). Canonicalization folds away the noise that
would otherwise defeat dedup (fragments, tracking params, default ports, host case), so a
crawl never re-fetches the same page under a cosmetically different URL."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params that never change the page, only tracking; dropped so they cannot defeat
# URL dedup.
_TRACKING_PREFIXES = ("utm_", "mc_")
_TRACKING_EXACT = frozenset({"gclid", "fbclid", "_ga", "ref", "ref_src", "igshid"})


def canonical_url(url: str) -> str:
    """A stable canonical form: lowercase scheme+host, drop the fragment, drop a default
    port, strip tracking params, and sort the remaining query. Path case is preserved
    (paths can be case-sensitive)."""
    parts = urlsplit((url or "").strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    default = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = f"{host}:{port}" if port and not default else host
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith(_TRACKING_PREFIXES) or k.lower() in _TRACKING_EXACT)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, query, ""))


def scope_host(url: str) -> str:
    """The host used for same-host scope decisions: the bare hostname, lowercased, WITHOUT
    port or userinfo. Seed binding and Scope.allows MUST share this basis - deriving the
    scope host from the netloc (with port) while allows() compares the hostname made a
    ported seed reject its own host and crawl nothing."""
    return (urlsplit(url).hostname or "").lower()


@dataclass
class Scope:
    host: str | None = None
    path_prefix: str = ""
    max_depth: int = 2
    max_pages: int = 50
    same_host: bool = True

    def allows(self, url: str, depth: int) -> bool:
        if depth > self.max_depth:
            return False
        parts = urlsplit(url)
        if self.same_host and self.host and scope_host(url) != self.host.lower():
            return False
        if self.path_prefix and not (parts.path or "/").startswith(self.path_prefix):
            return False
        return True


@dataclass
class Frontier:
    scope: Scope
    _seen: set = field(default_factory=set)
    _content: set = field(default_factory=set)
    _added: int = 0
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    def add(self, url: str, depth: int) -> bool:
        """Enqueue an in-scope, unseen URL (canonicalized). Returns False when it is
        out-of-scope, too deep, a duplicate, or the max-pages budget is spent."""
        if not self.scope.allows(url, depth):
            return False
        canon = canonical_url(url)
        if canon in self._seen:
            return False
        if self._added >= self.scope.max_pages:
            return False
        self._seen.add(canon)
        self._added += 1
        self._queue.put_nowait((canon, depth))
        return True

    def seen_content(self, content_hash: str) -> bool:
        """Content-hash dedup: True (already seen) if this exact body was crawled before,
        else records it and returns False. Catches the same page served under two URLs."""
        if content_hash in self._content:
            return True
        self._content.add(content_hash)
        return False

    async def get(self) -> tuple[str, int]:
        return await self._queue.get()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    @property
    def added(self) -> int:
        return self._added
