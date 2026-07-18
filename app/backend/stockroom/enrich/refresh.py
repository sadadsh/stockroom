"""Refresh an existing part's volatile procurement data from the distributor APIs.

The API lane (Mouser + DigiKey) has NO anti-bot wall and returns structured price/stock/
lifecycle, so a library rescan goes through it instead of scraping. We call each adapter's
lookup DIRECTLY (not EnrichmentPipeline.enrich, which caches per-MPN and often never reaches
the API legs), and keep the results PER VENDOR so each maps onto its own Purchase row."""
from __future__ import annotations

from stockroom.enrich.schema import EnrichmentResult
from stockroom.model.part import Purchase


def _has_data(result: EnrichmentResult) -> bool:
    return (result.mpn is not None or bool(result.price_breaks)
            or result.stock is not None or result.lifecycle is not None)


def refresh_via_adapters(mpn: str, adapters: list) -> list[tuple[str, EnrichmentResult]]:
    """(vendor, result) for each ENABLED adapter that returned real data. Never raises: each
    adapter.lookup already degrades a failure to an empty EnrichmentResult."""
    out: list[tuple[str, EnrichmentResult]] = []
    if not mpn:
        return out
    for adapter in adapters:
        if not getattr(adapter, "enabled", False):
            continue
        result = adapter.lookup(mpn)
        if _has_data(result):
            out.append((getattr(adapter, "vendor", "distributor"), result))
    return out


def apply_procurement_refresh(record, per_vendor, now_iso: str) -> bool:
    """Update record's Purchase rows + Lifecycle spec from the per-vendor API results, in place,
    non-destructively. Returns True iff anything changed. A value is written only when the result
    actually carries it, so a thin API answer never wipes existing data."""
    changed = False
    for vendor, result in per_vendor:
        if not _has_data(result):
            continue
        dk_pn = result.dist_pns.get(vendor.lower())
        # Only ever create/update a Purchase when the vendor returned purchase-shaped data
        # (price / stock / order P/N); a result carrying only identity or lifecycle never
        # creates an empty Purchase row (its lifecycle is applied below).
        has_purchase = bool(result.price_breaks) or result.stock is not None or bool(dk_pn)
        purchase = next((p for p in record.purchase
                         if (p.vendor or "").lower() == vendor.lower()), None)
        if purchase is None and not has_purchase:
            continue
        # Track whether THIS vendor's real data changed, so fetched_at (and thus a commit) only
        # moves on a genuine data change - not on every re-check. Otherwise a bulk rescan of N
        # unchanged parts would churn N one-line fetched_at commits per run (the "no empty commit"
        # constraint). fetched_at means "when this vendor's data last CHANGED".
        vendor_changed = False
        if purchase is None:
            purchase = Purchase(vendor=vendor)
            record.purchase.append(purchase)
            vendor_changed = True
        if result.price_breaks:
            new_breaks = [{"qty": b.qty, "price": b.price} for b in result.price_breaks]
            if new_breaks != purchase.price_breaks:
                purchase.price_breaks, vendor_changed = new_breaks, True
            currency = result.price_breaks[0].currency
            if currency and purchase.currency != currency:
                purchase.currency, vendor_changed = currency, True
        if result.stock is not None and purchase.stock != result.stock.value:
            purchase.stock, vendor_changed = result.stock.value, True
        if dk_pn and purchase.part_number != dk_pn:
            purchase.part_number, vendor_changed = dk_pn, True
        if vendor_changed:
            purchase.fetched_at = now_iso
            changed = True
    # lifecycle: first vendor that reported one (a Sourced field the candidate mapping drops)
    for _vendor, result in per_vendor:
        if result.lifecycle is not None and record.specs.get("Lifecycle") != result.lifecycle.value:
            record.specs["Lifecycle"], changed = result.lifecycle.value, True
            break
    return changed
