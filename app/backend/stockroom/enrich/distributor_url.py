"""Parse a distributor PRODUCT url into (vendor, search-token).

Mouser and DigiKey guard their product pages with Akamai Bot Manager, so rendering
them is slow and often blocked. But both publish an official Search API that resolves
a part number to the full record in one WAF-free call. This module pulls the part
number out of a pasted product url so the paste-a-link path can hit that API instead
of rendering the blocked page. It recognizes ONLY Mouser and DigiKey product urls (the
two Akamai-guarded distributors that have an official-API adapter here); every other
url returns None, and the caller renders the page as before (LCSC, manufacturer pages,
anything unrecognized).
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse


def distributor_mpn_from_url(url: str) -> tuple[str, str] | None:
    """(vendor, token) for a recognized Mouser/DigiKey product url, else None.

    The token is the part number embedded in the path; the official API resolves it
    (an exact MPN, a Mouser part number, or a searchable slug) to the canonical part.
    None means "not a recognized distributor product url": the caller renders instead.
    """
    u = (url or "").strip()
    if not u:
        return None
    try:
        parsed = urlparse(u)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    lower = [s.lower() for s in segments]

    if "mouser." in host:
        # .../ProductDetail/<Manufacturer>/<MPN>  OR  .../ProductDetail/<PartNumber>
        # The last segment after 'productdetail' is the part token; the qs= link tail is ignored.
        if "productdetail" in lower:
            tail = segments[lower.index("productdetail") + 1:]
            if tail and tail[-1].strip():
                return ("mouser", tail[-1].strip())
        return None

    if "digikey." in host:
        # .../products/detail/<mfr-slug>/<MPN>/<digikey-pn>: the MPN is the MIDDLE segment.
        if "detail" in lower:
            tail = segments[lower.index("detail") + 1:]
            if len(tail) >= 2 and tail[1].strip():
                return ("digikey", tail[1].strip())
        return None

    return None
