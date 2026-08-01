"""Refresh an existing part's volatile procurement data from the distributor APIs.

The API lane (Mouser + DigiKey) has NO anti-bot wall and returns structured price/stock/
lifecycle, so a library rescan goes through it instead of scraping. We call each adapter's
lookup DIRECTLY (not EnrichmentPipeline.enrich, which caches per-MPN and often never reaches
the API legs), and keep the results PER VENDOR so each maps onto its own Purchase row."""
from __future__ import annotations

from stockroom.enrich.apply import conflict_entries, spec_updates
from stockroom.enrich.schema import EnrichmentResult
from stockroom.model.part import Datasheet, EnrichmentField, Purchase, SourcedValue
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value

# The specs a rescan RE-READS rather than merely gap-fills: they are the volatile procurement
# values the lane exists to keep current. Everything else a vendor returns is a stable
# parametric fact, so an existing one stands and a differing answer becomes an alternate.
_REFRESHED_SPECS: frozenset[str] = frozenset({"Lifecycle", "Lead Time", "US Tariff %"})


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
    # Everything else the vendors returned. This block is what the audit found missing: the
    # refresh used to apply the Lifecycle spec and NOTHING else, so a re-check discarded every
    # parametric spec, HTS code, lead time, origin, tariff, description and datasheet the API
    # had just handed it - even for a record that held none of them.
    # `written` carries across vendors: the FIRST vendor to answer for a key wins its slot for
    # this pass, and a later vendor's differing answer is kept as an alternate rather than
    # overriding the leader (first-reports-wins, not first-differs-wins).
    written: set[str] = set()
    for vendor, result in per_vendor:
        if _apply_pulled_detail(record, vendor, result, now_iso, written):
            changed = True
    return changed


def _apply_pulled_detail(record, vendor: str, result: EnrichmentResult, now_iso: str,
                         written: set[str]) -> bool:
    """Fold one vendor's non-purchase data onto the record, non-destructively.

    The rule differs from an ADD on purpose. A rescan re-checks a part that may have been
    corrected by hand, so a value already on the record STANDS: a spec is only filled when the
    record lacks it, and a differing answer is recorded as an alternate rather than written over
    the top. That way a second distributor's description is kept (punch 9) instead of being
    dropped, and nothing a human fixed is silently undone.

    Volatile procurement values ARE refreshed, because re-checking them is the whole point of
    the lane: Lifecycle, Lead Time and the tariff are re-read from the vendor each pass.
    """
    changed = False
    # Catalogue intelligence is a versioned snapshot rather than a scalar spec. A refresh replaces
    # only the provider that answered and leaves every other provider block untouched.
    for provider, data in result.catalog.items():
        if not isinstance(data, dict):
            continue
        if record.catalog.get(provider) != data:
            record.catalog[provider] = dict(data)
            changed = True
    for label, value, sourced in spec_updates(result):
        key = normalize_spec_key(label)
        if not key:
            continue
        value = normalize_spec_value(value)
        current = record.specs.get(key)
        # A key an earlier vendor already answered for in this pass is settled: only its
        # DISAGREEMENT is still interesting, never an override.
        refreshable = key in _REFRESHED_SPECS and key not in written
        if current is None or (refreshable and current != value):
            if current != value:
                record.specs[key] = value
                changed = True
            record.enrichment[key] = EnrichmentField(
                source=sourced.source, confidence=sourced.confidence
            )
            written.add(key)
        elif current == value:
            written.add(key)  # this vendor agrees; the slot is settled for the pass
        else:
            # A stable spec the record already holds AND the vendor disagrees about: keep both,
            # stored value first, so the disagreement is visible instead of discarded.
            if _remember_alternate(record, key, current, value, sourced.source):
                changed = True

    # The description is a top-level record field, not a spec, so it gets the same treatment by
    # hand: fill it when blank, otherwise keep both answers.
    if result.description is not None:
        pulled = str(result.description.value).strip()
        if pulled and not record.description.strip():
            record.description, changed = pulled, True
        elif pulled and pulled != record.description.strip():
            if _remember_alternate(
                record, "description", record.description, pulled, result.description.source
            ):
                changed = True

    # A datasheet link the record does not have is pure gain (the passport counts a URL), and a
    # link it already has is never replaced.
    if result.datasheet_url is not None:
        url = str(result.datasheet_url.value).strip()
        if url and (record.datasheet is None or not (
            record.datasheet.file or record.datasheet.source_url
        )):
            record.datasheet = record.datasheet or Datasheet()
            record.datasheet.source_url = url
            record.datasheet.fetched_at = now_iso
            changed = True

    # Every disagreement the enrich layer itself kept (two APIs answering one lookup).
    for key, entries in conflict_entries(result).items():
        for entry in entries:
            if _remember_alternate(
                record, key, record.specs.get(key), entry.value, entry.source
            ):
                changed = True
    return changed


def _remember_alternate(record, key: str, kept, value, source: str) -> bool:
    """Record `value` as another answer for `key`, seeding the list with the value currently in
    force so a reader always sees which one is stored. Returns True only when something was
    actually added, so an unchanged re-check still produces no commit."""
    entries = record.alternates.setdefault(key, [])
    if not entries and kept is not None and str(kept).strip():
        entries.append(SourcedValue(value=kept, source="", confidence=""))
    if any(_same(e.value, value) for e in entries):
        return False
    entries.append(SourcedValue(value=value, source=source, confidence=""))
    return True


def _same(a, b) -> bool:
    """Values agree when they match after trimming and case-folding, so formatting noise never
    fakes a disagreement (the same comparison the enrich merge uses)."""
    return str(a).strip().casefold() == str(b).strip().casefold()
