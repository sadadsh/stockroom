"""The component workspace: one normalized presentation read model of a `PartRecord`.

`PartRecord` is the right shape for storage, provenance, git history, derivation, and EDA
output. It is the wrong shape for a screen. Serving `record.to_dict()` forced the frontend to
decide what counts as identity, what belongs beside a specification, which provider payload
deserves a card, and which disagreements matter - so those decisions were made repeatedly,
inconsistently, and in a component that also had to render.

This module makes those decisions once, in one tested place. It is a pure projection:

    * it never writes, never reads the filesystem, and never calls a network source;
    * it never becomes a second source of truth - nothing here is persisted back;
    * every canonical record field has exactly one declared destination (`DATA_DESTINATIONS`),
      so a field can never be silently dropped from the product.

The raw record endpoint stays available for compatibility and diagnostics. The opened-component
UI reads this instead.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from stockroom.eda.registry import all_tools, get_tool
from stockroom.enrich.schema import SOURCE_STATES
from stockroom.model.asset import ASSET_KINDS, Asset
from stockroom.model.trust import Verdict, asset_verdict
from stockroom.providers import provider_label

# Bump when the workspace shape changes in a way a reader must notice. The frontend mirrors
# this exact number so a stale client can degrade honestly instead of misreading a new shape.
WORKSPACE_SCHEMA_VERSION = 1

# ------------------------------------------------------------------ vocabularies

# One fact's agreement state. Deliberately closed: "how sure are we" is answered by naming the
# situation, never by a fabricated confidence percentage.
FACT_STATES: frozenset[str] = frozenset(
    {"verified", "agrees", "conflict", "manual", "unknown", "stale"}
)

# One representation's readiness. "review" means Stockroom TRIED to measure and could not -
# which is a different, weaker statement than "this is wrong" (`failed`).
REPRESENTATION_STATUSES: frozenset[str] = frozenset(
    {"ready", "review", "missing", "failed", "not_required"}
)

# Specification groups, in display order. `other` exists only for genuinely uncategorized keys
# and must stay small; a key that keeps landing there wants a rule below, not a bigger bucket.
SPEC_GROUPS: tuple[tuple[str, str], ...] = (
    ("electrical", "Electrical"),
    ("device", "Device"),
    ("physical", "Physical"),
    ("ratings", "Ratings & Compliance"),
    ("other", "Other"),
)

# Substring rules, first match wins, checked against the case-folded spec key. Trade and
# compliance facts deliberately do NOT live here: they are sourcing facts and are projected
# into the sourcing view instead, so a buyer's question is answered where buying happens.
_SPEC_GROUP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "electrical",
        (
            "voltage", "current", "power", "resistance", "capacitance", "inductance",
            "frequency", "impedance", "gain", "noise", "bandwidth", "slew", "ripple",
            "leakage", "threshold", "hysteresis", "duty", "esr", "charge", "energy",
        ),
    ),
    (
        "physical",
        (
            "package", "mount", "size", "dimension", "height", "width", "length", "pitch",
            "pin count", "pins", "terminal", "lead", "body", "weight", "case", "footprint",
            "orientation", "termination",
        ),
    ),
    (
        "ratings",
        (
            "temperature", "tolerance", "rating", "rohs", "reach", "msl", "esd", "grade",
            "qualification", "aec", "humidity", "moisture", "lifecycle", "compliance",
            "operating", "storage",
        ),
    ),
    (
        "device",
        (
            "type", "family", "series", "function", "channel", "interface", "protocol",
            "core", "architecture", "memory", "flash", "ram", "speed", "resolution",
            "output", "input", "configuration", "topology", "polarity", "logic",
        ),
    ),
)

# Spec keys that are bookkeeping rather than an engineering fact about the part. They stay in
# the record (they are real provider data) but never render as a specification row.
_SPEC_BOOKKEEPING: frozenset[str] = frozenset(
    {"image", "product category", "pinout", "datasheet", "datasheet url", "product url"}
)

# Canonical catalogue relationship keys -> the product concept the UI shows. Provider payloads
# are normalized THROUGH this map, so no presentation code ever reads `catalog["digikey"]`.
_RELATIONSHIP_KINDS: tuple[tuple[str, str, str], ...] = (
    ("alternate_packaging", "alternatePackaging", "Alternate Packaging"),
    ("substitutions", "substitutions", "Potential Substitutions"),
    ("recommended_products", "recommendations", "Recommendations"),
    ("associations", "associations", "Associated Products"),
)


# ------------------------------------------------------------------ destinations

# Every canonical `PartRecord` field, and the ONE place the product presents it. A field with
# no entry here is a field the product forgot; `tests/backend/test_workspace.py` fails on it.
# "diagnostics" is a real destination - technical truth the owner can still reach - but it is
# never a dumping ground for something a person would look for elsewhere.
DATA_DESTINATIONS: dict[str, str] = {
    "id": "identity",
    "display_name": "identity.displayName",
    "mpn": "identity.mpn",
    "manufacturer": "identity.manufacturer",
    "category": "identity.category",
    "part_class": "identity.partClass",
    "value": "identity.value",
    "description": "summary.description",
    "specs": "specifications",
    "tags": "identity.tags",
    "requires_override": "attention",
    "assets": "representations",
    "cad_variants": "representations.tools",
    "datasheet": "sources.records",
    "purchase": "sourcing.offers",
    "catalog": "sourcing",
    "enrichment": "sources.fields",
    "alternates": "sources.fields.alternates",
    "sources": "sources.records",
    "provenance": "sources.records",
    "hashes": "sources.diagnostics",
    "derived_at": "sources.diagnostics",
    "derived_by": "sources.diagnostics",
    "derived_extra": "sources.diagnostics",
    "schema_version": "sources.diagnostics",
    "extra": "sources.diagnostics",
}


# ------------------------------------------------------------------ small helpers


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _format(value: object) -> str:
    """The display form of a stored value.

    Structured values (a pinout list, a nested provider blob) are NOT flattened into a fake
    one-line string here: they have their own presentation, and a stringified dict on a
    specification row is noise pretending to be data.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple, dict)):
        return ""
    return str(value)


