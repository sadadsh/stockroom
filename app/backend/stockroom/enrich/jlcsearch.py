"""A Qt-free client for the free, no-key jlcsearch community API.

jlcsearch (jlcsearch.tscircuit.com) is a community mirror of JLCPCB's parts
catalogue exposed as a keyless JSON search endpoint. It is the same catalogue the
LCSC/JLCPCB skills use, so a resistor/capacitor/IC MPN resolves to an LCSC part
number, its JLC package, live stock, tiered price breaks, and the basic/preferred
assembly flags without any distributor API key.

This client is a thin, honest reader over that endpoint: it fetches through the
shared HttpFetcher seam (so a stub can serve a saved fixture in tests and the real
curl_cffi impl runs in production), parses the response defensively, and returns a
single best JlcHit (or None when the catalogue has no match). A transport failure or
an unparseable response raises EnrichError, never a silent empty result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import quote

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.fetch import HttpFetcher
from stockroom.enrich.schema import PriceBreak

_BASE_URL = "https://jlcsearch.tscircuit.com/components/list.json"


@dataclass
class JlcHit:
    mpn: str
    lcsc: str
    package: str
    stock: int
    price_breaks: list[PriceBreak] = field(default_factory=list)
    is_basic: bool = False
    is_preferred: bool = False
    category: str = ""
    subcategory: str = ""


def _parse_price_breaks(raw: object) -> list[PriceBreak]:
    """Parse the API's stringified price ladder into sorted PriceBreaks.

    The 'price' field is a JSON string like
    '[{"qFrom": 20, "qTo": 19980, "price": 0.000485714}, ...]'. A missing, empty,
    or malformed string (or a row missing qFrom/price) yields an empty list, so a
    catalogue row without pricing degrades to "no price" rather than crashing or
    inventing a break.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        ladder = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(ladder, list):
        return []
    breaks: list[PriceBreak] = []
    for entry in ladder:
        if not isinstance(entry, dict):
            continue
        if "qFrom" not in entry or "price" not in entry:
            continue
        try:
            qty = int(entry["qFrom"])
            price = float(entry["price"])
        except (TypeError, ValueError):
            continue
        breaks.append(PriceBreak(qty=qty, price=price, currency="USD"))
    breaks.sort(key=lambda b: b.qty)
    return breaks


def _rank_key(row: dict) -> tuple[int, int, int]:
    # is_preferred first, then is_basic, then stock; all descending, so a plain
    # max() over this key picks the best row.
    return (
        1 if row.get("is_preferred") else 0,
        1 if row.get("is_basic") else 0,
        int(row.get("stock") or 0),
    )


class JlcSearchClient:
    def __init__(self, http_fetcher=None):
        self._http = http_fetcher or HttpFetcher()

    def search(self, mpn: str) -> JlcHit | None:
        url = f"{_BASE_URL}?search={quote(mpn, safe='')}"
        result = self._http.get(url)  # raises EnrichError on transport failure
        try:
            payload = json.loads(result.text)
        except (ValueError, TypeError) as exc:
            raise EnrichError(f"jlcsearch returned unparseable JSON for {mpn!r}: {exc}") from exc

        components = payload.get("components") if isinstance(payload, dict) else None
        if not components or not isinstance(components, list):
            return None

        in_stock = [c for c in components if isinstance(c, dict) and int(c.get("stock") or 0) > 0]
        pool = in_stock or [c for c in components if isinstance(c, dict)]
        if not pool:
            return None

        row = max(pool, key=_rank_key)
        return JlcHit(
            mpn=str(row.get("mfr", "")),
            lcsc=f"C{row.get('lcsc', '')}",
            package=str(row.get("package", "")),
            stock=int(row.get("stock") or 0),
            price_breaks=_parse_price_breaks(row.get("price")),
            is_basic=bool(row.get("is_basic")),
            is_preferred=bool(row.get("is_preferred")),
            category=str(row.get("category", "")),
            subcategory=str(row.get("subcategory", "")),
        )
