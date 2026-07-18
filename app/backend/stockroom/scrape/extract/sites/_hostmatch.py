"""Shared host matching for the per-site product adapters.

A site adapter must claim a URL only when a given brand is the REGISTRABLE domain label
(mouser.com, mouser.co.il, digikey.de, ...), never a bare subdomain, path, or query that
merely contains the word (mouser.blogspot.com / digikey.evil.com / a `?ref=mouser.com`
query must NOT be claimed - extract_product runs EVERY matching adapter, so a false claim
contaminates the result). Two-level ccTLD suffixes the distributors' regional storefronts
use are honored so `mouser.co.il` reads as the registrable domain, not `co.il`."""

from __future__ import annotations

from urllib.parse import urlparse

# Two-level public suffixes the distributor regional storefronts sit under. A regional TLD
# absent here just fails to auto-claim (a safe miss), never a false claim on a foreign host.
_TWO_LEVEL_SUFFIXES = frozenset({
    "co.il", "co.uk", "co.jp", "co.kr", "co.in", "co.za", "co.nz", "co.th",
    "com.cn", "com.mx", "com.tw", "com.br", "com.sg", "com.au", "com.hk", "com.my",
})


def registrable_domain(host: str) -> str:
    """The registrable domain (eTLD+1) of a hostname, honoring the two-level ccTLDs above, so
    mouser.co.il -> 'mouser.co.il' while mouser.blogspot.com -> 'blogspot.com'."""
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def is_brand_host(url: str, brand: str) -> bool:
    """True when `brand` is the registrable-domain label of `url`'s host. A scheme-less string
    is normalized so its host is read from the netloc, never from a path/query."""
    raw = url if "://" in (url or "") else "//" + (url or "")
    host = (urlparse(raw).hostname or "").lower()
    return registrable_domain(host).split(".", 1)[0] == brand
