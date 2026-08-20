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

IDENTITY_PROJECTION_FIELDS: tuple[str, ...] = (
    "manufacturer",
    "description",
    "datasheet_url",
)

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
    catalogue supplies. Browser-extracted provider pages, LCSC, CAD providers and generic
    scrapes are deliberately outside this fact boundary.
    """
    key = str(source or "").strip().casefold()
    if key == "mouser":
        return 0
    if key == "digikey":
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


def _official_answers(result: EnrichmentResult, keys: tuple[str, ...]) -> list[Sourced]:
    """Provider-bound answers whose equal-value merges may have left no conflict entry."""
    answers: list[Sourced] = []
    for provider, binding in getattr(result, "official_evidence", {}).items():
        if not isinstance(binding, dict):
            continue
        values = binding.get("selected_values", {})
        if not isinstance(values, dict):
            continue
        for key in keys:
            if key not in values:
                continue
            value = values[key]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            answers.append(Sourced(value, str(provider), "high"))
            break
    return answers


def _permitted_result_answer(result: EnrichmentResult, sourced: Sourced) -> bool:
    """A datasheet becomes fact authority only after its PDF proves the requested MPN."""
    if specification_authority_rank(sourced.source) != 2:
        return True
    return "manufacturer_datasheet" in result.identity_authorities


def identity_evidence(result: EnrichmentResult, field_name: str) -> tuple[Sourced, ...]:
    """Every permitted answer for one selected identity field, in fixed authority order."""
    candidates = [
        *result.field_conflicts.get(field_name, []),
        *_official_answers(result, (field_name,)),
    ]
    primary = getattr(result, field_name)
    if primary is not None and not _permitted_result_answer(result, primary):
        primary = None
    return ordered_specification_answers(
        primary,
        [answer for answer in candidates if _permitted_result_answer(result, answer)],
    )


def identity_projection(result: EnrichmentResult) -> dict[str, Sourced | None]:
    """Select top-level identity facts through the same fixed authority as specs.

    Official payload bindings are included because two providers can report an identical value;
    the conflict map intentionally collapses that agreement, but the projection must still know
    that an authoritative provider stated it. LCSC and generic scrape values remain available in
    raw evidence and offer data, but never become these three selected facts.
    """
    projected: dict[str, Sourced | None] = {}
    for field_name in IDENTITY_PROJECTION_FIELDS:
        answers = identity_evidence(result, field_name)
        projected[field_name] = answers[0] if answers else None
    return projected


def specification_evidence(
    result: EnrichmentResult,
) -> list[tuple[str, tuple[Sourced, ...]]]:
    """Every allowed fact and its ordered competing answers, keyed by display label."""
    out: dict[str, tuple[Sourced, ...]] = {}

    def collect(
        label: str,
        primary: Sourced | None,
        conflicts: list[Sourced],
        *official_keys: str,
    ) -> None:
        candidates = [
            *conflicts,
            *_official_answers(result, tuple(official_keys) or (label,)),
        ]
        if primary is not None and not _permitted_result_answer(result, primary):
            primary = None
        answers = ordered_specification_answers(
            primary,
            [answer for answer in candidates if _permitted_result_answer(result, answer)],
        )
        if not answers or label in out:
            return
        out[label] = answers

    collect(
        "Package",
        result.package,
        result.field_conflicts.get("package", []),
        "package",
        "Package",
    )
    for label, sourced in result.specs.items():
        if label == "product_url":
            continue
        collect(label, sourced, result.spec_conflicts.get(label, []), label)
    for field_name, label in FIELD_SPEC_LABELS.items():
        sourced = getattr(result, field_name, None)
        collect(label, sourced, result.field_conflicts.get(field_name, []), field_name, label)
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
