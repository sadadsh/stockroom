"""Resolve a part's Ultra Librarian / SnapEDA page from its MPN.

Primary CAD-source resolver for guided capture: UL/SnapEDA offer BOTH KiCad and
Altium downloads behind a real control the guided window can click. The reliable
floor is a deterministic vendor search URL (no network). A best-effort
direct-part-page upgrade runs only when a fetcher is supplied and succeeds; the
live pages are login-gated and change, so any failure degrades to the search URL
(owner validates live selectors). DigiKey stays a fallback resolved elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from stockroom.enrich.errors import EnrichError

_UL_KEYS = {"ultralibrarian", "ul", "ultra librarian"}
_SNAPEDA = "snapeda"
_SNAPEDA_PART_RE = re.compile(r'href="(/parts/[^"]+)"')


@dataclass
class AssetPage:
    url: str
    vendor: str
    needs_login: bool = False


def _search_url(vendor: str, mpn: str) -> str | None:
    q = quote_plus(mpn)
    if vendor in _UL_KEYS:
        return f"https://app.ultralibrarian.com/search?queryText={q}"
    if vendor == _SNAPEDA:
        return f"https://www.snapeda.com/search/?q={q}&SearchType=all"
    return None


def _label(vendor: str) -> str:
    return "SnapEDA" if vendor == _SNAPEDA else "UltraLibrarian"


def resolve_asset_page(mpn, vendor="ultralibrarian", *, http_fetcher=None):
    mpn = (mpn or "").strip()
    if not mpn:
        return None
    vendor = (vendor or "ultralibrarian").strip().lower()
    search = _search_url(vendor, mpn)
    if search is None:
        return None
    url = search
    if http_fetcher is not None and vendor == _SNAPEDA:
        upgraded = _snapeda_direct_page(search, http_fetcher)
        if upgraded is not None:
            url = upgraded
    return AssetPage(url=url, vendor=_label(vendor), needs_login=True)


def _snapeda_direct_page(search_url: str, http_fetcher) -> str | None:
    try:
        result = http_fetcher.get(search_url)
    except EnrichError:
        return None
    html = getattr(result, "text", "") or ""
    m = _SNAPEDA_PART_RE.search(html)
    return "https://www.snapeda.com" + m.group(1) if m else None
