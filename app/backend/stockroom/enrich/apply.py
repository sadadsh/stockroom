"""What a pulled result implies for a part, as pure data.

Two places write enrichment onto a part and they used to disagree about what was worth
keeping: the ADD path (`enrich/pipeline._copy_specs`, via a staging candidate) carried specs
and dropped everything else, and the REFRESH path (`enrich/refresh`) kept price, stock and
Lifecycle and discarded every parametric spec, HTS code, lead time, origin, tariff,
description, datasheet and product URL on every re-check - so which vendor data a part ended
up with depended on whether it arrived by an add or by a rescan.

This module answers "what does this result say?" once, purely. The two callers keep their own
write semantics, because those genuinely differ: an add is filling a blank part, a refresh is
re-checking volatile data on a part that may have been corrected by hand.
"""

from __future__ import annotations

from stockroom.enrich.schema import EnrichmentResult, Sourced

# Canonical single-valued fields that have NO top-level home on a PartRecord, mapped to the spec
# label they are stored under. One registry map instead of per-extractor mirroring: the Mouser
# paths happened to mirror lifecycle and the tariff by hand (and the BOM cost layer reads
# `specs["US Tariff %"]` because of it), while DigiKey's `lead_time` was filled and then written
# down NOWHERE. Every other canonical field already has a real home - mpn / manufacturer /
# description / datasheet are record fields, package is its own spec, and product_url / stock are
# per-vendor Purchase data - so they are deliberately absent here.
FIELD_SPEC_LABELS: dict[str, str] = {
    "lifecycle": "Lifecycle",
    "lead_time": "Lead Time",
    "country_of_origin": "Country of Origin",
    "tariff_rate": "US Tariff %",
}


def spec_updates(result: EnrichmentResult) -> list[tuple[str, object, Sourced]]:
    """Every (spec label, value, origin) this result implies, in write order: the resolved
    package, each parametric spec, then the canonical fields that live as specs.

    Values are NOT coerced to str - a tariff rate is a float whose 0.0 means "confirmed no
    tariff", and turning that into "0.0" would make a real measurement look like a label.
    `product_url` is excluded: it is a purchase-link mechanism, not a spec row.
    """
    out: list[tuple[str, object, Sourced]] = []
    if result.package is not None:
        out.append(("Package", str(result.package.value), result.package))
    for label, sourced in result.specs.items():
        if label == "product_url":
            continue
        out.append((label, str(sourced.value), sourced))
    for field_name, label in FIELD_SPEC_LABELS.items():
        sourced = getattr(result, field_name, None)
        if sourced is not None:
            out.append((label, sourced.value, sourced))
    return out


def conflict_entries(result: EnrichmentResult) -> dict[str, list[Sourced]]:
    """Every kept disagreement, both namespaces folded into the one key space a record's
    `alternates` uses (a spec label, or a canonical field name in lower_snake)."""
    return {**result.spec_conflicts, **result.field_conflicts}
