"""The canonical specification record, and the category-aware grouping around it.

Everything a reader needs about ONE specification travels on ONE object: what it is called,
where it belongs, what the value means, who said so, who disagreed, whether the category even
expects it, and whether it can be filtered, sorted or compared. Nothing here is left for a
consumer to work out, because a consumer working it out is a consumer guessing.

The six states are kept strictly apart and are never collapsed into "unknown":

    missing         the category expects it and nobody supplied it - a real gap;
    not_reported    nobody supplied it and the category does not require it - not a gap;
    not_applicable  it does not apply to this kind of component at all;
    unverified      a value exists, from something short of the manufacturer's own word;
    conflicting     sources disagree, and every answer is carried;
    verified        a reviewed override or the manufacturer's own document.

An expected field with no value is still EMITTED. A hole a person can see is the whole point;
omitting it produced a sheet that looked complete because the gaps were invisible.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from stockroom.dossier.categories import CategorySchema, Constraint
from stockroom.dossier.fields import (
    FIELDS_BY_KEY,
    FieldDefinition,
    field_for,
    humanize,
    normalize_key,
)
from stockroom.dossier.precedence import (
    AUTHORITATIVE_TIERS,
    TIER_LABELS,
    Candidate,
    resolve,
    source_tier,
)
from stockroom.dossier.units import NormalizedValue, comparable_key, is_empty, normalize
from stockroom.dossier.vocabulary import (
    CATEGORY_GROUPS,
    GROUP_LABELS,
    GROUP_PARENT,
    OTHER_GROUP,
    UNIVERSAL_GROUPS,
)
from stockroom.providers import provider_label

# Spec keys that are bookkeeping rather than an engineering fact about the part. They stay in
# the record - they are real provider data - and stay reachable as raw evidence, but they never
# take a specification row: an asset reference, a link and a photo all have their own homes.
BOOKKEEPING_KEYS: frozenset[str] = frozenset(
    {
        "image",
        "product category",
        "product url",
        "datasheet",
        "datasheet url",
        "pinout",
        "symbol",
        "footprint",
        "3d model",
        "manufacturer page",
        "manufacturer url",
    }
)

# A distributor's INTERNAL record id is not a property of the part. LCSC's payload carries
# `brandId` / `catalogId`, and a humanized fallback label rendered `Brand Id 100` beside real
# parameters. The record deliberately KEEPS every field the source exposed; this is only about
# what is PRESENTED. Anchored on a trailing " Id" WORD, case-sensitive, so `Grid` keeps its row
# and a curated `LCSC Product ID` (spelled ID) keeps its own.
_VENDOR_RECORD_ID = re.compile(r" Id$")

# The whole-part group a key with no definition falls into.
_FALLBACK_GROUP = OTHER_GROUP[0]

# Where unregistered keys sort: after everything the schema ordered, in the order the source
# supplied them, so an unknown key is placed rather than shuffled.
_UNREGISTERED_ORDER_BASE = 10_000


@dataclass(frozen=True, slots=True)
class Specifications:
    """The whole specification half of a dossier, already decided."""

    records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    key_specifications: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    groups: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    completeness: Mapping[str, Any] = field(default_factory=dict)
    pinout: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # Source-specific keys that do not yet map onto a canonical field (raw level two).
    unmapped: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def is_presented(raw_key: object) -> bool:
    """True when a raw spec key belongs on the specification sheet at all."""
    text = str(raw_key or "").strip()
    if not text:
        return False
    if normalize_key(text) in BOOKKEEPING_KEYS:
        return False
    return not _VENDOR_RECORD_ID.search(text)


def _fallback_key(raw_key: str) -> str:
    """A stable canonical key for a spec the registry does not define yet."""
    return normalize_key(raw_key).replace(" ", "_") or "unnamed"


def _candidate(
    value: object,
    *,
    source: str,
    confidence: str,
    retrieved_at: str,
    original_key: str,
    definition: FieldDefinition | None,
    unit: str,
) -> Candidate:
    normalized = normalize(
        value,
        expected_unit=unit or (definition.unit if definition else ""),
        value_type=definition.value_type if definition else "",
    )
    return Candidate(
        value=value,
        normalized=normalized,
        source=str(source or ""),
        tier=source_tier(source),
        confidence=str(confidence or ""),
        retrieved_at=str(retrieved_at or ""),
        original_key=original_key,
    )


def _collect(record, schema: CategorySchema) -> tuple[
    dict[str, list[Candidate]], dict[str, FieldDefinition | None], list[str], list[dict[str, Any]]
]:
    """Every candidate answer, keyed by canonical field, plus what could not be mapped.

    A reviewed override contributes a candidate here only when it actually HOLDS a value. An
    entry that merely pins a source is a decision about which candidate wins, not a candidate of
    its own; adding it as one would put an empty manual answer at the top of the order and blank
    the field the pin was meant to settle.
    """
    candidates: dict[str, list[Candidate]] = {}
    definitions: dict[str, FieldDefinition | None] = {}
    order: list[str] = []
    unmapped: list[dict[str, Any]] = []

    specs = getattr(record, "specs", None) or {}
    enrichment = getattr(record, "enrichment", None) or {}
    alternates = getattr(record, "alternates", None) or {}
    sources = getattr(record, "sources", None) or {}

    for raw_key, value in specs.items():
        if not is_presented(raw_key):
            continue
        if isinstance(value, (list, dict)):
            # A structured leftover has no specification row. It stays reachable as raw record
            # data rather than rendering as an empty cell pretending to be a measurement.
            continue
        definition = field_for(raw_key)
        key = definition.key if definition is not None else _fallback_key(str(raw_key))
        if key not in candidates:
            candidates[key] = []
            definitions[key] = definition
            order.append(key)
        unit = schema.units.get(key, "")
        entry = enrichment.get(raw_key)
        stored = alternates.get(raw_key) or []
        if stored:
            # `PartRecord.alternates` repeats the winning value as its first entry, so the whole
            # list is the candidate set and nothing has to be re-derived from the winner.
            for offered in stored:
                candidates[key].append(
                    _candidate(
                        offered.value,
                        source=offered.source,
                        confidence=offered.confidence,
                        retrieved_at=getattr(sources.get(offered.source), "fetched_at", "") or "",
                        original_key=str(raw_key),
                        definition=definition,
                        unit=unit,
                    )
                )
        elif not is_empty(value):
            candidates[key].append(
                _candidate(
                    value,
                    source=getattr(entry, "source", "") or "",
                    confidence=getattr(entry, "confidence", "") or "",
                    retrieved_at=getattr(
                        sources.get(getattr(entry, "source", "")), "fetched_at", ""
                    ) or "",
                    original_key=str(raw_key),
                    definition=definition,
                    unit=unit,
                )
            )
        if definition is None:
            unmapped.append(
                {
                    "sourceKey": str(raw_key),
                    "canonicalKey": key,
                    "value": value,
                    "displayValue": "" if is_empty(value) else str(value),
                    "sourceId": getattr(entry, "source", "") or "",
                    "sourceLabel": provider_label(getattr(entry, "source", "") or ""),
                    "reason": "no canonical field claims this key yet",
                }
            )

    for key, override in (getattr(record, "overrides", None) or {}).items():
        definition = FIELDS_BY_KEY.get(key)
        if key not in candidates:
            candidates[key] = []
            definitions[key] = definition
            order.append(key)
        definitions.setdefault(key, definition)
        if not getattr(override, "has_value", True):
            continue
        candidates[key].append(
            _candidate(
                override.value,
                source="manual",
                confidence="",
                retrieved_at=override.reviewed_at,
                original_key=key,
                definition=definitions.get(key),
                unit=schema.units.get(key, ""),
            )
        )

    return candidates, definitions, order, unmapped


def _constraint_violation(
    constraint: Constraint | None, normalized: NormalizedValue
) -> str:
    """What the category's own rule says about this value, or "" when it says nothing.

    A violation is reported and the value is left exactly as the source gave it. Rewriting a
    distributor's answer to satisfy our rule would hide the disagreement that matters.
    """
    if constraint is None:
        return ""
    if constraint.allowed and normalized.display:
        allowed = {item.casefold() for item in constraint.allowed}
        if normalized.display.strip().casefold() not in allowed:
            return f"not one of {', '.join(constraint.allowed)}"
    magnitude = normalized.normalized
    if isinstance(magnitude, list):
        # A range is checked at its worst end, which is the one a rule about a floor catches.
        bounds = [item for item in magnitude if isinstance(item, (int, float))]
        magnitude = min(bounds) if bounds else None
    if not isinstance(magnitude, float):
        return ""
    if constraint.minimum is not None and magnitude < constraint.minimum:
        return f"below the minimum of {constraint.minimum}{constraint.unit}"
    if constraint.maximum is not None and magnitude > constraint.maximum:
        return f"above the maximum of {constraint.maximum}{constraint.unit}"
    return ""


# Source keys that are not providers and would otherwise render under their raw key.
_SOURCE_LABELS: dict[str, str] = {
    "manual": "Manual Override",
    "override": "Manual Override",
    "user": "Manual Override",
    "datasheet": "Datasheet",
    "provenance": "Original Package",
}


def source_label(source_id: str) -> str:
    """The name a source reads under. A value nothing accounts for says so, rather than
    borrowing a name it has no claim to."""
    if not source_id:
        return "Unattributed"
    return _SOURCE_LABELS.get(source_id.casefold()) or provider_label(source_id)


def _source_view(candidate: Candidate) -> dict[str, Any]:
    return {
        "sourceId": candidate.source,
        "sourceLabel": source_label(candidate.source),
        "tier": candidate.tier,
        "tierLabel": TIER_LABELS.get(candidate.tier, candidate.tier),
        "value": candidate.value,
        "displayValue": candidate.normalized.display,
        "normalizedValue": candidate.normalized.normalized,
        "unit": candidate.normalized.unit,
        "confidence": candidate.confidence,
        "retrievedAt": candidate.retrieved_at,
        "originalKey": candidate.original_key,
    }


def _verification_state(
    *,
    applicability: str,
    has_value: bool,
    conflict_state: str,
    tier: str,
    reviewed_unverified: bool = False,
) -> str:
    if not has_value:
        if applicability == "not_applicable":
            return "not_applicable"
        return "missing" if applicability == "expected" else "not_reported"
    if conflict_state == "conflicting":
        return "conflicting"
    if reviewed_unverified:
        # A reviewer who entered a value without confirming it said so. Reporting it as
        # `verified` because a manual decision outranks the sources would put our own word above
        # the manufacturer's on the strength of an admission that it had not been checked.
        return "unverified"
    return "verified" if tier in AUTHORITATIVE_TIERS else "unverified"


def _decision_views(
    override, resolution
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """How the reviewed decision on this field reads, as (override, preferred-source pin).

    Both carry what they displaced, because an override that cannot say what it replaced asks a
    reader to take it on trust, and a decision nobody can see the alternative to is a decision
    nobody can undo with any confidence.
    """
    if override is None:
        return None, None
    replaced_source = str(getattr(override, "replaced_source", "") or "")
    displaced = {
        "replacedValue": getattr(override, "replaced_value", None),
        "replacedSource": replaced_source,
        "replacedSourceLabel": source_label(replaced_source) if replaced_source else "",
    }
    value_view = (
        {
            "value": override.value,
            # The reviewer's stated reason. A manual value that disagrees with two distributors
            # and cannot say why is a value the next reader has to take on trust.
            "note": override.note,
            # Whether the reviewer stands behind it as checked. False is why the row can read
            # `Unverified` while still carrying a reviewed value.
            "verified": bool(getattr(override, "verified", True)),
            "reviewedBy": override.reviewed_by,
            "reviewedAt": override.reviewed_at,
            **displaced,
        }
        if getattr(override, "has_value", True)
        else None
    )
    pinned = str(getattr(override, "preferred_source", "") or "")
    pin_view = (
        {
            "sourceId": pinned,
            "sourceLabel": source_label(pinned),
            "reviewedBy": override.reviewed_by,
            "reviewedAt": override.reviewed_at,
            # True only when this pin is what the row is actually showing. False when the
            # pinned source no longer offers the field, and false while a reviewed VALUE
            # override outranks it - both are states a reader must be able to see, because a
            # control reporting itself in force while something else decides the value is a
            # control that lies about what it did.
            "inForce": (
                resolution.preferred is not None
                and resolution.preferred.source.casefold() == pinned.strip().casefold()
            ),
            **displaced,
        }
        if pinned
        else None
    )
    return value_view, pin_view


def _specification(
    key: str,
    definition: FieldDefinition | None,
    schema: CategorySchema,
    candidates: list[Candidate],
    *,
    order: int,
    override=None,
) -> dict[str, Any]:
    resolution = resolve(
        candidates,
        pinned_source=str(getattr(override, "preferred_source", "") or ""),
        exclude_discovery_sources=True,
    )
    override_view, pin_view = _decision_views(override, resolution)
    preferred = resolution.preferred
    applicability = schema.applicability(key)
    has_value = preferred is not None and not is_empty(preferred.value)
    normalized = preferred.normalized if preferred is not None else NormalizedValue(
        definition.value_type if definition else "text", None, "", ""
    )
    unit = normalized.unit or schema.units.get(key, "") or (definition.unit if definition else "")
    default_group = definition.group if definition is not None else _FALLBACK_GROUP
    group = schema.group_for(key, default_group)
    if group not in GROUP_LABELS:
        group = _FALLBACK_GROUP
    constraint = schema.constraints.get(key)
    violation = _constraint_violation(constraint, normalized) if has_value else ""
    tier = preferred.tier if preferred is not None else ""
    importance = (
        "key" if key in schema.key_specs
        else "primary" if applicability == "expected"
        else "secondary"
    )
    return {
        "key": key,
        "label": definition.label if definition is not None else humanize(
            (candidates[0].original_key if candidates else key)
        ),
        "group": group,
        "groupLabel": GROUP_LABELS.get(group, GROUP_LABELS[_FALLBACK_GROUP]),
        "order": order,
        "valueType": normalized.value_type if has_value else (
            definition.value_type if definition is not None else "text"
        ),
        "preferredValue": preferred.value if has_value else None,
        "normalizedValue": normalized.normalized if has_value else None,
        "displayValue": normalized.display if has_value else "",
        "unit": unit,
        "applicability": applicability,
        "importance": importance,
        "verificationState": _verification_state(
            applicability=applicability,
            has_value=has_value,
            conflict_state=resolution.conflict_state,
            tier=tier,
            reviewed_unverified=(
                tier == "manual_override"
                and override_view is not None
                and not override_view["verified"]
            ),
        ),
        "sourceCandidates": [_source_view(item) for item in resolution.candidates],
        "preferredSource": _source_view(preferred) if preferred is not None else None,
        # The reviewed decision in force on this field, so the row can say "overriding 3.3 V
        # from DigiKey" beside the value rather than presenting a manual answer as a sourced one.
        "override": override_view,
        "preferredSourcePin": pin_view,
        "confidence": preferred.confidence if preferred is not None else "",
        "conflictState": resolution.conflict_state,
        "expectedForCategory": applicability == "expected",
        "filterable": bool(definition.filterable) if definition is not None else False,
        "sortable": bool(definition.sortable) if definition is not None else False,
        "comparable": key in schema.comparison,
        # False says this key has no canonical definition yet - the source's own wording is
        # being shown, and that is a registry row this build still owes.
        "mapped": definition is not None,
        "constraint": (
            {
                "minimum": constraint.minimum,
                "maximum": constraint.maximum,
                "unit": constraint.unit,
                "allowed": list(constraint.allowed),
                "note": constraint.note,
            }
            if constraint is not None
            else None
        ),
        "constraintViolation": violation or None,
    }


def _pinout(record) -> tuple[dict[str, Any], ...]:
    for raw_key, value in (getattr(record, "specs", None) or {}).items():
        if normalize_key(raw_key) == "pinout" and isinstance(value, list):
            return tuple(dict(entry) for entry in value if isinstance(entry, dict))
    return ()


def _completeness(
    schema: CategorySchema, by_key: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    """How complete this part is FOR ITS CATEGORY, counting nothing irrelevant to it.

    A resistor is not incomplete for having no clock source, and a connector is not incomplete
    for having no flash size. Only the fields this category expects and recommends are counted,
    weighted by what the schema says they are worth, so the number means the same thing on every
    part of the same kind and never means anything across kinds it was not measured for.
    """
    def _present(keys: tuple[str, ...]) -> list[str]:
        return [
            key
            for key in keys
            if (by_key.get(key) or {}).get("verificationState")
            in {"verified", "unverified", "conflicting"}
        ]

    expected_present = _present(schema.expected)
    recommended_present = _present(schema.recommended)
    expected_total = len(schema.expected)
    recommended_total = len(schema.recommended)
    weighted_total = (
        schema.expected_weight * expected_total + schema.recommended_weight * recommended_total
    )
    weighted_present = (
        schema.expected_weight * len(expected_present)
        + schema.recommended_weight * len(recommended_present)
    )
    score = 1.0 if weighted_total == 0 else round(weighted_present / weighted_total, 4)
    return {
        "score": score,
        "expectedPresent": len(expected_present),
        "expectedTotal": expected_total,
        "recommendedPresent": len(recommended_present),
        "recommendedTotal": recommended_total,
        "missingExpected": [key for key in schema.expected if key not in expected_present],
        "missingRecommended": [
            key for key in schema.recommended if key not in recommended_present
        ],
        # Named so a reader can tell WHICH definition of complete produced the number.
        "basis": schema.key,
    }


def _earns_a_heading(specification: Mapping[str, Any]) -> bool:
    """True when this row is something a reader can actually read under a heading.

    A heading is a promise that there is something below it. Three of the six states keep that
    promise: a value keeps it, and so does `missing` (the category expects this and nobody
    supplied it) and `not_reported` (the category recommends it and nobody supplied it) - a
    stated gap is real content and is the entire reason expected fields are emitted with no
    value at all.

    `not_applicable` keeps no promise. It says the field is not a thing this kind of component
    has, and a heading whose every row says that is a heading about nothing. MEASURED on a
    100 nF 0402 capacitor: the capacitor schema declares `program_memory_size` and `interface`
    inapplicable, those two keys belong to the microcontroller groups `memory` and
    `communication_interfaces`, and the sheet therefore grew a `Memory` and a
    `Communication Interfaces` heading - offered in the column's anchor strip - on a ceramic
    capacitor. The row itself is NOT discarded: it stays in `records`, so completeness, search
    and the raw evidence levels still know the field was considered and ruled out. It simply
    does not conjure a section of its own, and where a group has real rows beside it, it still
    renders among them and still tells a reader looking for it that it does not apply.
    """
    return specification.get("verificationState") != "not_applicable"


def build_specifications(record, schema: CategorySchema) -> Specifications:
    """Every specification for one record, grouped and stated by this category's own rules."""
    candidates, definitions, seen_order, unmapped = _collect(record, schema)

    universe: list[str] = []
    for key in schema.field_order():
        if key in schema.expected or key in schema.recommended or key in schema.key_specs:
            universe.append(key)
    for key in schema.not_applicable:
        if key not in universe:
            universe.append(key)
    for key in seen_order:
        if key not in universe:
            universe.append(key)

    schema_order = schema.field_order()
    overrides = getattr(record, "overrides", None) or {}
    records: list[dict[str, Any]] = []
    for index, key in enumerate(universe):
        definition = definitions.get(key) or FIELDS_BY_KEY.get(key)
        if key in schema_order:
            order = schema_order.index(key)
        elif definition is not None:
            order = _UNREGISTERED_ORDER_BASE + index
        else:
            order = 2 * _UNREGISTERED_ORDER_BASE + index
        records.append(
            _specification(
                key,
                definition,
                schema,
                candidates.get(key, []),
                order=order,
                override=overrides.get(key),
            )
        )

    by_key = {item["key"]: item for item in records}
    key_specs = tuple(by_key[key] for key in schema.key_specs if key in by_key)

    # A KEY SPECIFICATION IS MOVED INTO THE HEADLINE BLOCK, NOT COPIED INTO IT.
    #
    # This was the other way round for one release, on the reasoning that supply voltage is a key
    # fact ABOUT a logic gate and an electrical parameter OF it, so a reader working down the
    # Electrical group had to find it there. MEASURED on a 100 nF 0402 capacitor, the cost of that
    # reasoning was the whole sheet: all seven of the capacitor's key specifications were also its
    # groups' only rows, so eleven distinct fields rendered as eighteen rows under ten headings, and
    # `Capacitance` appeared twice on one screen about a capacitor. A reader scrolling the groups was
    # re-reading the block they had just read.
    #
    # So promotion is a MOVE. The headline block answers "what is this part", the groups answer
    # "what else is on record about it", and no value is stated twice.
    promoted = {item["key"] for item in key_specs}
    remaining = [item for item in records if item["key"] not in promoted]
    rows_by_group: dict[str, list[dict[str, Any]]] = {}
    for item in remaining:
        rows_by_group.setdefault(item["group"], []).append(item)

    def content(group_id: str) -> int:
        """How many rows under this group a reader can actually read. See `_earns_a_heading`."""
        return sum(1 for item in rows_by_group.get(group_id, ()) if _earns_a_heading(item))

    # The headings this sheet actually renders: the schema's own order first, then any group a
    # row landed in that the schema never declared, then `other`. That middle step is what stops
    # a specification DISAPPEARING: a field's registry group (a resistor's `Mounting Type` sits
    # in `mounting`) does not have to be one the category listed, and a row with nowhere to go
    # used to be dropped from the sheet entirely - which is exactly the invisible hole the whole
    # category schema exists to prevent.
    declared = [key for key in schema.group_order() if key != "key_specifications"]
    undeclared = [
        group_id
        for group_id, _ in UNIVERSAL_GROUPS + CATEGORY_GROUPS
        if group_id not in declared and group_id != "key_specifications" and content(group_id) > 0
    ]
    ordering = (*declared, *undeclared, OTHER_GROUP[0])

    # A REFINEMENT HOLDING ONE ROW FOLDS INTO THE HEADING ABOVE IT.
    #
    # One header line per line of data is not a grouping, it is an index. `Capacitance`,
    # `Tolerance and Stability`, `Temperature Characteristics`, `Construction and Termination` and
    # `Mounting` each held exactly one row on the seeded capacitor, and the anchor strip offered all
    # five as destinations. So a category group with a single readable row is dropped and its rows are
    # read under the universal heading it refines (`GROUP_PARENT`, which declares one for every
    # category group and never points at `key_specifications` or `other`).
    #
    # DETERMINISTIC BY CONSTRUCTION, because a row must never move between renders: the fold target is
    # a static declaration, the decision is a pure function of one group's own row count, it is taken
    # in one pass over the fixed `ordering`, and it is not applied recursively - a parent that ends up
    # holding one folded row keeps its heading rather than folding onward into a third place.
    #
    # A UNIVERSAL group never folds. It has no `GROUP_PARENT` entry because it IS the parent, and one
    # row under `Environmental and Reliability` is still a heading a reader navigates by.
    folded_in: dict[str, list[dict[str, Any]]] = {}
    dissolved: set[str] = set()
    for group_id in ordering:
        parent = GROUP_PARENT.get(group_id)
        if parent is None or content(group_id) != 1:
            continue
        # Every row moves, the inapplicable ones included: a group is kept or dropped WHOLE, and a
        # row that says "this does not apply to this part" is still an answer somebody may look for.
        folded_in.setdefault(parent, []).extend(rows_by_group.get(group_id, ()))
        dissolved.add(group_id)

    groups: list[dict[str, Any]] = []
    for group_id in ordering:
        if group_id in dissolved:
            continue
        rows = [*rows_by_group.get(group_id, ()), *folded_in.get(group_id, ())]
        if not any(_earns_a_heading(item) for item in rows):
            continue
        rows.sort(key=lambda item: (item["order"], item["label"]))
        groups.append(
            {
                "id": group_id,
                "label": GROUP_LABELS.get(group_id, group_id),
                "specifications": rows,
                "count": len(rows),
            }
        )

    return Specifications(
        records=tuple(records),
        key_specifications=key_specs,
        groups=tuple(groups),
        completeness=_completeness(schema, by_key),
        pinout=_pinout(record),
        unmapped=tuple(unmapped),
    )