def _source_view(source_id: str, fetched_at: str = "") -> dict[str, Any] | None:
    source_id = _text(source_id).strip()
    if not source_id:
        return None
    return {
        "id": source_id,
        "label": provider_label(source_id),
        "fetchedAt": _text(fetched_at) or None,
    }


def fact(
    fact_id: str,
    label: str,
    raw_value: object,
    *,
    source_id: str = "",
    fetched_at: str = "",
    alternates: Sequence[Mapping[str, Any]] = (),
    unit: str | None = None,
    state: str = "",
) -> dict[str, Any]:
    """One presented datum, with where it came from and what else was offered for it.

    The state is DERIVED from the evidence rather than asserted by the caller unless the caller
    knows better: more than one distinct answer is a conflict, a value with no source is manual
    when it exists at all, and a value nobody supplied is unknown.
    """
    others = [dict(entry) for entry in alternates]
    if not state:
        if others:
            state = "conflict"
        elif raw_value in (None, ""):
            state = "unknown"
        elif source_id:
            state = "agrees"
        else:
            state = "manual"
    if state not in FACT_STATES:
        raise ValueError(f"unknown fact state: {state!r}")
    return {
        "id": fact_id,
        "label": label,
        "rawValue": raw_value,
        "formattedValue": _format(raw_value),
        "unit": unit,
        "source": _source_view(source_id, fetched_at),
        "alternates": others,
        "state": state,
    }


