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
from collections.abc import Iterable

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
    body = urllib.parse.urlencode(
        {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    ).encode()
    req = urllib.request.Request(
        "https://api.digikey.com/v1/oauth2/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
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
    token: str | None = None
    expires_at = 0.0
    TTL = 1500.0

    def _cached_token() -> str | None:
        nonlocal expires_at, token
        now = _time.monotonic()
        if token and now < expires_at:
            return token
        t = _fetch_token(client_id, client_secret, timeout)
        if t:  # cache successes only, so a refused token is retried next call
            token, expires_at = t, now + TTL
        return t

    def request(mpn: str) -> dict:
        token = _cached_token()
        if not token:
            raise EnrichError("digikey: no OAuth token (bad creds or throttled)")
        req = urllib.request.Request(
            "https://api.digikey.com/products/v4/search/keyword",
            data=json.dumps({"Keywords": str(mpn).strip(), "Limit": 10, "Offset": 0}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-DIGIKEY-Client-Id": client_id,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            # a 429/401/403 carries .code: the rescan breaker reads it via status_code
            raise EnrichError(f"digikey request failed: {exc}", status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise EnrichError(f"digikey request failed: {exc}") from exc

    return request


def validate_credentials(client_id: str, client_secret: str, *, timeout: float = 8) -> str:
    """Validate OAuth credentials without returning or persisting the bearer token."""

    try:
        token = _fetch_token(client_id, client_secret, timeout)
    except EnrichError as exc:
        return status_from_error(exc)
    return "ok" if token else "network_error"


class DigiKeyClient:
    """One authenticated Product Information V4 client.

    Product discovery, catalogue intelligence and order-time pricing deliberately share one
    token cache and one transport.  The old adapter exposed only KeywordSearch, which made every
    later feature invent its own auth/request code and turned the approved API surface into a
    collection of unrelated one-offs.
    """

    API_ROOT = "https://api.digikey.com/products/v4"

    def __init__(self, client_id: str, client_secret: str, timeout: float = 8):
        self.client_id = (client_id or "").strip()
        self.client_secret = client_secret or ""
        self.timeout = timeout
        self._token: str | None = None
        self._expires_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _cached_token(self) -> str:
        now = _time.monotonic()
        if self._token and now < self._expires_at:
            return self._token
        token = _fetch_token(self.client_id, self.client_secret, self.timeout)
        if not token:
            raise EnrichError("digikey: no OAuth token (bad creds or throttled)")
        self._token = token
        self._expires_at = now + 1500.0
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        query: dict[str, object] | None = None,
    ) -> dict:
        if not self.enabled:
            raise EnrichError("digikey: client credentials are not configured")
        url = f"{self.API_ROOT}{path}"
        if query:
            encoded = urllib.parse.urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
            if encoded:
                url += f"?{encoded}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._cached_token()}",
                "X-DIGIKEY-Client-Id": self.client_id,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            raise EnrichError(f"digikey request failed: {exc}", status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise EnrichError(f"digikey request failed: {exc}") from exc
        if not isinstance(decoded, dict):
            raise EnrichError("digikey response was not a JSON object")
        return decoded

    @staticmethod
    def _product_number(value: str) -> str:
        return urllib.parse.quote(str(value or "").strip(), safe="")

    def keyword_search(self, keywords: str, *, search_options: Iterable[str] = ()) -> dict:
        filters = [str(option) for option in search_options if str(option).strip()]
        body: dict[str, object] = {
            "Keywords": str(keywords or "").strip(),
            "Limit": 10,
            "Offset": 0,
        }
        if filters:
            body["FilterOptionsRequest"] = {"SearchOptions": filters}
        return self._request("POST", "/search/keyword", body=body)

    def product_details(self, product_number: str) -> dict:
        return self._request(
            "GET", f"/search/{self._product_number(product_number)}/productdetails"
        )

    def media(self, product_number: str) -> dict:
        return self._request("GET", f"/search/{self._product_number(product_number)}/media")

    def product_pricing(self, product_number: str) -> dict:
        return self._request("GET", f"/search/{self._product_number(product_number)}/pricing")

    def alternate_packaging(self, product_number: str) -> dict:
        return self._request(
            "GET", f"/search/{self._product_number(product_number)}/alternatepackaging"
        )

    def recommended_products(self, product_number: str) -> dict:
        return self._request(
            "GET", f"/search/{self._product_number(product_number)}/recommendedproducts"
        )

    def substitutions(self, product_number: str) -> dict:
        return self._request(
            "GET", f"/search/{self._product_number(product_number)}/substitutions"
        )

    def associations(self, product_number: str) -> dict:
        return self._request(
            "GET", f"/search/{self._product_number(product_number)}/associations"
        )

    def pricing_options_by_quantity(self, product_number: str, quantity: int) -> dict:
        if int(quantity) < 1:
            raise ValueError("requested quantity must be positive")
        return self._request(
            "GET",
            f"/search/{self._product_number(product_number)}/pricingbyquantity/{int(quantity)}",
        )

    def digireel_pricing(self, product_number: str, quantity: int) -> dict:
        if int(quantity) < 1:
            raise ValueError("requested quantity must be positive")
        return self._request(
            "GET",
            f"/search/{self._product_number(product_number)}/digireelpricing",
            query={"requestedQuantity": int(quantity)},
        )

    def manufacturers(self) -> dict:
        return self._request("GET", "/search/manufacturers")

    def categories(self) -> dict:
        return self._request("GET", "/search/categories")

    def category(self, category_id: int | str) -> dict:
        return self._request("GET", f"/search/categories/{int(category_id)}")

    def intake_bundle(self, mpn: str) -> dict:
        """Complete non-order evidence for a newly resolved part.

        ProductDetails, Media, and Product Pricing are unconditional. Relationship endpoints are
        kept separate in the bundle so alternate packaging can drive identity de-duplication
        without ever being confused with substitutions, recommendations or associations.
        Quantity-specific and DigiReel quote endpoints remain absent because they have no meaning
        until a BOM/order supplies a requested quantity.
        """
        search = self.keyword_search(mpn)
        product = _choose_product(search, mpn)
        product_number = _digikey_product_number(product)
        if not product_number:
            return {"schema_version": 1, "keyword_search": search}

        responses: dict[str, dict] = {"keyword_search": search}
        calls = (
            ("product_details", self.product_details),
            ("media", self.media),
            ("product_pricing", self.product_pricing),
            ("alternate_packaging", self.alternate_packaging),
            ("substitutions", self.substitutions),
            ("recommended_products", self.recommended_products),
            ("associations", self.associations),
        )
        for key, fetch in calls:
            try:
                responses[key] = fetch(product_number)
            except EnrichError as exc:
                # One optional catalogue relationship must never erase the product itself.  Keep
                # the missing endpoint named, without leaking auth headers or response bodies.
                responses[key] = {"_status": status_from_error(exc)}

        # The official filters are the authoritative availability probes.  They answer a
        # different question from Media (which tells us the provider links): whether an exact
        # search result is admitted by DigiKey's CAD/3D catalogue flags.
        for key, option in (
            ("has_cad_model_search", "HasCadModel"),
            ("has_3d_model_search", "Has3DModel"),
        ):
            try:
                responses[key] = self.keyword_search(mpn, search_options=(option,))
            except EnrichError as exc:
                responses[key] = {"_status": status_from_error(exc)}
        return {"schema_version": 1, "product_number": product_number, **responses}


_CLASSIFICATION_LABELS = {
    "RohsStatus": "RoHS",
    "ReachStatus": "REACH",
    "MoistureSensitivityLevel": "Moisture Sensitivity Level",
    "ExportControlClassNumber": "ECCN",
    "HtsusCode": "HTS Code (US)",
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


def _products(body: dict | None) -> list[dict]:
    if not isinstance(body, dict):
        return []
    for key in ("Products", "ProductVariations", "SearchResults"):
        value = body.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    product = body.get("Product")
    if isinstance(product, dict):
        return [product]
    if _obj_str(body.get("ManufacturerProductNumber")):
        return [body]
    return []


def _choose_product(body: dict | None, mpn: str) -> dict:
    products = _products(body)
    if not products:
        return {}
    target = normalize_mpn(mpn)
    return next(
        (
            product
            for product in products
            if normalize_mpn(_obj_str(product.get("ManufacturerProductNumber"))) == target
        ),
        {},
    )


def _digikey_product_number(product: dict) -> str:
    direct = _obj_str(product.get("DigiKeyProductNumber"))
    if direct:
        return direct
    return _obj_str(_pick_variation(product.get("ProductVariations")).get("DigiKeyProductNumber"))


def _bundle_response(body: dict | None, key: str) -> dict:
    value = (body or {}).get(key) if isinstance(body, dict) else None
    return value if isinstance(value, dict) else {}


def _details_product(body: dict | None, mpn: str) -> dict:
    details = _bundle_response(body, "product_details")
    chosen = _choose_product(details, mpn)
    return chosen or _choose_product(_bundle_response(body, "keyword_search"), mpn)


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _media_links(body: dict | None) -> list[dict]:
    """Flatten Media without binding Stockroom to one response wrapper revision."""
    media = _bundle_response(body, "media")
    out: list[dict] = []
    seen: set[str] = set()
    for item in _walk_dicts(media):
        url = _obj_str(item.get("Url")) or _obj_str(item.get("URL"))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "media_type": _obj_str(item.get("MediaType")) or _obj_str(item.get("Type")),
                "title": _obj_str(item.get("Title")) or _obj_str(item.get("Text")),
                "url": url,
            }
        )
    return out


def _provider_for_media(link: dict) -> str:
    haystack = f"{link.get('title', '')} {link.get('url', '')}".casefold()
    if "ultralibrarian" in haystack or "ultra librarian" in haystack:
        return "Ultra Librarian"
    if "snapeda" in haystack or "snapmagic" in haystack:
        return "SnapMagic"
    if "traceparts" in haystack:
        return "TraceParts"
    if "samacsys" in haystack or "componentsearchengine" in haystack:
        return "SamacSys"
    if "cadenas" in haystack:
        return "CADENAS"
    return ""


def _exact_filter_match(body: dict | None, mpn: str) -> bool | None:
    if not isinstance(body, dict) or body.get("_status"):
        return None
    target = normalize_mpn(mpn)
    return any(
        normalize_mpn(_obj_str(product.get("ManufacturerProductNumber"))) == target
        for product in _products(body)
    )


def pricing_options_from_payload(body: dict | None, mpn: str = "") -> list[dict]:
    """Flatten DigiKey quantity-pricing revisions into one stable purchasing view.

    When ``mpn`` is supplied, only ladders nested under that exact manufacturer part are kept;
    keyword search responses commonly include neighboring products that are evidence, but are not
    offers for the component being opened.
    """
    if not isinstance(body, dict):
        return []
    options: list[dict] = []
    seen: set[tuple] = set()
    target_mpn = normalize_mpn(mpn)

    def visit(
        value,
        inherited_product_number: str = "",
        inherited_packaging: str = "",
        inherited_mpn: str = "",
    ) -> None:
        if isinstance(value, list):
            for child in value:
                visit(child, inherited_product_number, inherited_packaging, inherited_mpn)
            return
        if not isinstance(value, dict):
            return
        item = value
        product_number = _obj_str(item.get("DigiKeyProductNumber")) or inherited_product_number
        manufacturer_mpn = (
            _obj_str(item.get("ManufacturerProductNumber")) or inherited_mpn
        )
        packaging = (
            _obj_str(item.get("PackageType"), "Name")
            or _obj_str(item.get("Packaging"), "Name")
            or _obj_str(item.get("PackageType"))
            or _obj_str(item.get("Packaging"))
            or inherited_packaging
        )
        price = item.get("UnitPrice")
        if price is None:
            price = item.get("Price")
        try:
            unit_price = float(price)
        except (TypeError, ValueError):
            pass
        else:
            quantity = item.get(
                "RequestedQuantity", item.get("Quantity", item.get("BreakQuantity", 0))
            )
            try:
                quantity_value = int(quantity or 0)
            except (TypeError, ValueError):
                quantity_value = 0
            currency = _obj_str(item.get("Currency")) or "USD"
            key = (product_number, packaging, quantity_value, unit_price, currency)
            exact_product = not target_mpn or normalize_mpn(manufacturer_mpn) == target_mpn
            if exact_product and key not in seen:
                seen.add(key)
                options.append(
                    {
                        "product_number": product_number,
                        "packaging": packaging,
                        "quantity": quantity_value,
                        "unit_price": unit_price,
                        "currency": currency,
                    }
                )
        for child in item.values():
            visit(child, product_number, packaging, manufacturer_mpn)

    visit(body)
    return sorted(options, key=lambda option: (option["unit_price"], option["product_number"]))


def digikey_catalog_from_payload(body: dict | None, mpn: str) -> dict:
    """Stable UI/persistence view over the complete raw DigiKey evidence bundle."""
    if not isinstance(body, dict):
        return {}
    product = _details_product(body, mpn)
    if not product:
        return {}
    media = _media_links(body)
    eda = [
        link
        for link in media
        if "eda" in str(link.get("media_type", "")).casefold()
        or "cad" in str(link.get("title", "")).casefold()
    ]
    providers = sorted({provider for link in eda if (provider := _provider_for_media(link))})
    cad_probe = _exact_filter_match(_bundle_response(body, "has_cad_model_search"), mpn)
    model_probe = _exact_filter_match(_bundle_response(body, "has_3d_model_search"), mpn)
    has_cad = cad_probe if cad_probe is not None else (True if eda else None)
    return {
        "schema_version": 1,
        "product_number": str(body.get("product_number") or _digikey_product_number(product)),
        "manufacturer_product_number": _obj_str(product.get("ManufacturerProductNumber")),
        "product_url": _obj_str(product.get("ProductUrl")),
        "availability": {
            "cad_model": has_cad,
            "three_d_model": model_probe,
            "providers": providers,
        },
        "media": media,
        # Every quantity ladder from every package variation remains available to the dossier.
        # The single canonical purchase row cannot represent several DigiKey SKUs without losing
        # the rest, so this provider-neutral list is the complete purchasing projection over the
        # retained raw response.
        "pricing_options": pricing_options_from_payload(body, mpn),
        # These remain separately named raw responses.  Their semantics are intentionally not
        # collapsed into one "related parts" list: alternate packaging is identity-equivalent;
        # substitutions, recommendations and associations are progressively weaker/different.
        "alternate_packaging": _bundle_response(body, "alternate_packaging"),
        "substitutions": _bundle_response(body, "substitutions"),
        "recommended_products": _bundle_response(body, "recommended_products"),
        "associations": _bundle_response(body, "associations"),
    }


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
    # DetailedDescription FIRST: DigiKey's `ProductDescription` is the abbreviated string it
    # prints in a search listing ("CAP CER 0.47UF 10V X7R 0402"), while `DetailedDescription`
    # is the readable one ("0.47 uF +/-10% 10V Ceramic Capacitor X7R 0402 (1005 Metric)").
    # Measured on the owner's library, 2026-07-27: both present on all 158 parts.
    desc = _obj_str(product.get("Description"), "DetailedDescription", "ProductDescription")
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


def parse_digikey_payload(body: dict | None, mpn: str) -> EnrichmentResult:
    """The WHOLE DigiKey response -> one EnrichmentResult, with no network and no credentials.

    The sibling of `parse_mouser_payload`; see that docstring for why the full body is the unit
    stored and re-parsed rather than the already-selected product.
    """
    # Import evidence written before the Product Information expansion is a plain
    # KeywordSearch response. New evidence is a versioned bundle whose ProductDetails answer is
    # the richer canonical product and whose KeywordSearch response remains the exact fallback.
    legacy = body or {}
    search = _bundle_response(body, "keyword_search") or legacy
    products = _products(search)
    if not products:
        return EnrichmentResult()
    target = normalize_mpn(mpn)
    exact = next(
        (
            p
            for p in products
            if isinstance(p, dict)
            and normalize_mpn(_obj_str(p.get("ManufacturerProductNumber")) or "") == target
        ),
        None,
    )
    detailed = _details_product(body, mpn)
    chosen = detailed or exact
    if not isinstance(chosen, dict):
        suggestions: list[str] = []
        seen: set[str] = set()
        for product in products:
            if not isinstance(product, dict):
                continue
            candidate = _obj_str(product.get("ManufacturerProductNumber")).strip()
            key = normalize_mpn(candidate)
            if not candidate or not key or key in seen:
                continue
            seen.add(key)
            suggestions.append(candidate)
            if len(suggestions) == 5:
                break
        result = EnrichmentResult()
        if suggestions:
            result.identity_suggestions["digikey"] = suggestions
        return result
    result = _parse_digikey_part(chosen)
    # Product Details is authoritative when present, but DigiKey's Keyword Search can carry
    # parameters or package fields omitted by that endpoint. Both are the same provider response
    # bundle, so fill only missing values and do not manufacture cross-source conflicts.
    if detailed and exact and detailed is not exact:
        result.merge_missing(_parse_digikey_part(exact), record_conflicts=False)
    catalog = digikey_catalog_from_payload(body, mpn)
    if catalog:
        result.catalog["digikey"] = catalog
    return result


class DigiKeyAdapter:
    def __init__(self, client_id: str = "", client_secret: str = "", requester=None):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.client = (
            DigiKeyClient(self.client_id, self.client_secret) if self.enabled and requester is None
            else None
        )
        self._requester = requester or (self.client.intake_bundle if self.client is not None else None)
        # out-of-band signal for the rescan circuit breaker (Phase-1b-2b); never affects the
        # returned EnrichmentResult, which stays exactly what it is today on every path.
        self.last_status: str = ""
        self.last_payload: dict | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def fetch_payload(self, mpn: str) -> dict | None:
        """The complete decoded response JSON for lossless storage. See the Mouser twin."""
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
        # FIXED 2026-07-27 (cold-eyes finding 1, the Mouser twin). See parse_mouser_payload's
        # sibling comment: an empty `Products` list is a truthy dict, so this must not use
        # HTTP-level truthiness to decide "ok".
        found = parse_digikey_payload(body, mpn).filled_fields()
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
        result = parse_digikey_payload(body, mpn)
        self.last_status = "ok" if result.filled_fields() else "not_found"
        if self.last_status == "ok" and isinstance(body, dict):
            self.last_payload = body
        return result
