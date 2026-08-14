"""Distributor offers, normalized once so nothing downstream parses a vendor payload.

Every offer answers the same questions in the same units whichever distributor it came from:
who, which order number, how many, at what price, in what currency, from what quantity, how
long the wait, and how long ago we asked. A surface reading these never sees a Mouser price
ladder or a DigiKey packaging block, and a new distributor is an adapter change rather than a
change here.

Freshness is a first-class field because a stock count is a measurement with a timestamp, not a
fact. `last checked` alone made a two-month-old count look identical to one taken this morning.
The clock is passed IN rather than read here, so the projection stays pure and testable; with no
clock the staleness is honestly `unknown` instead of being computed against a guess.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from stockroom.dossier.fields import normalize_key
from stockroom.dossier.urls import provider_of
from stockroom.enrich.schema import SOURCE_STATES, normalize_lifecycle
from stockroom.providers import provider_label

# How old a reading is allowed to be before it is worth saying so. Days, and deliberately
# generous: a distributor's stock moves fast, its price ladder does not.
STALENESS_THRESHOLDS: tuple[tuple[str, int], ...] = (("fresh", 2), ("aging", 14))
STALENESS_STATES: tuple[str, ...] = ("fresh", "aging", "stale", "unknown")

# A source outcome that means this offer's numbers could not be refreshed. `success` is not
# here: a source that answered has no failure to report.
_FAILURE_STATES: frozenset[str] = frozenset(SOURCE_STATES - {"success"})

_LEAD_TIME_KEYS: frozenset[str] = frozenset({"lead time", "manufacturer lead time"})
_FACTORY_LEAD_TIME_KEYS: frozenset[str] = frozenset(
    {"factory lead time", "factory lead weeks", "manufacturer standard lead time"}
)
_MOQ_KEYS: frozenset[str] = frozenset({"minimum order quantity", "moq", "order multiple"})
# The manufacturer's OWN word for where the part is in its life, which is a different claim from
# the lifecycle a distributor reports. A manufacturer saying "Not Recommended For New Designs"
# while a distributor still lists the part as active is exactly the disagreement worth showing.
_MANUFACTURER_STATUS_KEYS: frozenset[str] = frozenset(
    {
        "manufacturer part status",
        "manufacturer product status",
        "manufacturer status",
        "part status",
        "product status",
    }
)


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def staleness(fetched_at: object, now: object) -> str:
    """How much a reading taken at `fetched_at` can still be relied on."""
    then = _parse_time(fetched_at)
    reference = _parse_time(now)
    if then is None or reference is None:
        return "unknown"
    if then.tzinfo is None or reference.tzinfo is None:
        then = then.replace(tzinfo=None)
        reference = reference.replace(tzinfo=None)
    age_days = (reference - then).total_seconds() / 86400.0
    for state, limit in STALENESS_THRESHOLDS:
        if age_days <= limit:
            return state
    return "stale"


def _spec_lookup(record, wanted: frozenset[str]) -> str:
    for raw_key, value in (getattr(record, "specs", None) or {}).items():
        if normalize_key(raw_key) in wanted and value not in (None, ""):
            return str(value)
    return ""


def _price_breaks(entry) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in getattr(entry, "price_breaks", None) or []:
        if not isinstance(item, dict):
            continue
        qty = item.get("qty")
        price = item.get("price")
        try:
            qty_value = int(qty) if qty is not None else None
            price_value = float(price) if price is not None else None
        except (TypeError, ValueError):
            continue
        out.append({"qty": qty_value, "price": price_value})
    out.sort(key=lambda item: (item["qty"] is None, item["qty"]))
    return out


def _failure_state(record, provider_key: str) -> str:
    entry = (getattr(record, "sources", None) or {}).get(provider_key)
    raw = str((getattr(entry, "extra", None) or {}).get("state", "")).strip().casefold()
    return raw if raw in _FAILURE_STATES else ""


def manufacturer_status(record) -> str:
    """The manufacturer's own product status, or "" when it never said.

    Deliberately NOT run through `normalize_lifecycle`: that maps a distributor's token onto the
    library's canonical lifecycle, and the point of this field is to keep the manufacturer's own
    wording intact beside it. "" is honest silence, and a surface renders it as Unknown rather
    than assuming the part is active.
    """
    return _spec_lookup(record, _MANUFACTURER_STATUS_KEYS)


def _digikey_catalog_offers(
    record,
    *,
    now: str,
    lead_time: str,
    factory_lead_time: str,
    lifecycle: str,
) -> list[dict[str, Any]]:
    """Every exact-part DigiKey package ladder retained in catalog intelligence."""
    catalog = (getattr(record, "catalog", None) or {}).get("digikey")
    options = catalog.get("pricing_options") if isinstance(catalog, dict) else None
    if not isinstance(options, list):
        return []

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in options:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("product_number") or "").strip()
        packaging = str(item.get("packaging") or "").strip()
        currency = str(item.get("currency") or "USD").strip() or "USD"
        try:
            qty = int(item.get("quantity") or 0)
            price = float(item.get("unit_price"))
        except (TypeError, ValueError):
            continue
        if not sku or qty <= 0:
            continue
        row = {"qty": qty, "price": price}
        bucket = grouped.setdefault((sku, packaging, currency), [])
        if row not in bucket:
            bucket.append(row)

    source = (getattr(record, "sources", None) or {}).get("digikey")
    fetched_at = str(getattr(source, "fetched_at", "") or "")
    purchase = next(
        (
            item
            for item in getattr(record, "purchase", None) or []
            if str(getattr(item, "vendor", "") or "").casefold() == "digikey"
        ),
        None,
    )
    product_url = str(catalog.get("product_url") or "") if isinstance(catalog, dict) else ""
    offers: list[dict[str, Any]] = []
    for (sku, packaging, currency), breaks in grouped.items():
        breaks.sort(key=lambda item: item["qty"])
        purchase_sku = str(getattr(purchase, "part_number", "") or "")
        offers.append(
            {
                "provider": "digikey",
                "providerLabel": provider_label("digikey") or "DigiKey",
                "sku": f"{sku} · {packaging}" if packaging else sku,
                "stock": getattr(purchase, "stock", None) if purchase_sku == sku else None,
                "currency": currency,
                "unitPrice": breaks[0]["price"],
                "priceBreaks": breaks,
                "moq": breaks[0]["qty"],
                "leadTime": lead_time,
                "factoryLeadTime": factory_lead_time,
                "lifecycle": lifecycle,
                "offerUrl": product_url or str(getattr(purchase, "url", "") or ""),
                "lastCheckedAt": fetched_at or str(getattr(purchase, "fetched_at", "") or ""),
                "staleness": staleness(
                    fetched_at or getattr(purchase, "fetched_at", ""), now
                ),
                "failureState": _failure_state(record, "digikey"),
            }
        )
    return offers


def _mouser_catalog_offers(
    record,
    *,
    now: str,
    lead_time: str,
    factory_lead_time: str,
    lifecycle: str,
) -> list[dict[str, Any]]:
    """Every exact Mouser catalogue row, not only the canonical purchase companion."""
    catalog = (getattr(record, "catalog", None) or {}).get("mouser")
    rows = catalog.get("offers") if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        return []
    source = (getattr(record, "sources", None) or {}).get("mouser")
    fetched_at = str(getattr(source, "fetched_at", "") or "")
    offers: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("product_number") or "").strip()
        breaks: list[dict[str, Any]] = []
        currency = "USD"
        for raw in row.get("price_breaks") or []:
            if not isinstance(raw, dict):
                continue
            try:
                quantity = int(raw.get("qty") or 0)
                price = float(raw.get("price"))
            except (TypeError, ValueError):
                continue
            if quantity <= 0:
                continue
            currency = str(raw.get("currency") or currency)
            breaks.append({"qty": quantity, "price": price})
        breaks.sort(key=lambda item: item["qty"])
        if not sku:
            continue
        try:
            stock = int(row.get("stock")) if row.get("stock") not in (None, "") else None
        except (TypeError, ValueError):
            stock = None
        offers.append(
            {
                "provider": "mouser",
                "providerLabel": provider_label("mouser") or "Mouser",
                "sku": sku,
                "stock": stock,
                "currency": currency,
                "unitPrice": breaks[0]["price"] if breaks else None,
                "priceBreaks": breaks,
                "moq": breaks[0]["qty"] if breaks else None,
                "leadTime": lead_time,
                "factoryLeadTime": factory_lead_time,
                "lifecycle": lifecycle,
                "offerUrl": str(row.get("product_url") or ""),
                "lastCheckedAt": fetched_at,
                "staleness": staleness(fetched_at, now),
                "failureState": _failure_state(record, "mouser"),
            }
        )
    return offers


def build_offers(record, *, now: str = "") -> list[dict[str, Any]]:
    """One normalized offer per stored purchase entry or exact provider package ladder."""
    lead_time = _spec_lookup(record, _LEAD_TIME_KEYS)
    factory_lead_time = _spec_lookup(record, _FACTORY_LEAD_TIME_KEYS)
    lifecycle = normalize_lifecycle(_spec_lookup(record, frozenset({"lifecycle"}))) or ""
    declared_moq = _spec_lookup(record, _MOQ_KEYS)

    digikey_catalog_offers = _digikey_catalog_offers(
        record,
        now=now,
        lead_time=lead_time,
        factory_lead_time=factory_lead_time,
        lifecycle=lifecycle,
    )
    mouser_catalog_offers = _mouser_catalog_offers(
        record,
        now=now,
        lead_time=lead_time,
        factory_lead_time=factory_lead_time,
        lifecycle=lifecycle,
    )
    offers = [*digikey_catalog_offers, *mouser_catalog_offers]
    for entry in getattr(record, "purchase", None) or []:
        vendor = str(getattr(entry, "vendor", "") or "")
        provider = provider_of(getattr(entry, "url", ""))
        provider_key = (provider.key if provider is not None else vendor.casefold()).strip()
        if (
            (provider_key == "digikey" and digikey_catalog_offers)
            or (provider_key == "mouser" and mouser_catalog_offers)
        ):
            # Catalog projections carry every exact package/SKU ladder; a canonical purchase row
            # is only the volatile companion for one of them, not another distinct offer.
            continue
        breaks = _price_breaks(entry)
        unit_price = breaks[0]["price"] if breaks else None
        moq = breaks[0]["qty"] if breaks else None
        if moq is None and declared_moq:
            try:
                moq = int(float(declared_moq))
            except ValueError:
                moq = None
        offers.append(
            {
                "provider": provider_key,
                # A distributor URL always carries its provider, so a surface can say "Mouser
                # Listing" instead of the meaningless "Product Page" it used to show.
                "providerLabel": provider_label(provider_key) or vendor,
                "sku": str(getattr(entry, "part_number", "") or ""),
                "stock": getattr(entry, "stock", None),
                "currency": str(getattr(entry, "currency", "") or "") or "USD",
                "unitPrice": unit_price,
                "priceBreaks": breaks,
                "moq": moq,
                "leadTime": lead_time,
                "factoryLeadTime": factory_lead_time,
                "lifecycle": lifecycle,
                "offerUrl": str(getattr(entry, "url", "") or ""),
                "lastCheckedAt": str(getattr(entry, "fetched_at", "") or ""),
                "staleness": staleness(getattr(entry, "fetched_at", ""), now),
                # Empty when the source answered. A failure here is why the numbers beside it
                # may be older than they look.
                "failureState": _failure_state(record, provider_key),
            }
        )
    offers.sort(
        key=lambda item: (
            str(item["providerLabel"]).casefold(),
            str(item["provider"]),
            str(item["sku"]).casefold(),
        )
    )
    return offers


def indexed_source_failures(record, offers: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Failed official checks without an offer row still belong in Sourcing."""
    offered = {str(item.get("provider", "")) for item in offers}
    failures: list[dict[str, str]] = []
    for provider, entry in (getattr(record, "sources", None) or {}).items():
        state = str((getattr(entry, "extra", None) or {}).get("state", "")).casefold()
        if provider in offered or state not in _FAILURE_STATES:
            continue
        failures.append(
            {
                "provider": provider,
                "providerLabel": provider_label(provider) or provider,
                "state": state,
            }
        )
    return failures


