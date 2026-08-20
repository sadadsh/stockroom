"""The component dossier: one coherent read model of a `PartRecord`.

`PartRecord` is the right shape for storage, provenance, git history, derivation and EDA output.
It is the wrong shape for a screen. Serving `record.to_dict()` forced the frontend to decide what
counts as identity, which specifications belong together for THIS kind of component, which
provider payload deserves a card, which link is the manufacturer's own, and which disagreements
matter - so those decisions were made repeatedly, inconsistently, and in a component that also
had to render.

This module makes them once. It is a pure projection:

    * it never writes, never reads the filesystem, and never calls a network source;
    * it never becomes a second source of truth - nothing here is persisted back;
    * every canonical record field has exactly one declared destination (`destinations.py`),
      so a field can never be silently dropped from the product.

The raw record endpoint stays available for compatibility and diagnostics. The opened component
reads this instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stockroom.dossier.cad import build_cad_assets, representation
from stockroom.dossier.categories import CategorySchema, resolve_schema
from stockroom.dossier.documents import build_documents
from stockroom.dossier.fields import field_for, humanize, normalize_key
from stockroom.dossier.manufacturer import manufacturer_page
from stockroom.dossier.offers import (
    build_offers,
    indexed_source_failures,
    manufacturer_status,
    supply_summary,
)
from stockroom.dossier.official_evidence import build_official_evidence
from stockroom.dossier.raw import build_compatibility, build_conflicts, build_raw_levels
from stockroom.dossier.related import build_related_parts
from stockroom.dossier.revisions import build_revisions, manual_overrides
from stockroom.dossier.specifications import (
    Specifications,
    build_specifications,
    record_field,
    source_label,
)
from stockroom.dossier.vocabulary import (
    CATEGORY_GROUPS,
    DOSSIER_SCHEMA_VERSION,
    UNIVERSAL_GROUPS,
    VERIFICATION_STATES,
)
from stockroom.enrich.schema import SOURCE_STATES
from stockroom.model.asset import ASSET_KINDS
from stockroom.model.part import REQUIRED_FIELDS
from stockroom.provider_coverage import provider_coverage

# The identity fields a part cannot be completed without. Separate from the category schema on
# purpose: these are true of every component whatever it is.
_BLOCKING_IDENTITY: tuple[tuple[str, str], ...] = (
    ("mpn", "Manufacturer Part Number"),
    ("manufacturer", "Manufacturer"),
    ("description", "Description"),
)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _identity(
    record,
    schema: CategorySchema,
    specifications: Specifications,
    identity_values: Mapping[str, str],
) -> dict[str, Any]:
    by_key = {item["key"]: item for item in specifications.records}
    package = (by_key.get("package") or {}).get("displayValue") or ""
    pin_count = (by_key.get("pin_count") or {}).get("normalizedValue")
    lifecycle = (by_key.get("lifecycle") or {}).get("displayValue") or ""
    return {
        "id": record.id,
        "displayName": record.display_name or record.mpn or record.id,
        "mpn": identity_values["mpn"],
        "manufacturer": identity_values["manufacturer"],
        "category": record.category,
        "categorySchema": {
            "key": schema.key,
            "label": schema.label,
            "parent": schema.parent,
        },
        "partClass": str(record.part_class),
        "value": record.value,
        "package": package or None,
        "pinCount": int(pin_count) if isinstance(pin_count, float) else None,
        "lifecycle": lifecycle or None,
        "tags": list(record.tags),
        # The manufacturer's own page, never taken from an offer. See `dossier.manufacturer`.
        "manufacturerPage": manufacturer_page(record),
    }


def _attention(
    record,
    specifications: Specifications,
    identity_values: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Only unresolved, actionable problems. Every item names what to do about it."""
    items: list[dict[str, Any]] = []
    for field_name, label in _BLOCKING_IDENTITY:
        if not identity_values[field_name]:
            items.append(
                {
                    "id": f"identity.{field_name}",
                    "severity": "blocking",
                    "title": f"{label} Is Missing",
                    "detail": "This component cannot be completed without it.",
                    "action": "edit-identity",
                }
            )

    for kind in ASSET_KINDS:
        view = representation(record, kind)
        if view["status"] in {"missing", "failed", "review"}:
            items.append(
                {
                    "id": f"representation.{kind}",
                    "severity": "blocking" if view["status"] == "missing" else "warning",
                    "title": f"{kind.title()} {view['status'].title()}",
                    "detail": view["issue"] or "",
                    "action": f"open-representation:{kind}",
                }
            )

    for item in specifications.records:
        # Category schemas still measure completeness internally, but an absent vendor fact is
        # not a specification the component screen may invent. Only sourced facts can create a
        # specification attention item.
        if item["conflictState"] == "conflicting":
            offered = len(item["sourceCandidates"])
            items.append(
                {
                    "id": f"specification.conflict.{item['key']}",
                    "severity": "warning",
                    "title": f"Sources Disagree On {item['label']}",
                    "detail": f"{offered} values were offered and all are kept.",
                    "action": f"open-specification-sources:{item['key']}",
                }
            )
        if item["constraintViolation"]:
            items.append(
                {
                    "id": f"specification.constraint.{item['key']}",
                    "severity": "warning",
                    "title": f"{item['label']} Fails Its Constraint",
                    "detail": item["constraintViolation"],
                    "action": f"open-specification-sources:{item['key']}",
                }
            )

    if record.requires_override is not None:
        items.append(
            {
                "id": "requirements.override",
                "severity": "info",
                "title": "Requirements Are Overridden",
                "detail": "This component uses per-part requirements instead of its class default.",
                "action": "open-requirements",
            }
        )
    return items


