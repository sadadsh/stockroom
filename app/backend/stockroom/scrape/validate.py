"""The no-bad-data gate (spec section 7). Each rule is conservative: a value that fails
is DROPPED (left None / removed), never coerced or guessed, so garbage never lands on a
record. A package or spec that is merely unrecognized is kept as plain text (the schema
is source-agnostic; an honest blank beats a wrong guess). Never raises."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from stockroom.enrich.schema import EnrichmentResult, PriceBreak

_MPN_RE = re.compile(r"^[A-Za-z0-9 ._/+#-]{1,64}$")


def is_pdf_bytes(b: bytes) -> bool:
    return bytes(b[:5]) == b"%PDF-"


def valid_mpn(s: str) -> bool:
    return bool(_MPN_RE.match(s or ""))


def valid_url(s: str) -> bool:
    try:
        parts = urlsplit((s or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def valid_stock(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and n >= 0


def sane_price_breaks(breaks: list[PriceBreak]) -> list[PriceBreak]:
    """Positive qty + price, sorted ascending by qty, unit price non-increasing. A break
    that would raise the per-unit price at a higher quantity is an extraction anomaly and
    is dropped, so the ladder the BOM layer reads is always monotonic."""
    clean = [b for b in breaks if isinstance(b.qty, int) and b.qty > 0 and b.price > 0]
    clean.sort(key=lambda b: b.qty)
    out: list[PriceBreak] = []
    last_price: float | None = None
    for b in clean:
        if last_price is None or b.price <= last_price + 1e-9:
            out.append(b)
            last_price = b.price
    return out


def validate_product(result: EnrichmentResult) -> EnrichmentResult:
    """Drop every field that fails its rule (in place) and return the same result: a
    bad-charset MPN, a negative/non-int stock, and a malformed datasheet/product URL are
    cleared; the price ladder is sanitized to a monotonic positive one. Package,
    description, and specs are kept as plain text (never guessed, never dropped for being
    unrecognized). Never raises."""
    if result.mpn is not None and not valid_mpn(str(result.mpn.value)):
        result.mpn = None
    if result.stock is not None and not valid_stock(result.stock.value):
        result.stock = None
    if result.datasheet_url is not None and not valid_url(str(result.datasheet_url.value)):
        result.datasheet_url = None
    if result.product_url is not None and not valid_url(str(result.product_url.value)):
        result.product_url = None
    result.price_breaks = sane_price_breaks(result.price_breaks)
    return result
