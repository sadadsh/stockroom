"""OPTIONAL Mouser Search API adapter, OFF by default and opt-in only.

Enrichment is scrape-first and does NOT depend on this (spec section 6.1 item 4):
with no key the adapter is disabled and makes no network call, so a disabled or
capped Mouser never breaks anything. When the user opts in (MachineConfig already
carries a mouser_api_key), it is ONE MORE source in the registry.

The parse and the exact-MPN pick are re-implemented Qt-free from the owner's own
legacy client (legacy/tools/LibraryManager.py: _parse_mouser_part, _mouser_request,
make_mouser_lookup). Nothing is imported from legacy/ (backend imports zero PyQt).
The legacy config-file rate-limit bookkeeping is dropped; Stockroom paces with the
sliding-window limiter (ratelimit.py) instead."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from stockroom.enrich.errors import EnrichError, status_from_error
from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced, normalize_mpn


def _coerce_price(raw) -> float | None:
    """A Mouser price is a currency string like '$1.23' or '1,23 EUR'. Pull the
    first numeric run (extracted from the legacy _coerce_price)."""
    if raw is None:
        return None
    s = str(raw).replace(",", ".")
    digits = "".join(c for c in s if c.isdigit() or c == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


_COMPLIANCE_LABELS = {
    "USHTS": "HTS Code (US)", "CNHTS": "HTS Code (CN)", "CAHTS": "HTS Code (CA)",
    "JPHTS": "HTS Code (JP)", "MXHTS": "HTS Code (MX)", "TARIC": "HTS Code (EU TARIC)",
    "ECCN": "ECCN",
}


def _capture_everything(p: dict, r: EnrichmentResult) -> None:
    """Fold the full field set the search API returns (parametric attributes, the distributor
    category, compliance + trade origin, the product image, order quantities) into the spec bag.
    Previously dropped; the owner's "use literally everything the token gives us". Each row is
    setdefault so a real value already on the result (e.g. a datasheet leg's) is never clobbered."""
    cat = (p.get("Category") or "").strip()
    if cat:
        r.specs.setdefault("Product Category", Sourced(cat, "mouser", "high"))
    # ProductAttributes repeat a name once per option (Packaging: Reel / Cut Tape / MouseReel),
    # so group by name and join the distinct values into one spec row.
    attrs: dict[str, list[str]] = {}
    for a in p.get("ProductAttributes") or []:
        if not isinstance(a, dict):
            continue
        name = (a.get("AttributeName") or "").strip()
        val = (a.get("AttributeValue") or "").strip()
        if name and val and val not in attrs.setdefault(name, []):
            attrs[name].append(val)
    for name, vals in attrs.items():
        r.specs.setdefault(name, Sourced(", ".join(vals), "mouser", "high"))
    rohs = (p.get("ROHSStatus") or "").strip()
    if rohs:
        r.specs.setdefault("RoHS", Sourced(rohs, "mouser", "high"))
    image = (p.get("ImagePath") or "").strip()
    if image:
        r.specs.setdefault("Image", Sourced(image, "mouser", "medium"))
    for src_key, label in (("Min", "Minimum Order Quantity"), ("Mult", "Order Multiple"),
                           ("SalesMaximumOrderQty", "Maximum Order Quantity")):
        raw = p.get(src_key)
        val = str(raw).strip() if raw not in (None, "") else ""
        if val:
            r.specs.setdefault(label, Sourced(val, "mouser", "medium"))
    weight = p.get("UnitWeightKg")
    unit_weight = weight.get("UnitWeight") if isinstance(weight, dict) else None
    if isinstance(unit_weight, (int, float)) and unit_weight > 0:
        r.specs.setdefault("Unit Weight (kg)", Sourced(str(unit_weight), "mouser", "medium"))
    # Export/trade compliance: HTS codes + ECCN under readable labels.
    for c in p.get("ProductCompliance") or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("ComplianceName") or "").strip()
        val = (c.get("ComplianceValue") or "").strip()
        if name and val:
            r.specs.setdefault(_COMPLIANCE_LABELS.get(name, name), Sourced(val, "mouser", "high"))
    # Trade origin: kept as specs, and the manufacturing origin promoted to the canonical field.
    for c in p.get("TradeCompliance") or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("ComplianceName") or "").strip()
        val = (c.get("ComplianceValue") or "").strip()
        if not (name and val):
            continue
        r.specs.setdefault(name, Sourced(val, "mouser", "high"))
        if name == "Country of Origin" and r.country_of_origin is None:
            r.country_of_origin = Sourced(val, "mouser", "high")