def supply_summary(
    offers: list[dict[str, Any]],
    *,
    manufacturer_status: str = "",
    source_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """The buying answer in one line, derived only from the offers themselves.

    `manufacturer_status` is passed IN rather than read off a record here, so this stays a pure
    function of the offers plus one stated fact. It is the manufacturer's own status word, which
    no offer can supply and which belongs beside the lifecycle the offers do report.
    """
    priced = [item for item in offers if item["unitPrice"] is not None]
    best = min(priced, key=lambda item: item["unitPrice"]) if priced else None
    in_stock = [item for item in offers if isinstance(item["stock"], int) and item["stock"] > 0]
    counted = [item["stock"] for item in offers if isinstance(item["stock"], int)]
    order = {state: index for index, state in enumerate(STALENESS_STATES)}
    worst = max(
        (item["staleness"] for item in offers),
        key=lambda state: order.get(state, len(order)),
        default="unknown",
    )
    return {
        "offerCount": len(offers),
        "providersInStock": [item["provider"] for item in in_stock],
        # None, not zero: nobody reporting a count is a different fact from everybody
        # reporting none in stock, and zero would erase the difference.
        "totalStock": sum(counted) if counted else None,
        "bestUnitPrice": best["unitPrice"] if best is not None else None,
        "bestUnitPriceCurrency": best["currency"] if best is not None else "",
        "bestUnitPriceProvider": best["provider"] if best is not None else "",
        "lifecycle": next((item["lifecycle"] for item in offers if item["lifecycle"]), ""),
        # Kept apart from `lifecycle` on purpose: one is the canonical library state, the other is
        # what the manufacturer itself calls the part, and they are allowed to disagree.
        "manufacturerStatus": manufacturer_status,
        "leadTime": next((item["leadTime"] for item in offers if item["leadTime"]), ""),
        "factoryLeadTime": next(
            (item["factoryLeadTime"] for item in offers if item["factoryLeadTime"]), ""
        ),
        "staleness": worst,
        # Named, not keyed. A surface saying "digikey could not be read (not_configured)" is
        # showing a person two storage identifiers and calling it an explanation.
        "failures": [
            {
                "provider": item["provider"],
                "providerLabel": item["providerLabel"],
                "state": item["failureState"],
            }
            for item in offers
            if item["failureState"]
        ] + list(source_failures or []),
    }


__all__ = [
    "STALENESS_STATES",
    "STALENESS_THRESHOLDS",
    "build_offers",
    "indexed_source_failures",
    "manufacturer_status",
    "staleness",
    "supply_summary",
]
