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


# The distributor each known host IS, by the name a person uses. Lives here, beside the other
# url parsing, because the enrich pipeline needs it and cannot import a FastAPI router; it used
# to live only in `api/routers/ingest.py`, which is exactly why the pipeline hardcoded the string
# "scrape" instead and 85 of the owner's records ended up filed under a mechanism name.
_KNOWN_VENDOR_HOSTS = {"lcsc": "LCSC", "mouser": "Mouser", "digikey": "DigiKey"}

# LCSC product urls end in the C-number, either bare (`/product-detail/C3034813.html`) or after a
# descriptive slug (`/product-detail/Thermistors_Semitec-103AT-2_C3034813.html`). A SEARCH url has
# no part number at all, and must yield "" rather than a guess: 20 of the owner's records only
# ever resolved to a search page, and inventing a number for those would be worse than empty.
_LCSC_IN_PATH = __import__("re").compile(r"(?:^|[-_/])(C\d+)(?:\.html?)?$", __import__("re").I)


def vendor_from_url(url: str) -> str:
    """The distributor's NAME for a purchase link: a known distributor by name, any other shop by
    its host, and a non-url as a manual entry. Never the name of the mechanism that found it."""
    u = (url or "").strip()
    try:
        host = (urlparse(u).hostname or "").lower()
    except ValueError:
        return "manual"
    if not host:
        return "manual"
    for token, name in _KNOWN_VENDOR_HOSTS.items():
        if token in host:
            return name
    return host.removeprefix("www.")


def distributor_part_number_from_url(url: str) -> str:
    """The distributor's own part number embedded in a product url, or "".

    Extends `distributor_mpn_from_url` (Mouser/DigiKey only, by design -- those are the two
    Akamai-guarded sites with an official API) to LCSC, whose C-number is the key the
    easyeda2kicad conversion needs. Returns "" for anything unrecognised, including a search
    page: an empty part number is honest, and a guessed one is a wrong part.
    """
    u = (url or "").strip()
    if not u:
        return ""
    known = distributor_mpn_from_url(u)
    if known is not None:
        return known[1]
    try:
        parsed = urlparse(u)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if "lcsc." not in host:
        return ""
    for segment in reversed([s for s in parsed.path.split("/") if s]):
        m = _LCSC_IN_PATH.search(unquote(segment))
        if m:
            return m.group(1).upper()
    return ""
