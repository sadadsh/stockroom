"""Typed documents, and which datasheet a person should actually open.

A URL string cannot say whether it points at the manufacturer's own PDF, a distributor's mirror
of it, an HTML product page with no PDF at all, or a superseded revision. Those are different
documents with different trust, and a single `datasheet_url` field made every one of them look
the same. Each becomes a typed resource here, and the preferred datasheet is DERIVED from the
evidence rather than stored, so a better copy arriving later wins immediately instead of losing
to a stale flag.

Six shapes all have to work and all do: URL only, local file only, both, several revisions of
one document, an HTML page where no PDF exists, and no datasheet at all. The last one is a real
answer and is reported as one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from stockroom.dossier.urls import host_of, is_pdf, matches_manufacturer, provider_of
from stockroom.providers import provider_label

# What a document IS. Closed, because "some other link" is not a document type and a reader
# looking for a PCN must not have to open five attachments to find out none of them is one.
DOCUMENT_TYPES: tuple[str, ...] = (
    "datasheet",
    "datasheet_page",
    "package_drawing",
    "application_note",
    "pcn",
    "pdn",
    "compliance_declaration",
    "certificate",
    "attachment",
    "other",
)

# Who published the copy. This is about the COPY, not about the document: a distributor-hosted
# mirror of a manufacturer PDF is a distributor copy of a manufacturer document.
SOURCE_TYPES: tuple[str, ...] = (
    "manufacturer",
    "distributor",
    "cad_provider",
    "imported",
    "unknown",
)

# What we hold. `verified` means the bytes were checked, never that a link looked plausible.
DOCUMENT_STATUSES: tuple[str, ...] = ("verified", "stored", "referenced", "unreachable")

DOCUMENT_TYPE_LABELS: dict[str, str] = {
    "datasheet": "Datasheet",
    "datasheet_page": "Datasheet Page",
    "package_drawing": "Package Drawing",
    "application_note": "Application Note",
    "pcn": "Product Change Notice",
    "pdn": "Product Discontinuation Notice",
    "compliance_declaration": "Compliance Declaration",
    "certificate": "Certificate",
    "attachment": "Imported Attachment",
    "other": "Reference",
}

# Title tokens that identify a catalogue media entry's type. First match wins, most specific
# first, and a title nothing here recognises stays `other` rather than being called a datasheet.
_TITLE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pcn", ("pcn", "product change notice", "change notification")),
    ("pdn", ("pdn", "discontinuation", "obsolescence notice", "end of life notice")),
    ("compliance_declaration", ("rohs", "reach", "compliance", "declaration", "conflict mineral")),
    ("certificate", ("certificate", "certification", "ul listing", "iso ")),
    ("package_drawing", ("drawing", "outline", "mechanical", "land pattern", "recommended pad")),
    ("application_note", ("application note", "app note", "user guide", "reference manual",
                          "errata", "user manual")),
    ("datasheet", ("datasheet", "data sheet", "product specification")),
)


def _document_type(title: str, url: str, mime_type: str, declared: str = "") -> str:
    if declared in DOCUMENT_TYPES:
        return declared
    folded = f"{title} {url}".casefold()
    for kind, tokens in _TITLE_TYPES:
        if any(token in folded for token in tokens):
            # A datasheet reference that is a page rather than a file is its own type: it can
            # still be opened, but it is not the document, and calling it one would promise a
            # PDF that does not exist.
            if kind == "datasheet" and not is_pdf(url, mime_type):
                return "datasheet_page"
            return kind
    return "other"


def _source_type(url: str, manufacturer: str, declared: str = "") -> str:
    if declared in SOURCE_TYPES:
        return declared
    if not url:
        return "unknown"
    if matches_manufacturer(url, manufacturer):
        return "manufacturer"
    provider = provider_of(url)
    if provider is None:
        return "unknown"
    if provider.distributor:
        return "distributor"
    if provider.key == "manufacturer":
        return "manufacturer"
    return "cad_provider"


def _status(local_path: str, remote_url: str, verified_at: str, declared: str = "") -> str:
    if declared in DOCUMENT_STATUSES:
        return declared
    if verified_at:
        return "verified"
    if local_path:
        return "stored"
    if remote_url:
        return "referenced"
    return "unreachable"


def document_id(
    document_type: str, source: str, revision: str, local_path: str, remote_url: str
) -> str:
    """A stable name for one document, derived from what makes it that document.

    Derived rather than stored, and derived only from the document's OWN identity - what kind of
    thing it is, who supplied it, which revision it is, and where it lives. Two consequences
    matter and both are the point:

      * a re-read of the same record always produces the same id, and adding, removing or
        reordering any OTHER document leaves it untouched;
      * two documents that differ in any of those five facts get different ids, so a part can
        carry several revisions of one datasheet, or two sources' copies of one file, without
        either of them being addressable as the other.

    It is deliberately NOT a position. An index means something different the moment an
    enrichment lands, so a viewer opened on index 2 and clicked a second later fetches a
    different document with nothing having failed - which is the failure that looks like success.

    It is deliberately not persisted either. A stored id could disagree with the document it
    names; a derived one cannot.

    It is also not a path. Nothing derives a filesystem location from this value - a document is
    resolved by finding the record's own entry with this id and reading the path IT carries - so
    an id from a request can never name a file the record does not reference. The result is plain
    lowercase hex, so it needs no escaping to sit in a URL path segment.
    """
    material = "\x1f".join(
        (
            document_type,
            source.casefold(),
            revision.casefold(),
            local_path.casefold(),
            remote_url.casefold(),
        )
    )
    return hashlib.blake2s(material.encode("utf-8"), digest_size=8).hexdigest()


def _view(
    *,
    document_type: str,
    title: str,
    revision: str,
    manufacturer: str,
    source_type: str,
    source: str,
    local_path: str,
    remote_url: str,
    mime_type: str,
    is_current: bool,
    retrieved_at: str,
    verified_at: str,
    status: str,
) -> dict[str, Any]:
    return {
        "id": document_id(document_type, source, revision, local_path, remote_url),
        "documentType": document_type,
        "documentTypeLabel": DOCUMENT_TYPE_LABELS.get(document_type, "Reference"),
        "title": title or DOCUMENT_TYPE_LABELS.get(document_type, "Reference"),
        "revision": revision,
        "manufacturer": manufacturer,
        "sourceType": source_type,
        "sourceId": source,
        "sourceLabel": provider_label(source) if source else "",
        "localPath": local_path,
        "remoteUrl": remote_url,
        "mimeType": mime_type or ("application/pdf" if is_pdf(remote_url) else ""),
        "host": host_of(remote_url),
        # Decided below, once every document is on the table.
        "isPreferred": False,
        "isCurrent": is_current,
        "retrievedAt": retrieved_at,
        "verifiedAt": verified_at,
        "status": status,
    }


def _from_record_documents(record) -> list[dict[str, Any]]:
    manufacturer = str(getattr(record, "manufacturer", "") or "")
    out: list[dict[str, Any]] = []
    for stored in getattr(record, "documents", None) or []:
        document_type = _document_type(
            stored.title, stored.remote_url or stored.local_path, stored.mime_type,
            stored.document_type,
        )
        out.append(
            _view(
                document_type=document_type,
                title=stored.title,
                revision=stored.revision,
                manufacturer=stored.manufacturer or manufacturer,
                source_type=_source_type(stored.remote_url, manufacturer, stored.source_type),
                source=stored.source,
                local_path=stored.local_path,
                remote_url=stored.remote_url,
                mime_type=stored.mime_type,
                is_current=bool(stored.is_current),
                retrieved_at=stored.retrieved_at,
                verified_at=stored.verified_at,
                status=_status(
                    stored.local_path, stored.remote_url, stored.verified_at, stored.status
                ),
            )
        )
    return out


def _legacy_local_path(stored: str) -> str:
    """The legacy datasheet filename as a library-relative path.

    `Datasheet.file` has always meant "this name, under `datasheets/`", which is a convention
    every reader had to know before it could find the bytes. Stating it here rather than storing
    it changes nothing on disk and gives every projected document ONE meaning for `localPath`,
    so a document is folded onto the typed entry for the same file instead of appearing twice
    under two spellings of one path.
    """
    text = str(stored or "").strip().replace("\\", "/")
    if not text:
        return ""
    head = text.split("/", 1)[0].casefold()
    return text if head == "datasheets" else f"datasheets/{text}"


def _from_legacy_datasheet(record) -> list[dict[str, Any]]:
    """The single legacy `datasheet` slot, typed.

    Kept as a first-class source rather than migrated away: a v4 record on a peer's machine
    still carries its datasheet here, and rewriting every record on disk to move one field is a
    destructive migration in exchange for nothing.
    """
    datasheet = getattr(record, "datasheet", None)
    if datasheet is None:
        return []
    if not (datasheet.file or datasheet.source_url):
        return []
    manufacturer = str(getattr(record, "manufacturer", "") or "")
    url = datasheet.source_url or ""
    document_type = "datasheet" if (datasheet.file or is_pdf(url)) else "datasheet_page"
    source_type = _source_type(url, manufacturer)
    if not url and datasheet.file:
        # A stored file with no link is something Stockroom imported; claiming the manufacturer
        # published it would be an attribution nothing on the record supports.
        source_type = "imported"
    return [
        _view(
            document_type=document_type,
            title="Datasheet",
            revision="",
            manufacturer=manufacturer,
            source_type=source_type,
            source="datasheet",
            local_path=_legacy_local_path(datasheet.file),
            remote_url=url,
            mime_type="application/pdf" if (datasheet.file or is_pdf(url)) else "text/html",
            is_current=True,
            retrieved_at=datasheet.fetched_at or "",
            verified_at="",
            status=_status(datasheet.file or "", url, ""),
        )
    ]


def _from_catalog(record) -> list[dict[str, Any]]:
    manufacturer = str(getattr(record, "manufacturer", "") or "")
    out: list[dict[str, Any]] = []
    for provider_key, payload in (getattr(record, "catalog", None) or {}).items():
        if not isinstance(payload, Mapping):
            continue
        for item in payload.get("media") or []:
            if not isinstance(item, Mapping):
                continue
            url = str(item.get("url") or "")
            if not url.startswith("https://"):
                continue
            title = str(item.get("title") or "")
            document_type = _document_type(title, url, str(item.get("mime_type") or ""))
            out.append(
                _view(
                    document_type=document_type,
                    title=title,
                    revision=str(item.get("revision") or ""),
                    manufacturer=manufacturer,
                    source_type=_source_type(url, manufacturer),
                    source=str(provider_key),
                    local_path="",
                    remote_url=url,
                    mime_type=str(item.get("mime_type") or ""),
                    is_current=True,
                    retrieved_at="",
                    verified_at="",
                    status="referenced",
                )
            )
    return out


def _from_provenance(record) -> list[dict[str, Any]]:
    provenance = getattr(record, "provenance", None)
    if provenance is None or not (provenance.source_url or provenance.original_zip_sha256):
        return []
    return [
        _view(
            document_type="attachment",
            title="Original Import Package",
            revision="",
            manufacturer=str(getattr(record, "manufacturer", "") or ""),
            source_type="imported",
            source=provenance.source or "provenance",
            local_path="",
            remote_url=provenance.source_url or "",
            mime_type="",
            is_current=True,
            retrieved_at=provenance.ingested_at or "",
            # An import package is proven by its digest, which is exactly the kind of check that
            # earns `verified`; a package with no digest recorded has not been checked.
            verified_at=provenance.ingested_at if provenance.original_zip_sha256 else "",
            status="verified" if provenance.original_zip_sha256 else "referenced",
        )
    ]


def _dedupe(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per distinct copy. The first sighting keeps the slot, so the record's own
    typed document beats a catalogue link to the same file."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in documents:
        key = (
            item["documentType"],
            item["localPath"].casefold(),
            item["remoteUrl"].casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _revision_sort_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return (str(item.get("revision") or ""), str(item.get("retrievedAt") or ""))


def _apply_currency(documents: list[dict[str, Any]]) -> None:
    """Within one document family, the highest revision is the current one.

    A record that explicitly says a document is superseded is believed and never re-promoted:
    somebody knew something the revision string did not say.
    """
    families: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in documents:
        families.setdefault(
            (item["documentType"], item["title"].strip().casefold()), []
        ).append(item)
    for members in families.values():
        if len(members) < 2:
            continue
        eligible = [item for item in members if item["isCurrent"]]
        if not eligible:
            continue
        newest = max(eligible, key=_revision_sort_key)
        for item in members:
            item["isCurrent"] = item is newest


# The preferred-datasheet order, best first. Each rule is a predicate over one typed document;
# the first rule any document satisfies decides, and within a rule the current revision wins.
_PREFERENCE_RULES: tuple[tuple[str, Any], ...] = (
    (
        "verified local manufacturer PDF",
        lambda item: item["documentType"] == "datasheet"
        and item["sourceType"] == "manufacturer"
        and bool(item["localPath"])
        and item["status"] == "verified",
    ),
    (
        "official manufacturer PDF URL",
        lambda item: item["documentType"] == "datasheet"
        and item["sourceType"] == "manufacturer"
        and bool(item["remoteUrl"]),
    ),
    (
        "verified imported PDF",
        lambda item: item["documentType"] == "datasheet"
        and item["sourceType"] == "imported"
        and bool(item["localPath"]),
    ),
    (
        "trusted distributor copy of the manufacturer PDF",
        lambda item: item["documentType"] == "datasheet"
        and item["sourceType"] in {"distributor", "cad_provider", "unknown"},
    ),
    (
        "referenced datasheet page",
        lambda item: item["documentType"] == "datasheet_page",
    ),
    (
        "other referenced document",
        lambda item: bool(item["remoteUrl"] or item["localPath"]),
    ),
)


def preferred_datasheet(documents: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """The datasheet to open, and the rule that chose it.

    Returning the reason is not decoration: "we are showing you a distributor's copy because the
    manufacturer's own PDF is not on file" is the difference between a link and an explanation,
    and it is also the next action.
    """
    for reason, predicate in _PREFERENCE_RULES:
        matches = [item for item in documents if predicate(item)]
        if not matches:
            continue
        current = [item for item in matches if item["isCurrent"]] or matches
        return max(current, key=_revision_sort_key), reason
    return None, ""


def find_document(record, wanted_id: str) -> dict[str, Any] | None:
    """The one typed document this record references under `wanted_id`, or None.

    Resolution goes THROUGH the record every time. There is no index from an id to a path
    anywhere, so an id nothing on this part produced simply finds nothing.
    """
    wanted = str(wanted_id or "").strip().casefold()
    if not wanted:
        return None
    for item in build_documents(record)["items"]:
        if item["id"] == wanted:
            return item
    return None


def _reading_order(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
    """Where a document sits in the list a person reads.

    The primary datasheet first, then the remaining kinds in the order `DOCUMENT_TYPES` declares -
    which is the order they matter in, not the order the record happened to store them. A
    superseded revision sorts under the current one it supersedes. The alternative, source order,
    put an import package above the datasheet whenever a part had been imported.
    """
    try:
        kind = DOCUMENT_TYPES.index(item["documentType"])
    except ValueError:
        kind = len(DOCUMENT_TYPES)
    return (
        0 if item["isPreferred"] else 1,
        kind,
        0 if item["isCurrent"] else 1,
        str(item.get("title") or "").casefold(),
    )


def build_documents(record) -> dict[str, Any]:
    """Every document this part references, typed, deduplicated and ranked."""
    documents = _dedupe(
        _from_record_documents(record)
        + _from_legacy_datasheet(record)
        + _from_catalog(record)
        + _from_provenance(record)
    )
    _apply_currency(documents)
    preferred, reason = preferred_datasheet(documents)
    if preferred is not None:
        preferred["isPreferred"] = True
    documents.sort(key=_reading_order)
    by_type: dict[str, int] = {}
    for item in documents:
        by_type[item["documentType"]] = by_type.get(item["documentType"], 0) + 1
    return {
        "types": list(DOCUMENT_TYPES),
        "items": documents,
        "count": len(documents),
        "countsByType": by_type,
        "preferredDatasheet": preferred,
        "preferredDatasheetReason": reason,
        # A part with no datasheet at all is a state, not a missing section.
        "hasDatasheet": any(
            item["documentType"] in {"datasheet", "datasheet_page"} for item in documents
        ),
    }


__all__ = [
    "DOCUMENT_STATUSES",
    "DOCUMENT_TYPES",
    "DOCUMENT_TYPE_LABELS",
    "SOURCE_TYPES",
    "build_documents",
    "document_id",
    "find_document",
    "preferred_datasheet",
]