def _alternates_for(record, key: str) -> list[dict[str, Any]]:
    """Every value a source offered for `key` and lost with.

    The winning value is repeated as the first stored entry (see `PartRecord.alternates`), so
    it is dropped here: an "alternate" that is the value already on screen is not an
    alternative, and showing it as one manufactures a disagreement that does not exist.
    """
    entries = record.alternates.get(key) or []
    if len(entries) < 2:
        return []
    return [
        {
            "rawValue": entry.value,
            "formattedValue": _format(entry.value),
            "sourceId": entry.source,
            "sourceLabel": provider_label(entry.source),
        }
        for entry in entries[1:]
    ]


def _record_fact(record, key: str, label: str, value: object) -> dict[str, Any]:
    enrichment = record.enrichment.get(key)
    return fact(
        key,
        label,
        value,
        source_id=enrichment.source if enrichment else "",
        alternates=_alternates_for(record, key),
    )


# ------------------------------------------------------------------ identity


def _identity(record) -> dict[str, Any]:
    specs = record.specs or {}
    package = specs.get("package") or specs.get("Package") or None
    pin_count = specs.get("pin_count") or specs.get("pins") or None
    try:
        pin_count = int(pin_count) if pin_count not in (None, "") else None
    except (TypeError, ValueError):
        pin_count = None
    return {
        "id": record.id,
        "displayName": record.display_name or record.mpn or record.id,
        "mpn": record.mpn,
        "manufacturer": record.manufacturer,
        "category": record.category,
        "partClass": str(record.part_class),
        "value": record.value,
        "package": _text(package) or None,
        "pinCount": pin_count,
        "lifecycle": _text(specs.get("lifecycle")) or None,
        "tags": list(record.tags),
    }


def _summary(record) -> dict[str, Any]:
    return {
        "description": _record_fact(record, "description", "Description", record.description),
        "datasheetUrl": (record.datasheet.source_url if record.datasheet else "") or "",
        "datasheetFile": (record.datasheet.file if record.datasheet else "") or "",
    }


# ------------------------------------------------------------------ representations


def _asset_status(asset: Asset | None, *, required: bool) -> str:
    if asset is None or not asset.is_present():
        return "missing" if required else "not_required"
    verdict = asset_verdict(asset)
    if verdict is Verdict.FAIL:
        return "failed"
    # An asset carrying checks that could not measure is honestly "unreviewed", which is a
    # weaker claim than ready. An asset nobody ever measured is not accused of anything.
    if verdict is Verdict.UNKNOWN and asset.checks:
        return "review"
    return "ready"


# Worst first: one failing tool must not be hidden behind another tool's clean result.
_STATUS_RANK: tuple[str, ...] = ("failed", "review", "missing", "ready", "not_required")


def _tool_supports(tool, kind: str) -> bool:
    """True when this tool has a real slot for `kind`.

    A tool that carries the asset INSIDE another file (Altium embeds the 3D model in the
    footprint library) still supports it - it just does not store it separately, which the
    tool view reports as `embedded` rather than pretending the asset is missing.
    """
    if kind in getattr(tool, "unsupported_assets", {}):
        return False
    return kind in ASSET_KINDS