def _quality_summary(
    record,
    schema: CategorySchema,
    specifications: Specifications,
    identity_values: Mapping[str, str],
) -> dict[str, Any]:
    counts = dict.fromkeys(VERIFICATION_STATES, 0)
    for item in specifications.records:
        if item["preferredValue"] is None:
            continue
        counts[item["verificationState"]] += 1
    attention = _attention(record, specifications, identity_values)
    missing_passport_fields = set(record.missing_fields())
    passport_labels = {
        "mpn": "MPN",
        "manufacturer": "manufacturer",
        "description": "value/description",
    }
    for key, label in passport_labels.items():
        if identity_values[key]:
            missing_passport_fields.discard(label)
        else:
            missing_passport_fields.add(label)
    return {
        "description": identity_values["description"],
        "completeness": dict(specifications.completeness),
        "stateCounts": counts,
        "attention": attention,
        "blockingCount": sum(1 for item in attention if item["severity"] == "blocking"),
        # The passport gate, which is about identity and sourcing and is deliberately NOT the
        # category completeness above: a part enters the library on its identity alone.
        "missingPassportFields": [
            label for _, label in REQUIRED_FIELDS if label in missing_passport_fields
        ],
    }


# Record-level sourced fields, and how they read. These are not specifications - they are
# identity and sourcing facts - but sources disagree about them, so their candidates are resolved
# by the same precedence and reported rather than silently settled.
_RECORD_FIELD_LABELS: dict[str, str] = {
    "mpn": "Manufacturer Part Number",
    "manufacturer": "Manufacturer",
    "display_name": "Display Name",
    "description": "Description",
    "value": "Value",
    "category": "Category",
    "datasheet_url": "Datasheet URL",
    "product_url": "Product URL",
    "stock": "Stock",
}


def _record_fields(record, specifications: Specifications) -> list[dict[str, Any]]:
    """Sourced record fields whose disagreements the specification sheet cannot show.

    A key already presented as a canonical specification is skipped: it has a row of its own,
    and repeating it here would be the same fact twice with two chances to disagree with itself.
    """
    presented = {item["key"] for item in specifications.records}
    out: list[dict[str, Any]] = []
    keys = set(getattr(record, "enrichment", None) or {}) | set(
        getattr(record, "alternates", None) or {}
    )
    for key in sorted(keys):
        definition = field_for(key)
        canonical = definition.key if definition is not None else normalize_key(key).replace(
            " ", "_"
        )
        if canonical in presented:
            continue
        value = getattr(record, key, None)
        if value is None:
            value = (getattr(record, "specs", None) or {}).get(key)
        label = _RECORD_FIELD_LABELS.get(key) or humanize(key)
        out.append(record_field(record, key, label, value))
    return out


def _identity_values(record, record_fields: list[dict[str, Any]]) -> dict[str, str]:
    """Identity facts safe to present, while unattributed legacy values stay readable."""
    values = {
        key: _text(getattr(record, key, ""))
        for key, _ in _BLOCKING_IDENTITY
    }
    for item in record_fields:
        key = str(item.get("key") or "")
        if key in values:
            # A sourced field participates in authority. Discovery-only evidence remains in
            # provenance but cannot leak back through the record's denormalized scalar value.
            values[key] = _text(item.get("preferredValue"))
    return values


def _entry_state(entry) -> str:
    raw = _text((getattr(entry, "extra", None) or {}).get("state")).strip().casefold()
    return raw if raw in SOURCE_STATES else "success"


