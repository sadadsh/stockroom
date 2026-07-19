"""Resolve a part's DigiKey product-detail page from its MPN - the page that hosts the Ultra
Librarian / SnapEDA CAD download the owner clicks. The DigiKey v4 API reliably returns a
ProductUrl (enrich/digikey_api.py); no CAD-model URL is exposed by the API, so we open the
product page and let the owner take the one-click download there."""
from __future__ import annotations


def resolve_digikey_cad_source(mpn: str, adapter) -> str | None:
    if not mpn or not getattr(adapter, "enabled", False):
        return None
    result = adapter.lookup(mpn)
    product = getattr(result, "product_url", None)
    return product.value if (product is not None and product.value) else None
