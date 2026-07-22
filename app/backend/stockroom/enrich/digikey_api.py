"""OPTIONAL DigiKey Product Information API v4 adapter, OFF by default and opt-in only.

Mirrors enrich/mouser.py: with no credentials the adapter is disabled and makes no network
call. When the user supplies OAuth2 client-credentials it becomes one more source, resolving an
MPN to the canonical EnrichmentResult. Extracted Qt-free from the owner's legacy
LibraryManager.py (_parse_digikey_part / _digikey_token / _digikey_request); nothing is imported
from that repo. Never raises: any auth/network/parse failure yields an empty result so the
registry falls through cleanly."""
from __future__ import annotations

import json
import time as _time
import urllib.error
import urllib.parse
import urllib.request

from stockroom.enrich.errors import EnrichError, status_from_error
from stockroom.enrich.schema import (
    EnrichmentResult,
    PriceBreak,
    Sourced,
    normalize_lifecycle,
    normalize_mpn,
)


def _fetch_token(client_id: str, client_secret: str, timeout: float) -> str | None:
    """OAuth2 client-credentials bearer token, or None on a non-HTTP transport failure (the
    caller treats a missing token as a failed lookup). An HTTP error status at the token
    endpoint (401/403 bad credential, 429 throttled) instead raises EnrichError carrying that
    status_code, so a bad/expired DigiKey credential surfaces to DigiKeyAdapter.lookup as
    auth_error/rate_limited (via status_from_error) - the same breaker signal a failed product
    search gives - rather than degrading to a generic, breaker-invisible failure."""
    if not (client_id and client_secret):
        return None
    body = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret,
                                   "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request("https://api.digikey.com/v1/oauth2/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            parsed = json.loads(r.read().decode())
        return parsed.get("access_token") if isinstance(parsed, dict) else None
    except urllib.error.HTTPError as exc:
        raise EnrichError(f"digikey token request failed: {exc}", status_code=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def _default_requester(client_id: str, client_secret: str, timeout: float = 8):
    """A requester(mpn) -> v4 body dict. One OAuth2 bearer token is cached across every call on
    this closure (DigiKey tokens live ~30 min; a 25-min TTL leaves margin), so a bulk rescan does
    not re-auth per part. Raises EnrichError on any auth/transport failure."""
    tok = {"token": None, "exp": 0.0}
    TTL = 1500.0

    def _cached_token() -> str | None:
        now = _time.monotonic()
        if tok["token"] and now < tok["exp"]:
            return tok["token"]
        t = _fetch_token(client_id, client_secret, timeout)
        if t:  # cache successes only, so a refused token is retried next call
            tok["token"], tok["exp"] = t, now + TTL
        return t

    def request(mpn: str) -> dict:
        token = _cached_token()
        if not token:
            raise EnrichError("digikey: no OAuth token (bad creds or throttled)")
        req = urllib.request.Request(
            "https://api.digikey.com/products/v4/search/keyword",
            data=json.dumps({"Keywords": str(mpn).strip(), "Limit": 10, "Offset": 0}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}",
                     "X-DIGIKEY-Client-Id": client_id})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            # a 429/401/403 carries .code: the rescan breaker reads it via status_code
            raise EnrichError(f"digikey request failed: {exc}", status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise EnrichError(f"digikey request failed: {exc}") from exc

    return request


_CLASSIFICATION_LABELS = {
    "RohsStatus": "RoHS", "ReachStatus": "REACH",
    "MoistureSensitivityLevel": "Moisture Sensitivity Level",
    "ExportControlClassNumber": "ECCN", "HtsusCode": "HTS Code (US)",
}


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
    the first non-empty key wins; a non-str/dict is dropped."""
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
    # The full field set the token returns (previously only RoHS was kept): the parametric table,
    # the product image, the leaf category, the series, and the whole compliance block. The owner's
    # "use literally everything the token gives us". Each is setdefault so a higher-priority source
    # already on the result is never clobbered.
    classifications = product.get("Classifications")
    if isinstance(classifications, dict):
        for src_key, label in _CLASSIFICATION_LABELS.items():
            val = classifications.get(src_key)
            if isinstance(val, str) and val.strip():
                r.specs.setdefault(label, Sourced(val.strip(), "digikey", "high"))
    # The parametric table: the real electrical specs. A "-" ValueText is DigiKey's empty
    # placeholder and is skipped (an honest gap, never a fabricated value).
    for prm in product.get("Parameters") or []:
        if not isinstance(prm, dict):
            continue
        label = _obj_str(prm.get("ParameterText"))
        val = _obj_str(prm.get("ValueText"))
        if label and val and val != "-":
            r.specs.setdefault(label, Sourced(val, "digikey", "high"))
    photo = _obj_str(product.get("PhotoUrl"))
    if photo:
        r.specs.setdefault("Image", Sourced(photo, "digikey", "medium"))
    cat_name = _obj_str(product.get("Category"), "Name")
    if cat_name and cat_name != "-":
        r.specs.setdefault("Product Category", Sourced(cat_name, "digikey", "high"))
    series_name = _obj_str(product.get("Series"), "Name")
    if series_name and series_name != "-":
        r.specs.setdefault("Series", Sourced(series_name, "digikey", "high"))
    pkg_type = _obj_str(var.get("PackageType"), "Name")
    if pkg_type:
        r.specs.setdefault("Package Type", Sourced(pkg_type, "digikey", "medium"))
    moq = var.get("MinimumOrderQuantity")
    if isinstance(moq, int) and moq > 0:
        r.specs.setdefault("Minimum Order Quantity", Sourced(str(moq), "digikey", "medium"))
    std_pkg = var.get("StandardPackage")
    if isinstance(std_pkg, int) and std_pkg > 0:
        r.specs.setdefault("Standard Package", Sourced(str(std_pkg), "digikey", "medium"))
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
        # out-of-band signal for the rescan circuit breaker (Phase-1b-2b); never affects the
        # returned EnrichmentResult, which stays exactly what it is today on every path.
        self.last_status: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def lookup(self, mpn: str) -> EnrichmentResult:
        if not self.enabled or not mpn or self._requester is None:
            return EnrichmentResult()
        try:
            body = self._requester(mpn)
        except EnrichError as exc:
            self.last_status = status_from_error(exc)
            return EnrichmentResult()  # a failed API call must not break enrichment
        products = (body or {}).get("Products") or []
        if not products:
            self.last_status = "not_found"
            return EnrichmentResult()
        target = normalize_mpn(mpn)
        exact = next(
            (p for p in products
             if isinstance(p, dict)
             and normalize_mpn(_obj_str(p.get("ManufacturerProductNumber")) or "") == target),
            None,
        )
        chosen = exact if exact is not None else products[0]
        result = _parse_digikey_part(chosen)
        if exact is None and result.mpn is not None:
            result.mpn = Sourced(result.mpn.value, "digikey", "low")  # flag for manual review
        self.last_status = "ok"
        return result
