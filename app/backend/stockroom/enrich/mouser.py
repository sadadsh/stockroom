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

import html
import json
import re
import urllib.error
import urllib.request

from stockroom.enrich.errors import EnrichError, status_from_error
from stockroom.enrich.schema import EnrichmentResult, PriceBreak, Sourced, normalize_mpn


def _catalogue_code(mouser_part_number: str) -> str:
    """The manufacturer code from a Mouser stock number ("595-TPS2121RUXR" -> "595").

    Returns "" when the stock number is absent or is not in that shape, and the caller then
    strips NOTHING -- an unknown code must never be guessed at, because the whole point of
    keying on it is that a token starting with it IS a Mouser catalogue number.
    """
    code, sep, rest = (mouser_part_number or "").strip().partition("-")
    return code if sep and rest and code.isdigit() else ""


def _is_catalogue_tail(joined: str, code: str) -> bool:
    """True when `joined` (the candidate tail, its whitespace already removed) is nothing but
    Mouser's own alternate-packaging annotation: bare "A" markers, each optionally followed by
    this part's Mouser stock number or a truncated prefix of it.

    Whitespace is removed by the caller rather than tolerated here because Mouser inserts spaces
    INSIDE the numbers it appends ("59 5-TPD1E10B06DPYT", "595- DRV2605LDGST", "595 -SN74..."),
    so the only reliable form of the token is the one with the spacing taken back out.
    """
    partials = [re.escape(code) + r"-[A-Z0-9]*"] + [
        re.escape(code[:k]) for k in range(len(code), 0, -1)
    ]
    group = "A(?:" + "|".join(partials) + ")?"
    if not re.fullmatch(f"(?:{group})+", joined):
        return False
    # A run of bare markers is NOT a catalogue tail. Requiring at least one real, non-empty
    # stock number is what stops a description that legitimately ends in "A" (an amp rating)
    # from being cut, which would be a worse defect than the noise this removes.
    return re.search(re.escape(code) + r"-[A-Z0-9]", joined) is not None


def clean_mouser_description(description: str, mouser_part_number: str) -> str:
    """Mouser's `Description`, as a person should read it.

    Two defects, both measured on the owner's real library (2026-07-27, 158 parts):

    1. **The catalogue tail.** Mouser appends its alternate-packaging stock numbers to the
       description behind a bare "A" marker, so 13 of 158 parts derived a description ending
       "... Vltg Det A A 595-TPS3700DDCR". It is cut at the FIRST marker whose remainder is
       entirely catalogue numbers, and the cut is driven by the payload's OWN stock number
       rather than by a guess at what a part number looks like.
    2. **HTML entities.** `2.7-V&nbsp;to 22-V` is served raw. Unescaping alone is not enough:
       `&nbsp;` decodes to U+00A0, which is not a space to anything that measures or wraps
       text, so every whitespace run is normalized to a single space.

    The complete decoded JSON payload is untouched by all of this under `sourced/`, which makes
    cleaning at DERIVE time safe rather than lossy.
    """
    text = re.sub(r"\s+", " ", html.unescape(description or "")).strip()
    code = _catalogue_code(mouser_part_number)
    if not code:
        return text
    words = text.split(" ")
    for i in range(1, len(words)):
        if words[i] != "A":
            continue
        if _is_catalogue_tail("".join(words[i:]), code):
            return " ".join(words[:i])
    return text


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
    desc = clean_mouser_description(p.get("Description") or "", p.get("MouserPartNumber") or "")
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


def _mouser_catalog_offers(parts: list, mpn: str) -> list[dict]:
    """Every exact Mouser catalogue row and its complete quantity ladder."""
    target = normalize_mpn(mpn)
    offers: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if normalize_mpn(part.get("ManufacturerPartNumber") or "") != target:
            continue
        breaks: list[dict] = []
        for item in part.get("PriceBreaks") or []:
            if not isinstance(item, dict):
                continue
            price = _coerce_price(item.get("Price"))
            try:
                quantity = int(item.get("Quantity") or 0)
            except (TypeError, ValueError):
                continue
            if price is not None and quantity > 0:
                breaks.append(
                    {
                        "qty": quantity,
                        "price": price,
                        "currency": str(item.get("Currency") or "USD"),
                    }
                )
        breaks.sort(key=lambda item: item["qty"])
        offers.append(
            {
                "product_number": str(part.get("MouserPartNumber") or "").strip(),
                "stock": part.get("AvailabilityInStock"),
                "product_url": str(part.get("ProductDetailUrl") or "").strip(),
                "price_breaks": breaks,
            }
        )
    return offers