def _representation(record, kind: str) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    statuses: list[str] = []
    for tool in all_tools():
        if not _tool_supports(tool, kind):
            continue
        needed = kind in record.needs(tool.key)
        asset = record.assets_for(tool.key).get(kind)
        status = _asset_status(asset, required=needed)
        statuses.append(status)
        origin = asset.origin if asset is not None else None
        embedded = kind in getattr(tool, "embedded_assets", {})
        tools.append(
            {
                "tool": tool.key,
                "toolLabel": tool.label,
                "status": status,
                "present": bool(asset is not None and asset.is_present()),
                "embedded": embedded,
                "reference": {
                    "lib": asset.lib if asset else "",
                    "name": asset.name if asset else "",
                    "file": asset.file if asset else "",
                },
                "sourceId": origin.vendor if origin else "",
                "sourceLabel": provider_label(origin.vendor) if origin else "",
                "sourceUrl": origin.url if origin else "",
                "capturedAt": origin.captured_at if origin else "",
                "checks": [
                    {
                        "check": check.check,
                        "measured": check.measured,
                        "expected": check.expected,
                        "against": check.against,
                        "checkedAt": check.checked_at,
                        "note": check.note,
                    }
                    for check in (asset.checks if asset else [])
                ],
            }
        )

    status = next((s for s in _STATUS_RANK if s in statuses), "not_required")
    selected = next(
        (view for view in tools if view["status"] == "ready"),
        next((view for view in tools if view["present"]), None),
    )
    issue = None
    if status == "missing":
        issue = "No file is attached yet."
    elif status == "failed":
        issue = "A recorded check did not pass."
    elif status == "review":
        issue = "A recorded check could not be measured."
    return {
        "kind": kind,
        "status": status,
        "selectedTool": (selected or {}).get("tool", "") or "shared",
        "tools": tools,
        "sourceLabel": (selected or {}).get("sourceLabel", ""),
        "issue": issue,
        # Retained candidates are counted by the capture layer; the workspace reports only what
        # the record itself proves, so this is never an invented number.
        "alternativeCount": 0,
    }


def _representations(record) -> dict[str, Any]:
    return {kind: _representation(record, kind) for kind in ASSET_KINDS}


# ------------------------------------------------------------------ specifications


def _spec_group(key: str) -> str:
    folded = key.casefold()
    for group, needles in _SPEC_GROUP_RULES:
        if any(needle in folded for needle in needles):
            return group
    return "other"


def _specifications(record) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in SPEC_GROUPS}
    pinout: list[dict[str, Any]] = []
    for key, value in sorted((record.specs or {}).items()):
        if key.casefold() == "pinout":
            if isinstance(value, list):
                pinout = [dict(entry) for entry in value if isinstance(entry, dict)]
            continue
        if key.casefold() in _SPEC_BOOKKEEPING:
            continue
        if isinstance(value, (list, dict)):
            # Structured leftovers have no specification row; they stay reachable as raw
            # record data under diagnostics rather than rendering as an empty cell.
            continue
        groups[_spec_group(key)].append(
            _record_fact(record, key, key.replace("_", " ").strip().title(), value)
        )
    return {
        "groups": [
            {"id": key, "label": label, "facts": groups[key], "count": len(groups[key])}
            for key, label in SPEC_GROUPS
            if groups[key]
        ],
        "total": sum(len(items) for items in groups.values()),
        "pinout": pinout,
        "pinCount": len(pinout),
    }


# ------------------------------------------------------------------ sourcing


def _offers(record) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for entry in record.purchase:
        vendor = _text(entry.vendor)
        offers.append(
            {
                "sourceId": vendor.casefold(),
                "sourceLabel": provider_label(vendor.casefold()) if vendor else "",
                "partNumber": entry.part_number,
                "url": entry.url,
                "stock": entry.stock,
                "currency": entry.currency or "USD",
                "priceBreaks": [
                    {
                        "qty": break_entry.get("qty"),
                        "price": break_entry.get("price"),
                    }
                    for break_entry in (entry.price_breaks or [])
                    if isinstance(break_entry, dict)
                ],
                "fetchedAt": entry.fetched_at,
            }
        )
    offers.sort(key=lambda item: item["sourceLabel"].casefold())
    return offers


