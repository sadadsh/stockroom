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


def specification_authority_rank(source: object) -> int | None:
    """The fixed fact-authority order for specifications and classification.

    Mouser leads, DigiKey fills the gaps, and a manufacturer datasheet fills what neither
    catalogue supplies.  Distributor HTML variants retain their provider family, while LCSC,
    CAD providers and generic scrapes are deliberately outside this fact boundary.
    """
    key = str(source or "").strip().casefold()
    if key == "mouser" or key.startswith(("mouser_", "mouser-")):
        return 0
    if key == "digikey" or key.startswith(("digikey_", "digikey-")):
        return 1
    if key in {"datasheet", "manufacturer_datasheet"}:
        return 2
    return None


def ordered_specification_answers(
    primary: Sourced | None, alternatives: list[Sourced] | tuple[Sourced, ...] = ()
) -> tuple[Sourced, ...]:
    """Allowed answers in the one fixed order, without duplicate source/value pairs."""
    unique: list[Sourced] = []
    seen: set[tuple[str, str]] = set()
    for sourced in ([primary] if primary is not None else []) + list(alternatives):
        rank = specification_authority_rank(sourced.source)
        if rank is None:
            continue
        identity = (str(sourced.source).casefold(), str(sourced.value).strip().casefold())
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(sourced)
    return tuple(
        sorted(unique, key=lambda sourced: specification_authority_rank(sourced.source) or 0)
    )


def specification_evidence(
    result: EnrichmentResult,
) -> list[tuple[str, tuple[Sourced, ...]]]:
    """Every allowed fact and its ordered competing answers, keyed by display label."""
    out: dict[str, tuple[Sourced, ...]] = {}

    def collect(label: str, primary: Sourced | None, conflicts: list[Sourced]) -> None:
        answers = ordered_specification_answers(primary, conflicts)
        if not answers or label in out:
            return
        out[label] = answers

    collect("Package", result.package, result.field_conflicts.get("package", []))
    for label, sourced in result.specs.items():
        if label == "product_url":
            continue
        collect(label, sourced, result.spec_conflicts.get(label, []))
    for field_name, label in FIELD_SPEC_LABELS.items():
        sourced = getattr(result, field_name, None)
        collect(label, sourced, result.field_conflicts.get(field_name, []))
    return list(out.items())


def spec_updates(result: EnrichmentResult) -> list[tuple[str, object, Sourced]]:
    """Every selected (spec label, value, origin), in stable write order.

    Values are NOT coerced to str - a tariff rate is a float whose 0.0 means "confirmed no
    tariff", and turning that into "0.0" would make a real measurement look like a label.
    `product_url` is excluded: it is a purchase-link mechanism, not a spec row.
    """
    return [
        (label, answers[0].value, answers[0]) for label, answers in specification_evidence(result)
    ]


def conflict_entries(result: EnrichmentResult) -> dict[str, list[Sourced]]:
    """Every kept disagreement, both namespaces folded into the one key space a record's
    `alternates` uses (a spec label, or a canonical field name in lower_snake)."""
    specification_fields = {"package", *FIELD_SPEC_LABELS}
    record_fields = {
        key: entries
        for key, entries in result.field_conflicts.items()
        if key not in specification_fields
    }
    specification_fields = {
        label: list(answers) for label, answers in specification_evidence(result)
    }
    return {**record_fields, **specification_fields}