def _source_ledger(
    record, resolved: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every source consulted, what happened to it, and how many fields it is answering for."""
    counts: dict[str, int] = {}
    for item in resolved:
        preferred = item.get("preferredSource") or {}
        source_id = _text(preferred.get("sourceId"))
        if source_id:
            counts[source_id] = counts.get(source_id, 0) + 1

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, entry in sorted((record.sources or {}).items()):
        seen.add(key)
        out.append(
            {
                "id": key,
                "label": source_label(key),
                "state": _entry_state(entry),
                "fieldCount": counts.get(key, 0),
                "fetchedAt": _text(getattr(entry, "fetched_at", "")),
                "payloadRef": _text(getattr(entry, "file", "")),
            }
        )
    # A source can win a field without its raw payload ever landing in the evidence index (an
    # API answer applied directly). Leaving it out would under-report the ledger: the field
    # sheet would name a source the source list does not admit exists.
    for key in sorted(set(counts) - seen):
        out.append(
            {
                "id": key,
                "label": source_label(key),
                "state": "success",
                "fieldCount": counts[key],
                "fetchedAt": "",
                "payloadRef": "",
            }
        )
    return out


def _diagnostics(record, schema: CategorySchema) -> dict[str, Any]:
    hashes = record.hashes
    return {
        "recordSchemaVersion": record.schema_version,
        "isFutureRecord": record.is_future_schema(),
        "derivedBy": record.derived_by,
        "hashes": {
            "symbolContent": hashes.symbol_content if hashes else "",
            "footprintContent": hashes.footprint_content if hashes else "",
            "modelFile": hashes.model_file if hashes else "",
        },
        # Keys written by a newer build. Surfaced rather than hidden: a reader must be able to
        # see that this record carries data this build did not understand.
        "unknownKeys": sorted(set(record.extra) | set(record.derived_extra)),
        "categorySchema": schema.key,
        "groups": [
            {"id": key, "label": label}
            for key, label in (*UNIVERSAL_GROUPS, *CATEGORY_GROUPS)
        ],
    }


def component_dossier(
    record,
    *,
    coverage: Mapping[str, Any] | None = None,
    official_payloads: Mapping[str, Any] | None = None,
    now: str = "",
) -> dict[str, Any]:
    """The whole opened-component presentation model for one record.

    `coverage` is `stockroom.provider_coverage.provider_coverage(...)` already computed by a
    caller that HAS the machine-local evidence store, passed in rather than reached for: this
    module still never opens a path. Omitting it is not an error and does not hide the section -
    it falls back to the coverage the record itself proves, which is the complete answer for a
    caller with no store and an honest subset for one that has evidence it did not hand over.

    `now` is the reading clock for offer freshness, passed in for the same reason: a projection
    that read the clock itself could not be tested, and with no clock the answer is honestly
    `unknown` rather than computed against a guess.
    """
    schema = resolve_schema(record)
    specifications = build_specifications(record, schema)
    key_specifications = [
        item for item in specifications.key_specifications if item["preferredValue"] is not None
    ]
    specification_groups = []
    for group in specifications.groups:
        rows = [
            item
            for item in group["specifications"]
            if item["preferredValue"] is not None
        ]
        if rows:
            specification_groups.append({**group, "specifications": rows, "count": len(rows)})
    record_fields = _record_fields(record, specifications)
    identity_values = _identity_values(record, record_fields)
    resolved = [*specifications.records, *record_fields]
    documents = build_documents(record)
    offers = build_offers(record, now=now)
    # Resolved ONCE and handed to both readers: the CAD column decides its preferred source
    # against this same document, so the provider a comparison row offers and the provider the
    # preference will accept are answered from one reading of the evidence.
    sources = dict(coverage) if coverage is not None else provider_coverage(record)
    return {
        "schemaVersion": DOSSIER_SCHEMA_VERSION,
        "identity": _identity(record, schema, specifications, identity_values),
        "qualitySummary": _quality_summary(
            record, schema, specifications, identity_values
        ),
        # The screen lists facts a permitted source actually supplied. Expected/recommended
        # schema gaps remain in completeness diagnostics, never as fabricated `Missing` rows.
        "keySpecifications": key_specifications,
        "specificationGroups": specification_groups,
        "cadAssets": build_cad_assets(record, schema, sources),
        "cadSourceCoverage": sources,
        "supplySummary": supply_summary(
            offers,
            manufacturer_status=manufacturer_status(record),
            source_failures=indexed_source_failures(record, offers),
        ),
        "distributorOffers": offers,
        # Every leaf from every retained official response. The caller reads bytes and passes the
        # payloads in, preserving this projection's no-I/O boundary.
        "officialApiData": build_official_evidence(
            official_payloads,
            source_entries=getattr(record, "sources", None),
        ),
        "documents": documents,
        "relatedParts": build_related_parts(record, specifications),
        "provenance": {
            "sources": _source_ledger(record, resolved),
            # Identity and sourcing facts sources disagree about. Not specifications, and
            # deliberately not shown as such - but never settled in silence either.
            "recordFields": record_fields,
            # Every unsettled disagreement, as fields with named answers rather than as a state
            # word on a key. A surface renders these; it never re-derives which side won.
            "conflicts": build_conflicts(resolved),
            "manualOverrides": manual_overrides(record),
            # What a record this build does not fully understand MEANS, translated here so no
            # surface has to turn a schema number into a sentence.
            "compatibility": build_compatibility(record),
            "raw": build_raw_levels(record, resolved, specifications.unmapped),
        },
        "revisions": build_revisions(record, documents["items"]),
        "diagnostics": {
            **_diagnostics(record, schema),
            "pinout": list(specifications.pinout),
            "pinCount": len(specifications.pinout),
            "facets": list(schema.facets),
            "comparisonFields": list(schema.comparison),
        },
    }


__all__ = ["component_dossier"]
