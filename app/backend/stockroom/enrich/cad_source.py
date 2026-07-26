"""Resolve the DigiKey page a part opens for its CAD download. When the DigiKey v4 API resolves
an exact ProductUrl (enrich/digikey_api.py) we open that product-detail page, which hosts the
SnapEDA / Ultra Librarian / SamacSys CAD downloads the owner clicks. When no product page is
available - no creds, a disabled or absent adapter, or an API miss - we fall back to a DigiKey
keyword-search URL so a part with a real mpn ALWAYS opens a real DigiKey page. Only a blank mpn
resolves to None. The mpn is URL-encoded so an odd part number cannot alter the query string."""
from __future__ import annotations

from urllib.parse import quote_plus


def resolve_digikey_cad_source(mpn: str, adapter) -> str | None:
    if not mpn:
        return None
    if getattr(adapter, "enabled", False):
        result = adapter.lookup(mpn)
        product = getattr(result, "product_url", None)
        if product is not None and product.value:
            return product.value
    return f"https://www.digikey.com/en/products/result?keywords={quote_plus(mpn)}"