def _catalog_entries(
    catalog: Mapping[str, Any], key: str
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Every catalogue list entry under `key`, paired with the provider that supplied it."""
    for provider_key, payload in catalog.items():
        if not isinstance(payload, Mapping):
            continue
        for item in payload.get(key) or []:
            if isinstance(item, Mapping):
                yield str(provider_key), item


def _relationships(record) -> list[dict[str, Any]]:
    """Provider catalogue relationships, normalized into product concepts.

    Nothing here claims equivalence. A distributor's "substitution" is a suggestion made by a
    distributor, and it is labelled as one: Stockroom has not validated that the part is
    electrically or mechanically interchangeable, and must never imply that it has.
    """
    catalog = record.catalog or {}
    out: list[dict[str, Any]] = []
    for source_key, view_key, label in _RELATIONSHIP_KINDS:
        items: list[dict[str, Any]] = []
        for provider_key, item in _catalog_entries(catalog, source_key):
            items.append(
                {
                    "mpn": _text(item.get("manufacturer_product_number") or item.get("mpn")),
                    "manufacturer": _text(item.get("manufacturer")),
                    "description": _text(item.get("description")),
                    "url": _text(item.get("product_url") or item.get("url")),
                    "sourceId": provider_key,
                    "sourceLabel": provider_label(provider_key),
                }
            )
        if items:
            out.append({"id": view_key, "label": label, "items": items, "count": len(items)})
    return out


def _resources(record) -> list[dict[str, Any]]:
    """Provider-published resource links (CAD pages, drawings, media), provider-neutral."""
    out: list[dict[str, Any]] = []
    for provider_key, item in _catalog_entries(record.catalog or {}, "media"):
        url = _text(item.get("url"))
        if not url.startswith("https://"):
            continue
        out.append(
            {
                "title": _text(item.get("title")) or url,
                "url": url,
                "sourceId": provider_key,
                "sourceLabel": provider_label(provider_key),
            }
        )
    return out


def _sourcing(record) -> dict[str, Any]:
    specs = record.specs or {}
    shared = [
        _record_fact(record, "lifecycle", "Lifecycle", specs.get("lifecycle")),
        _record_fact(record, "lead_time", "Lead Time", specs.get("lead_time")),
        _record_fact(
            record, "country_of_origin", "Country Of Origin", specs.get("country_of_origin")
        ),
        _record_fact(record, "tariff_rate", "Tariff Rate", specs.get("tariff_rate")),
        _record_fact(record, "rohs", "RoHS", specs.get("RoHS") or specs.get("rohs")),
        _record_fact(record, "reach", "REACH", specs.get("REACH") or specs.get("reach")),
    ]
    return {
        "offers": _offers(record),
        "shared": [item for item in shared if item["rawValue"] not in (None, "")],
        "relationships": _relationships(record),
        "resources": _resources(record),
    }


# ------------------------------------------------------------------ sources


def _field_sources(record) -> list[dict[str, Any]]:
    keys = sorted(set(record.enrichment) | set(record.alternates))
    out = []
    for key in keys:
        enrichment = record.enrichment.get(key)
        value = getattr(record, key, None)
        if value is None:
            value = (record.specs or {}).get(key)
        out.append(
            fact(
                key,
                key.replace("_", " ").strip().title(),
                value,
                source_id=enrichment.source if enrichment else "",
                alternates=_alternates_for(record, key),
            )
        )
    return out


def _entry_state(entry) -> str:
    """What actually happened to one consulted source.

    The vocabulary is `stockroom.enrich.schema.SOURCE_STATES`, and it is READ, never guessed: a
    build that recorded the outcome alongside the evidence index carries it in the entry's
    `extra`, and the projection surfaces exactly that. An entry with no recorded outcome but a
    stored payload proves only one thing - the source answered - so it reads `success`. Nothing
    here infers a failure from an absence, because "we have no evidence from Mouser" and "Mouser
    failed" are different sentences and only the source itself can tell them apart.
    """
    raw = _text((getattr(entry, "extra", None) or {}).get("state")).strip().casefold()
    return raw if raw in SOURCE_STATES else "success"


def _field_counts(fields: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """How many presented fields each source is currently answering for."""
    counts: dict[str, int] = {}
    for item in fields:
        source = item.get("source") or {}
        source_id = _text(source.get("id"))
        if source_id:
            counts[source_id] = counts.get(source_id, 0) + 1
    return counts


def _source_records(record, field_counts: Mapping[str, int]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for key, entry in sorted((record.sources or {}).items()):
        seen.add(key)
        out.append(
            {
                "id": key,
                "label": provider_label(key),
                "state": _entry_state(entry),
                "fieldCount": field_counts.get(key, 0),
                "fetchedAt": getattr(entry, "fetched_at", "") or "",
                "file": getattr(entry, "file", "") or "",
            }
        )
    # A source can win a field without its raw payload ever landing in the evidence index (an
    # API answer applied directly). Leaving it out would under-report the ledger: the field
    # sheet would name a source the source list does not admit exists.
    for key in sorted(set(field_counts) - seen):
        out.append(
            {
                "id": key,
                "label": provider_label(key),
                "state": "success",
                "fieldCount": field_counts[key],
                "fetchedAt": "",
                "file": "",
            }
        )
    if record.datasheet is not None:
        out.append(
            {
                "id": "datasheet",
                "label": "Datasheet",
                "state": "success",
                "fieldCount": field_counts.get("datasheet", 0),
                "fetchedAt": record.datasheet.fetched_at,
                "file": record.datasheet.file,
                "url": record.datasheet.source_url,
            }
        )
    if record.provenance is not None:
        out.append(
            {
                "id": "provenance",
                "label": provider_label(record.provenance.source) or "Original Package",
                "state": "success",
                "fieldCount": field_counts.get("provenance", 0),
                "fetchedAt": record.provenance.ingested_at,
                "file": "",
                "url": record.provenance.source_url,
                "digest": record.provenance.original_zip_sha256,
            }
        )
    return out


def _diagnostics(record) -> dict[str, Any]:
    hashes = record.hashes
    return {
        "schemaVersion": record.schema_version,
        "derivedAt": record.derived_at,
        "derivedBy": record.derived_by,
        "hashes": {
            "symbolContent": hashes.symbol_content if hashes else "",
            "footprintContent": hashes.footprint_content if hashes else "",
            "modelFile": hashes.model_file if hashes else "",
        },
        # Keys written by a newer build. Surfaced rather than hidden: a reader must be able to
        # see that this record carries data this build did not understand.
        "unknownKeys": sorted(set(record.extra) | set(record.derived_extra)),
    }


def _sources(record) -> dict[str, Any]:
    fields = _field_sources(record)
    return {
        "fields": fields,
        "records": _source_records(record, _field_counts(fields)),
        "diagnostics": _diagnostics(record),
    }


# ------------------------------------------------------------------ attention


def _attention(record) -> list[dict[str, Any]]:
    """Only unresolved, actionable problems. Every item names what to do about it."""
    items: list[dict[str, Any]] = []
    for field_name, label in (
        ("mpn", "Manufacturer Part Number"),
        ("manufacturer", "Manufacturer"),
        ("description", "Description"),
    ):
        if not getattr(record, field_name, ""):
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
        view = _representation(record, kind)
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

    for key, entries in sorted((record.alternates or {}).items()):
        if len(entries) > 1:
            items.append(
                {
                    "id": f"conflict.{key}",
                    "severity": "warning",
                    "title": f"Sources Disagree On {key.replace('_', ' ').title()}",
                    "detail": f"{len(entries)} values were offered.",
                    "action": f"open-field-source:{key}",
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


# ------------------------------------------------------------------ entry point


def component_workspace(record) -> dict[str, Any]:
    """The whole opened-component presentation model for one record."""
    return {
        "schemaVersion": WORKSPACE_SCHEMA_VERSION,
        "identity": _identity(record),
        "summary": _summary(record),
        "representations": _representations(record),
        "specifications": _specifications(record),
        "sourcing": _sourcing(record),
        "sources": _sources(record),
        "attention": _attention(record),
    }


__all__ = [
    "DATA_DESTINATIONS",
    "FACT_STATES",
    "REPRESENTATION_STATUSES",
    "SOURCE_STATES",
    "SPEC_GROUPS",
    "WORKSPACE_SCHEMA_VERSION",
    "component_workspace",
    "fact",
]