def parse_mouser_payload(body: dict | None, mpn: str) -> EnrichmentResult:
    """The WHOLE Mouser response -> one EnrichmentResult, with no network and no credentials.

    Extracted from `MouserAdapter.lookup` (not copied from it: `lookup` calls this) so a RE-DERIVE
    can rebuild a part from `sourced/<id>/mouser.json` on a fresh clone with no API key. That is
    the point of storing the raw payload at all - "import everything so we can change the way the
    data's manipulated later" only works if the manipulation can run again without the vendor.

    It takes the FULL response body rather than the already-chosen part, so the SELECTION is
    re-derivable too: which of several returned parts matched is a derivation decision, and
    freezing it at import time would mean a later fix to the matcher could never reach the parts
    already imported.
    """
    parts = ((body or {}).get("SearchResults") or {}).get("Parts") or []
    if not parts:
        return EnrichmentResult()
    target = normalize_mpn(mpn)
    # The query may be a MANUFACTURER part number or a MOUSER STOCK NUMBER - the endpoint
    # accepts both (`mouserPartNumber`, options "Exact"), and a sourcing document written
    # against Mouser names parts the second way. Checking only the manufacturer field made
    # every stock-number query a non-match, so the adapter silently fell through to
    # parts[0]: a DIFFERENT part, returned as the answer with a `low` label nobody reads.
    exact = next(
        (p for p in parts
         if isinstance(p, dict)
         and target in {normalize_mpn(p.get("ManufacturerPartNumber") or ""),
                        normalize_mpn(p.get("MouserPartNumber") or "")}),
        None,
    )
    chosen = exact if exact is not None else parts[0]
    if not isinstance(chosen, dict):
        return EnrichmentResult()
    result = _parse_mouser_part(chosen)
    catalog_offers = _mouser_catalog_offers(parts, mpn)
    if catalog_offers:
        result.catalog["mouser"] = {"schema_version": 1, "offers": catalog_offers}
    if exact is None and result.mpn is not None:
        # no exact match: downgrade confidence so a manual review flags it
        result.mpn = Sourced(result.mpn.value, "mouser", "low")
    return result


def validate_api_key(api_key: str, *, probe_mpn: str = "NE555P") -> str:
    """Validate one person-supplied key without retaining payload or credential material."""

    adapter = MouserAdapter(api_key)
    adapter.lookup(probe_mpn)
    return adapter.last_status or "network_error"


class MouserAdapter:
    def __init__(self, api_key: str = "", requester=None):
        self.api_key = api_key or ""
        self._requester = requester or (
            _default_requester(self.api_key) if self.api_key else None
        )
        # out-of-band signal for the rescan circuit breaker (Phase-1b-2b); never affects the
        # returned EnrichmentResult, which stays exactly what it is today on every path.
        self.last_status: str = ""
        self.last_payload: dict | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def fetch_payload(self, mpn: str) -> dict | None:
        """The complete decoded response JSON, for lossless storage under `sourced/`.

        `lookup` parses and discards the body; an IMPORT has to keep it, because the whole point of
        the sourced layer is that the derivation can be re-run later against what the vendor
        actually said. Returns None when the call could not be made or failed - a failed fetch is
        "no evidence from this source", never an empty payload written over a good one.
        """
        if not self.enabled or not mpn or self._requester is None:
            return None
        try:
            body = self._requester(mpn)
        except EnrichError as exc:
            self.last_status = status_from_error(exc)
            return None
        if not isinstance(body, dict):
            self.last_status = "not_found"
            return None
        # FIXED 2026-07-27 (cold-eyes finding 1): a genuine "no such part" answer from Mouser is
        # HTTP 200 with an EMPTY Parts list - a truthy dict - so `"ok" if body else "not_found"`
        # reported EVERY not-found lookup as a hit. Measured: a fabricated MPN
        # ("ZZZNOTAREALPART123") was indistinguishable from a real one, the importer wrote it as
        # evidence, indexed it in `sources`, and counted it `imported`. The sibling `lookup()`
        # already gets this right (`"ok" if result.filled_fields() else "not_found"`); this now
        # matches it by parsing the same way, rather than trusting an HTTP-level truthiness check.
        found = parse_mouser_payload(body, mpn).filled_fields()
        self.last_status = "ok" if found else "not_found"
        # A genuine not-found must return None, same as a failed call: there is no evidence here,
        # and storing an empty-results response under sourced/ would look like a successful import
        # of nothing, forever.
        return body if found else None

    def lookup(self, mpn: str) -> EnrichmentResult:
        self.last_payload = None
        if not self.enabled or not mpn or self._requester is None:
            return EnrichmentResult()
        try:
            body = self._requester(mpn)
        except EnrichError as exc:
            self.last_status = status_from_error(exc)
            return EnrichmentResult()  # a failed API call must not break enrichment
        result = parse_mouser_payload(body, mpn)
        self.last_status = "ok" if result.filled_fields() else "not_found"
        if self.last_status == "ok" and isinstance(body, dict):
            self.last_payload = body
        return result
