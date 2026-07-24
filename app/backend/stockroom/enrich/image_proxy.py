"""Serve a pulled product photo to the SPA (owner 2026-07-24: "the pulled images dont
render"). The photo URL arrives in specs["Image"] from the distributor APIs; the SPA
renders it as a real <img> and falls back to this proxy when the vendor CDN refuses the
hotlink (Mouser sits behind Akamai). The proxy fetches server-side with a browser-like
identity, verifies the bytes really are an image (an HTML challenge page is refused, and
never cached, so a later attempt can still succeed), and caches on disk under the enrich
cache so a repeat render never re-hits the vendor.

The URL is HOSTILE INPUT (it originates from remote page content), so only plainly-public
https targets are ever fetched: no cleartext http, no IP literals, no loopback/private
names - this endpoint must not be usable to probe the machine or the LAN."""
from __future__ import annotations

import hashlib
import ipaddress
import logging
from pathlib import Path
from urllib.parse import urlsplit

_log = logging.getLogger("stockroom.enrich.image_proxy")

_BLOCKED_HOSTS = frozenset({"localhost"})
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")

# Browser-like identity: some vendor CDNs refuse a bare client outright. No Referer -
# hotlink guards key on a FOREIGN referer; none at all reads as a direct visit.
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5",
}


def allowed_image_url(url: str) -> bool:
    """Whether the proxy may fetch this URL at all: https, a real public-looking hostname,
    never an IP literal and never a loopback/private/mDNS-style name. Fails CLOSED on any
    parse trouble."""
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").strip().lower()
    if not host:
        return False
    if host in _BLOCKED_HOSTS or any(host.endswith(s) for s in _BLOCKED_SUFFIXES):
        return False
    if "." not in host:
        return False  # a dotless name ("intranet") is a private-network name, not a public host
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True  # a hostname, not an IP literal
    return False  # every IP literal is refused (loopback, private, AND public - no need)


def sniff_image_type(data: bytes) -> str | None:
    """The real content type of the fetched bytes, or None when they are not an image.
    Magic-byte sniffing, never the server's header: a blocked fetch commonly answers an
    HTML challenge page WITH an image/* content type."""
    if not data:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    head = data.lstrip()[:64].lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:512].lower()):
        return "image/svg+xml"
    return None


def cache_path_for(url: str, cache_dir) -> Path:
    """The stable on-disk cache slot for a URL's image bytes, under <cache_dir>/images.
    Keyed by the URL's sha256 so no remote-controlled characters ever reach the path."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]
    return Path(cache_dir) / "images" / digest


def _http_fetch(url: str) -> bytes:
    """GET the image bytes with a browser-like identity. Raises on any HTTP/transport
    failure (fetch_product_image degrades it to None)."""
    import httpx

    resp = httpx.get(url, headers=_FETCH_HEADERS, timeout=20.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def fetch_product_image(url: str, cache_dir, *, fetch=None) -> tuple[bytes, str] | None:
    """(bytes, content_type) for a product photo URL - from the disk cache when present,
    else fetched and cached - or None for a disallowed URL, a failed fetch, or bytes that
    are not really an image (which are never cached, so a transient block is retryable).
    Never raises: the SPA's <img> simply stays on its direct-src or hides."""
    if not allowed_image_url(url):
        return None
    slot = cache_path_for(url, cache_dir)
    try:
        if slot.exists():
            data = slot.read_bytes()
            ctype = sniff_image_type(data)
            if ctype is not None:
                return (data, ctype)
    except OSError:  # an unreadable cache slot is just a miss
        pass
    if fetch is None:
        fetch = _http_fetch
    try:
        data = fetch(url)
    except Exception:  # noqa: BLE001 - network/HTTP failure degrades to "no image"
        _log.info("product image fetch failed: %s", url)
        return None
    ctype = sniff_image_type(data or b"")
    if ctype is None:
        return None
    try:
        slot.parent.mkdir(parents=True, exist_ok=True)
        slot.write_bytes(data)
    except OSError:  # a full/read-only cache disk never blocks serving the bytes
        _log.warning("product image cache write failed: %s", slot)
    return (data, ctype)
