"""The part's own history, assembled only from what the record can prove.

Stockroom does not keep a change log inside the record - the library is a git repository and
that is where history lives. What the record CAN prove is a set of dated events: when it was
imported, when each source last answered, when each document was retrieved or verified, when a
person overrode a field, and when the derivation last ran. Ordered, those events are the honest
answer to "what has happened to this part", and none of them is invented.

An event with no timestamp is still emitted, with an empty date and sorted last. Dropping it
would lose a real event because a source forgot to stamp it, and a fabricated date would be
worse than no date at all.
"""

from __future__ import annotations

from typing import Any

from stockroom.providers import provider_label

# What kinds of things happen to a part. Closed, so a timeline row always renders.
REVISION_KINDS: tuple[tuple[str, str], ...] = (
    ("imported", "Imported"),
    ("source_fetched", "Source Read"),
    ("document_retrieved", "Document Retrieved"),
    ("document_verified", "Document Verified"),
    ("manual_override", "Field Overridden"),
    ("cad_captured", "CAD Captured"),
    ("derived", "Derivation Ran"),
)
REVISION_LABELS: dict[str, str] = dict(REVISION_KINDS)

# Which history an event belongs to. Two different questions live in one timeline: "where did this
# data come from" and "what has changed since". Splitting them here rather than in a surface means
# both histories are the projection's answer, and a new event kind cannot land in neither.
REVISION_SECTIONS: dict[str, tuple[str, str]] = {
    "imported": ("intake", "Import and Enrichment History"),
    "source_fetched": ("intake", "Import and Enrichment History"),
    "derived": ("intake", "Import and Enrichment History"),
    "document_retrieved": ("changes", "Revision History"),
    "document_verified": ("changes", "Revision History"),
    "manual_override": ("changes", "Revision History"),
    "cad_captured": ("changes", "Revision History"),
}


def _event(kind: str, at: str, summary: str, detail: str = "") -> dict[str, Any]:
    section, section_label = REVISION_SECTIONS[kind]
    return {
        "kind": kind,
        "kindLabel": REVISION_LABELS[kind],
        "section": section,
        "sectionLabel": section_label,
        "at": at or "",
        "summary": summary,
        "detail": detail,
    }


def manual_overrides(record) -> list[dict[str, Any]]:
    """Every reviewed decision in force, with who made it and what it displaced.

    Two kinds of decision live in the same place and are reported apart. "The answer is 0.5%" and
    "believe Mouser about this" are different claims, and rendering the second as a value would
    show a blank where a real answer is in force.
    """
    from stockroom.dossier.specifications import source_label

    out: list[dict[str, Any]] = []
    for key, override in sorted((getattr(record, "overrides", None) or {}).items()):
        replaced_source = str(getattr(override, "replaced_source", "") or "")
        preferred = str(getattr(override, "preferred_source", "") or "")
        out.append(
            {
                "field": key,
                "value": override.value,
                # False when this entry only pins a source: there is no manual value to show.
                "hasValue": bool(getattr(override, "has_value", True)),
                "preferredSource": preferred,
                "preferredSourceLabel": source_label(preferred) if preferred else "",
                "replacedValue": getattr(override, "replaced_value", None),
                "replacedSource": replaced_source,
                "replacedSourceLabel": source_label(replaced_source) if replaced_source else "",
                "note": override.note,
                "reviewedBy": override.reviewed_by,
                "reviewedAt": override.reviewed_at,
            }
        )
    return out


def build_revisions(record, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The dated events this record proves, newest first."""
    events: list[dict[str, Any]] = []

    provenance = getattr(record, "provenance", None)
    if provenance is not None and (provenance.ingested_at or provenance.source):
        origin_label = (
            provider_label(provenance.source) or provenance.source or "an import package"
        )
        events.append(
            _event(
                "imported",
                provenance.ingested_at or "",
                f"Imported from {origin_label}",
                provenance.source_url or "",
            )
        )

    for key, entry in sorted((getattr(record, "sources", None) or {}).items()):
        fetched = str(getattr(entry, "fetched_at", "") or "")
        events.append(
            _event(
                "source_fetched",
                fetched,
                f"{provider_label(key) or key} supplied data",
                str(getattr(entry, "file", "") or ""),
            )
        )

    for document in documents:
        if document.get("retrievedAt"):
            events.append(
                _event(
                    "document_retrieved",
                    document["retrievedAt"],
                    f"{document['documentTypeLabel']} retrieved",
                    document.get("revision") or document.get("title") or "",
                )
            )
        if document.get("verifiedAt"):
            events.append(
                _event(
                    "document_verified",
                    document["verifiedAt"],
                    f"{document['documentTypeLabel']} verified",
                    document.get("revision") or document.get("title") or "",
                )
            )

    for override in manual_overrides(record):
        by = override["reviewedBy"] or "a reviewer"
        # A pin and a typed value are different events. Calling both "set" would put a value in
        # the timeline that nobody entered.
        summary = (
            f"{override['field']} set by {by}"
            if override["hasValue"]
            else f"{override['field']} pinned to "
            f"{override['preferredSourceLabel'] or override['preferredSource']} by {by}"
        )
        events.append(_event("manual_override", override["reviewedAt"], summary, override["note"]))

    for tool_key, bundle in sorted((getattr(record, "assets", None) or {}).items()):
        for kind in ("symbol", "footprint", "model"):
            asset = bundle.get(kind)
            origin = getattr(asset, "origin", None) if asset is not None else None
            if origin is None or not (origin.captured_at or origin.vendor):
                continue
            events.append(
                _event(
                    "cad_captured",
                    origin.captured_at or "",
                    f"{tool_key} {kind} captured from "
                    f"{provider_label(origin.vendor) or origin.vendor or 'an unnamed source'}",
                    origin.url or "",
                )
            )

    derived_at = str(getattr(record, "derived_at", "") or "")
    if derived_at:
        events.append(
            _event(
                "derived",
                derived_at,
                "Derivation ran",
                str(getattr(record, "derived_by", "") or ""),
            )
        )

    # Newest first, and undated events LAST rather than first: an empty timestamp would sort
    # ahead of every real one and claim to be the oldest thing that happened to the part.
    dated = sorted((item for item in events if item["at"]), key=lambda item: item["at"],
                   reverse=True)
    undated = [item for item in events if not item["at"]]
    return dated + undated


__all__ = [
    "REVISION_KINDS",
    "REVISION_LABELS",
    "REVISION_SECTIONS",
    "build_revisions",
    "manual_overrides",
]
