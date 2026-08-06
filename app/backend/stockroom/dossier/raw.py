"""Raw data, preserved at three levels, each with its own job.

Level one - CANONICAL. The normalized specifications: one field, one meaning, one unit, whoever
supplied it. This is what a person reads and what a search filters on.

Level two - SOURCE-SPECIFIC. Fields a source really sent that no canonical field claims yet.
They are kept with the source's own key and the source's own value, because the alternative is
discarding vendor data, and the owner's rule is that everything a source gave us is kept. This
level is also the backlog: a key that keeps appearing here wants a field definition.

Level three - EVIDENCE. For every candidate answer: the key the source used, the value it sent,
when it was retrieved, which stored payload it came out of, which parser produced it, what
normalization made of it, and which other answer it disagrees with. This is what makes a value
auditable back to the bytes a vendor returned.

The payload is REFERENCED, never inlined. `sourced/<id>/<source>.json` holds the bytes; copying
them here would put a megabyte of vendor JSON on a screen read once a month, and the whole point
of the evidence tree is that the payload lives in exactly one place.

None of this is the normal way to read the part. Raw JSON as a UI fallback is what the dossier
exists to replace; these levels are reachable, technical truth, not a substitute for the sheet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from stockroom.dossier.fields import humanize
from stockroom.dossier.specifications import source_label
from stockroom.enrich.schema import SCHEMA_VERSION as ENRICH_SCHEMA_VERSION

RAW_LEVELS: tuple[tuple[str, str], ...] = (
    ("canonical", "Canonical Normalized Specifications"),
    ("source_fields", "Source Fields With No Canonical Mapping"),
    ("evidence", "Raw Source Evidence"),
)


def _payload_reference(record, source_id: str) -> dict[str, str]:
    """Where the bytes behind one source live, without carrying any of them."""
    entry = (getattr(record, "sources", None) or {}).get(source_id)
    if entry is None:
        return {"file": "", "fetchedAt": "", "endpoint": ""}
    extra = getattr(entry, "extra", None) or {}
    return {
        "file": str(getattr(entry, "file", "") or ""),
        "fetchedAt": str(getattr(entry, "fetched_at", "") or ""),
        # An adapter that recorded which endpoint or page answered keeps it in its own extra
        # keys; nothing is invented when it did not.
        "endpoint": str(extra.get("endpoint") or extra.get("url") or ""),
    }


def build_evidence(record, specifications: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One evidence row per candidate answer, in specification order."""
    parser_version = f"enrich/{ENRICH_SCHEMA_VERSION}"
    derived_by = str(getattr(record, "derived_by", "") or "")
    out: list[dict[str, Any]] = []
    for specification in specifications:
        candidates = list(specification.get("sourceCandidates") or [])
        if not candidates:
            continue
        preferred = specification.get("preferredSource") or {}
        for candidate in candidates:
            source_id = str(candidate.get("sourceId") or "")
            payload = _payload_reference(record, source_id)
            out.append(
                {
                    "field": specification.get("key"),
                    "originalKey": candidate.get("originalKey"),
                    "originalValue": candidate.get("value"),
                    "retrievedAt": candidate.get("retrievedAt") or payload["fetchedAt"],
                    "sourceId": source_id,
                    "sourceLabel": source_label(source_id),
                    "sourceTier": candidate.get("tier"),
                    "payloadRef": payload["file"],
                    "endpoint": payload["endpoint"],
                    "parserVersion": parser_version,
                    "derivedBy": derived_by,
                    "normalizationResult": {
                        "displayValue": candidate.get("displayValue"),
                        "normalizedValue": candidate.get("normalizedValue"),
                        "unit": candidate.get("unit"),
                    },
                    # Which answer this one lost to, and only when it actually lost. A candidate
                    # that agrees with the value in force is not in conflict with anything.
                    "conflictsWith": (
                        preferred.get("sourceId")
                        if specification.get("conflictState") in {"conflicting", "resolved"}
                        and candidate.get("sourceId") != preferred.get("sourceId")
                        else None
                    ),
                }
            )
    return out


def build_raw_levels(
    record,
    specifications: Sequence[Mapping[str, Any]],
    unmapped: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The three preservation levels, each reporting what it is holding."""
    canonical = [item for item in specifications if item.get("mapped")]
    evidence = build_evidence(record, specifications)
    return {
        "levels": [{"id": key, "label": label} for key, label in RAW_LEVELS],
        "canonical": {
            "count": len(canonical),
            "fields": [item.get("key") for item in canonical],
        },
        "sourceFields": {
            "count": len(unmapped),
            "items": [dict(item) for item in unmapped],
        },
        "evidence": {
            "count": len(evidence),
            "items": evidence,
        },
    }


def build_conflicts(resolved: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every field whose sources disagree, with all the answers that were offered.

    A conflict is reported as a FIELD with several answers, not as a warning with a key in it.
    "Sources disagree about Tolerance: Mouser says 1 %, the datasheet says 0.5 %" is something a
    person can settle; `conflictState: conflicting` on `tolerance` is not.
    """
    out: list[dict[str, Any]] = []
    for item in resolved:
        if item.get("conflictState") != "conflicting":
            continue
        preferred = item.get("preferredSource") or {}
        in_force = preferred.get("displayValue")
        out.append(
            {
                "field": item.get("key") or "",
                "label": item.get("label") or humanize(item.get("key")),
                "group": item.get("groupLabel") or "",
                "inForce": item.get("displayValue") or "",
                "inForceSource": preferred.get("sourceLabel") or preferred.get("sourceId") or "",
                "candidates": [
                    {
                        "sourceId": candidate.get("sourceId") or "",
                        "sourceLabel": candidate.get("sourceLabel")
                        or source_label(str(candidate.get("sourceId") or "")),
                        "displayValue": candidate.get("displayValue") or "",
                        # Whether this answer is the one currently in force, so a surface can show
                        # the disagreement without re-deciding which side won.
                        "inForce": candidate.get("displayValue") == in_force
                        and candidate.get("sourceId") == preferred.get("sourceId"),
                    }
                    for candidate in (item.get("sourceCandidates") or [])
                ],
            }
        )
    return out


def build_compatibility(record) -> dict[str, Any]:
    """What "written by a newer build" means for the person reading this component.

    `unknownKeys` is a list of raw storage keys, and a raw storage key is not something anyone can
    act on - nor is a schema number. What IS actionable is how many fields this build cannot edit
    and what those fields are CALLED, so that is what travels here. The keys themselves stay in
    diagnostics, which is where machine-oriented text belongs.
    """
    fields = [
        {"key": key, "label": humanize(key), "origin": origin}
        for origin, mapping in (
            ("record", getattr(record, "extra", None) or {}),
            ("derived", getattr(record, "derived_extra", None) or {}),
        )
        for key in sorted(mapping)
    ]
    is_future = bool(getattr(record, "is_future_schema", lambda: False)())
    return {
        "isFutureRecord": is_future,
        "readOnlyFieldCount": len(fields),
        "fields": fields,
        # True only when there is something to say. A record this build understands completely
        # produces no notice at all rather than a reassuring one nobody needs to read.
        "hasNotice": is_future or bool(fields),
    }


__all__ = [
    "RAW_LEVELS",
    "build_compatibility",
    "build_conflicts",
    "build_evidence",
    "build_raw_levels",
]
