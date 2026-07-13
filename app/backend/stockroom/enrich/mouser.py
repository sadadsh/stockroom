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

from stockroom.enrich.errors import EnrichError
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
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EnrichError(f"mouser request failed: {exc}") from exc

    return request


class MouserAdapter:
    def __init__(self, api_key: str = "", requester=None):
        self.api_key = api_key or ""
        self._requester = requester or (
            _default_requester(self.api_key) if self.api_key else None
        )

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def lookup(self, mpn: str) -> EnrichmentResult:
        if not self.enabled or not mpn or self._requester is None:
            return EnrichmentResult()
        try:
            body = self._requester(mpn)
        except EnrichError:
            return EnrichmentResult()  # a failed API call must not break enrichment
        parts = ((body or {}).get("SearchResults") or {}).get("Parts") or []
        if not parts:
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
        return result
