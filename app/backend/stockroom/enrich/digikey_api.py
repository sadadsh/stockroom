"""OPTIONAL DigiKey Product Information API v4 adapter, OFF by default and opt-in only.

Mirrors enrich/mouser.py: with no credentials the adapter is disabled and makes no network
call. When the user supplies OAuth2 client-credentials it becomes one more source, resolving an
MPN to the canonical EnrichmentResult. Extracted Qt-free from the owner's legacy
LibraryManager.py (_parse_digikey_part / _digikey_token / _digikey_request); nothing is imported
from that repo. Never raises: any auth/network/parse failure yields an empty result so the
registry falls through cleanly."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.schema import (
    EnrichmentResult,
    PriceBreak,
    Sourced,
    normalize_lifecycle,
    normalize_mpn,
)


def _default_requester(*a, **k):
    """Temporary stub; Task 3 will replace with the real implementation."""
    return None


def _coerce_price(raw) -> float | None:
    """A price may be a number or a currency string ('$0.12'); pull the first numeric run."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace(",", ".")
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _obj_str(v, *keys: str) -> str:
    """A v4 field that may be a nested object OR a bare string -> a clean string. For an object,
    the first present key wins; a non-str/dict is dropped."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for k in keys:
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _pick_variation(variations) -> dict:
    """The first usable ProductVariation (carries the DigiKey P/N + StandardPricing)."""
    if isinstance(variations, list):
        for v in variations:
            if isinstance(v, dict):
                return v
    return {}


def _parse_digikey_part(product: dict) -> EnrichmentResult:
    r = EnrichmentResult()
    if not isinstance(product, dict):
        return r
    mpn = _obj_str(product.get("ManufacturerProductNumber"))
    if mpn:
        r.mpn = Sourced(mpn, "digikey", "high")
    man = _obj_str(product.get("Manufacturer"), "Name")
    if man:
        r.manufacturer = Sourced(man, "digikey", "high")
    desc = _obj_str(product.get("Description"), "ProductDescription", "DetailedDescription")
    if desc:
        r.description = Sourced(desc, "digikey", "high")
    ds = _obj_str(product.get("DatasheetUrl"))
    if ds:
        r.datasheet_url = Sourced(ds, "digikey", "high")
    status = _obj_str(product.get("ProductStatus"), "Status")
    if status:
        r.lifecycle = Sourced(normalize_lifecycle(status), "digikey", "high")
    try:
        stock = int(product.get("QuantityAvailable") or 0)
    except (TypeError, ValueError):
        stock = 0
    if stock:
        r.stock = Sourced(stock, "digikey", "high")
    lead = _obj_str(product.get("ManufacturerLeadWeeks"))
    if lead:
        r.lead_time = Sourced(lead, "digikey", "high")
    url = _obj_str(product.get("ProductUrl"))
    if url:
        r.product_url = Sourced(url, "digikey", "high")
    var = _pick_variation(product.get("ProductVariations"))
    dk_pn = _obj_str(var.get("DigiKeyProductNumber"))
    if dk_pn:
        r.dist_pns["digikey"] = dk_pn
    classifications = product.get("Classifications")
    rohs = _obj_str(classifications, "RohsStatus") if isinstance(classifications, dict) else ""
    if rohs:
        r.specs["RoHS"] = Sourced(rohs, "digikey", "high")
    breaks: list[PriceBreak] = []
    pricing = var.get("StandardPricing")
    for b in pricing if isinstance(pricing, list) else []:
        if not isinstance(b, dict):
            continue
        price = _coerce_price(b.get("UnitPrice"))
        try:
            qty = int(b.get("BreakQuantity"))
        except (TypeError, ValueError):
            continue
        if price is not None:
            breaks.append(PriceBreak(qty=qty, price=price))
    breaks.sort(key=lambda x: x.qty)
    if breaks:
        r.price_breaks = breaks
    return r


class DigiKeyAdapter:
    def __init__(self, client_id: str = "", client_secret: str = "", requester=None):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self._requester = requester or (
            _default_requester(self.client_id, self.client_secret) if self.enabled else None
        )

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def lookup(self, mpn: str) -> EnrichmentResult:
        if not self.enabled or not mpn or self._requester is None:
            return EnrichmentResult()
        try:
            body = self._requester(mpn)
        except EnrichError:
            return EnrichmentResult()  # a failed API call must not break enrichment
        products = (body or {}).get("Products") or []
        if not products:
            return EnrichmentResult()
        target = normalize_mpn(mpn)
        exact = next(
            (p for p in products
             if normalize_mpn(_obj_str(p.get("ManufacturerProductNumber")) or "") == target),
            None,
        )
        chosen = exact if exact is not None else products[0]
        result = _parse_digikey_part(chosen)
        if exact is None and result.mpn is not None:
            result.mpn = Sourced(result.mpn.value, "digikey", "low")  # flag for manual review
        return result