def _parse_mouser_part(p: dict) -> EnrichmentResult:
    """One Mouser API part -> the canonical schema (legacy _parse_mouser_part,
    remapped onto EnrichmentResult; a distributor API is high confidence)."""
    r = EnrichmentResult()
    mpn = (p.get("ManufacturerPartNumber") or "").strip()
    if mpn:
        r.mpn = Sourced(mpn, "mouser", "high")
    man = (p.get("Manufacturer") or "").strip()
    if man:
        r.manufacturer = Sourced(man, "mouser", "high")
    desc = (p.get("Description") or "").strip()
    if desc:
        r.description = Sourced(desc, "mouser", "high")
    ds = (p.get("DataSheetUrl") or "").strip()
    if ds:
        r.datasheet_url = Sourced(ds, "mouser", "high")
    try:
        stock = int(p.get("AvailabilityInStock") or 0)
    except (TypeError, ValueError):
        stock = 0
    if stock:
        r.stock = Sourced(stock, "mouser", "high")
    # M7d procurement fields the BOM cost/sourcing layer consumes. Each is emitted only
    # when Mouser actually returned it, so an absent value stays None (honest unknown,
    # not a fabricated status/lead).
    lifecycle = (p.get("LifecycleStatus") or "").strip()
    if lifecycle:
        r.lifecycle = Sourced(lifecycle, "mouser", "high")
    lead = (p.get("LeadTime") or "").strip()
    if lead:
        r.lead_time = Sourced(lead, "mouser", "high")
    url = (p.get("ProductDetailUrl") or "").strip()
    if url:
        r.product_url = Sourced(url, "mouser", "high")
    mouser_pn = (p.get("MouserPartNumber") or "").strip()
    if mouser_pn:
        r.dist_pns["mouser"] = mouser_pn
    breaks: list[PriceBreak] = []
    for b in p.get("PriceBreaks") or []:
        qty, price = b.get("Quantity"), _coerce_price(b.get("Price"))
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            continue
        if price is not None:
            breaks.append(PriceBreak(qty=qty, price=price))
    breaks.sort(key=lambda x: x.qty)
    if breaks:
        r.price_breaks = breaks
    _capture_everything(p, r)
    return r


def _default_requester(api_key: str, timeout: int = 8):
    """POST to the Mouser partnumber endpoint and return the parsed JSON body, or
    raise EnrichError (extracted Qt-free from legacy _mouser_request; the caller
    treats any failure as "no result", so the registry falls through cleanly)."""

    def request(mpn: str) -> dict:
        payload = {"SearchByPartRequest": {"mouserPartNumber": mpn, "partSearchOptions": "Exact"}}
        req = urllib.request.Request(
            f"https://api.mouser.com/api/v1/search/partnumber?apiKey={api_key}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            # a 429/401/403 carries .code: the rescan breaker reads it via status_code
            raise EnrichError(f"mouser request failed: {exc}", status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EnrichError(f"mouser request failed: {exc}") from exc

    return request


class MouserAdapter:
    def __init__(self, api_key: str = "", requester=None):
        self.api_key = api_key or ""
        self._requester = requester or (
            _default_requester(self.api_key) if self.api_key else None
        )
        # out-of-band signal for the rescan circuit breaker (Phase-1b-2b); never affects the
        # returned EnrichmentResult, which stays exactly what it is today on every path.
        self.last_status: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def lookup(self, mpn: str) -> EnrichmentResult:
        if not self.enabled or not mpn or self._requester is None:
            return EnrichmentResult()
        try:
            body = self._requester(mpn)
        except EnrichError as exc:
            self.last_status = status_from_error(exc)
            return EnrichmentResult()  # a failed API call must not break enrichment
        parts = ((body or {}).get("SearchResults") or {}).get("Parts") or []
        if not parts:
            self.last_status = "not_found"
            return EnrichmentResult()
        target = normalize_mpn(mpn)
        exact = next(
            (p for p in parts if normalize_mpn(p.get("ManufacturerPartNumber") or "") == target),
            None,
        )
        chosen = exact if exact is not None else parts[0]
        result = _parse_mouser_part(chosen)
        if exact is None and result.mpn is not None:
            # no exact match: downgrade confidence so a manual review flags it
            result.mpn = Sourced(result.mpn.value, "mouser", "low")
        self.last_status = "ok"
        return result