def record_field(record, key: str, label: str, value: object) -> dict[str, Any]:
    """One record-level sourced field, resolved by exactly the same precedence as a spec.

    The description, the MPN and the manufacturer are sourced facts like any other and sources
    disagree about them like any other - a distributor's description of a part is often not the
    manufacturer's. They are not SPECIFICATIONS, so they do not belong on the sheet, but their
    disagreements have to be visible somewhere or a conflict silently picks a winner.
    """
    sources = getattr(record, "sources", None) or {}
    entry = (getattr(record, "enrichment", None) or {}).get(key)
    stored = (getattr(record, "alternates", None) or {}).get(key) or []
    candidates: list[Candidate] = []
    if stored:
        for offered in stored:
            candidates.append(
                _candidate(
                    offered.value,
                    source=offered.source,
                    confidence=offered.confidence,
                    retrieved_at=getattr(sources.get(offered.source), "fetched_at", "") or "",
                    original_key=key,
                    definition=None,
                    unit="",
                )
            )
    elif not is_empty(value):
        source = getattr(entry, "source", "") or ""
        candidates.append(
            _candidate(
                value,
                source=source,
                confidence=getattr(entry, "confidence", "") or "",
                retrieved_at=getattr(sources.get(source), "fetched_at", "") or "",
                original_key=key,
                definition=None,
                unit="",
            )
        )
    resolution = resolve(candidates, exclude_discovery_sources=True)
    preferred = resolution.preferred
    return {
        "key": key,
        "label": label,
        "preferredValue": preferred.value if preferred is not None else None,
        "displayValue": preferred.normalized.display if preferred is not None else "",
        "sourceCandidates": [_source_view(item) for item in resolution.candidates],
        "preferredSource": _source_view(preferred) if preferred is not None else None,
        "conflictState": resolution.conflict_state,
        "verificationState": _verification_state(
            applicability="applicable",
            has_value=preferred is not None,
            conflict_state=resolution.conflict_state,
            tier=preferred.tier if preferred is not None else "",
        ),
        # Present so the raw evidence level can treat a record field and a specification
        # identically; nothing here is a canonical specification.
        "mapped": False,
    }


def distinct_answers(specification: Mapping[str, Any]) -> int:
    """How many materially different answers one specification is carrying."""
    values = {
        comparable_key(
            NormalizedValue(
                "text",
                candidate.get("normalizedValue"),
                str(candidate.get("unit") or ""),
                str(candidate.get("displayValue") or ""),
            )
        )
        for candidate in specification.get("sourceCandidates") or []
    }
    return len(values)


__all__ = [
    "BOOKKEEPING_KEYS",
    "Specifications",
    "build_specifications",
    "distinct_answers",
    "is_presented",
    "record_field",
    "source_label",
]
