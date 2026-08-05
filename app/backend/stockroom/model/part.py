"""The Stockroom part record: one JSON file per part.

One file per part is git-merge friendly by construction: concurrent adds on two machines land
in different files and cannot conflict (spec section 3). JSON is emitted canonically (sorted
keys, 2-space indent, trailing newline) so a one-field edit produces a minimal, stable diff.

The v3 identity / derived / sources / assets shape is drawn in
`docs/specs/2026-07-27-owner-spec-complete-trusted-library.md` section 9.  Version 4 adds only
the active CAD-variant pointers; the existing ``assets`` map remains the materialized projection:

    parts/<id>.json          identity + part_class + DERIVED + asset refs + a sources INDEX
    sourced/<id>/<src>.json  the raw pull, byte for byte, append-only evidence

Four rules hold the whole thing up:

  1. **`sourced/` is append-only evidence.** A re-derive READS it and never writes it. That is
     what "edit without reimporting" means, and it is why normalization moved off the import
     path (see model/derived.py).
  2. **`derived` is disposable by construction.** Drop the block, recompute, get the record
     back. `clear_derived()` exists so that is testable rather than asserted.
  3. **Identity is not derived.** `id`, `mpn`, `manufacturer` and `part_class` are never
     rewritten by a re-derive; only a human or an explicit re-classify changes them.
  4. **Checks are facts, the verdict is derived** (model/trust.py). Tightening a check
     re-judges the whole library with no re-audit.

The derived fields keep their flat Python attributes (`record.display_name`), because the
boundary the schema needs is a boundary in the DATA, not a second way to spell an attribute.
`record.derived` reads and writes them as one `Derived` block, and `DERIVED_FIELDS` is the one
list the record, the serializer and the drift test all read - so a derived field added in one
place and forgotten in another fails a test rather than silently persisting flat.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stockroom.eda.registry import all_tools, get_tool
from stockroom.model.asset import ASSET_KINDS, Asset, AssetOrigin, AssetRef, EdaAssets
from stockroom.model.cad_variant import CadVariantSelections
from stockroom.model.category import slugify
from stockroom.model.derived import DERIVED_BY, DERIVED_FIELDS, Derived
from stockroom.model.part_class import (
    DEFAULT_PART_CLASS,
    PartClass,
    RequirementOverride,
    capturable_kinds,
    needed_kinds,
    parse_part_class,
)
from stockroom.model.part_id import make_part_id
from stockroom.model.sourced import SourceEntry, source_rel_path
from stockroom.model.spec_hygiene import normalize_specs
from stockroom.model.trust import AssetCheck

# The record schema version this build WRITES. Bump it when the shape changes in a way an older
# build cannot faithfully reproduce, AND add the migration that upgrades the previous shape.
#   1 = flat, implicitly-KiCad `symbol`/`footprint`/`model` plus `altium_symbol`/`altium_footprint`
#   2 = the per-tool `eda` map (one symmetric EdaAssets bundle per EDA registry key)
#   3 = identity / `derived` / `sources` / `assets` (asset = ref + origin + checks), and
#       `part_class` in place of the two-valued `passive` flag
#   4 = `cad_variants`: one active digest-bound evidence bundle per tool, kept separate from
#       the materialized `assets` projection
#   5 = typed `documents`, the official `manufacturer_page` held apart from every distributor
#       offer, and reviewed manual `overrides` - three things the flat `datasheet` slot and a
#       purchase URL could not express without guessing
#
# This exists because peers share these records through git and BOTH write them. Kubernetes'
# API conventions state the rule: patching a resource at schema version N-1 must not erase
# fields defined at version N. Before this, an older build editing one field on a newer peer's
# part silently deleted every field it did not recognise, and git recorded the deletion as an
# intentional change. `extra` (below) is the other half of that guarantee.
SCHEMA_VERSION = 5

# KiCad-visible fields mirrored INTO symbol properties so KiCad shows a complete
# part even without Stockroom (spec section 3). Maps record-derived value ->
# KiCad property name; the actual value extraction lives in mutation/placement.
KICAD_MIRROR_FIELDS: tuple[str, ...] = (
    "Value",
    "MPN",
    "Manufacturer",
    "Datasheet",
    "Description",
    "ki_keywords",
    "Purchase",
)

# The completion passport (owner directive, 2026-07-16): a part enters the library on
# its IDENTITY + SOURCING alone. The CAD assets are NO LONGER gated - a part is added first and
# its assets are attached afterwards. This lets a whole BOM land as tracked records immediately,
# then be completed at leisure. Each pair is (presence-flag key, human label); the key names a
# flag, not a record attribute directly, so the same set gates staged inputs and finished
# records alike.
REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("display_name", "name"),
    ("mpn", "MPN"),
    ("manufacturer", "manufacturer"),
    ("category", "category"),
    ("description", "value/description"),
    ("datasheet", "datasheet"),
    ("purchase", "purchase link"),
)

# Human labels for the asset kinds, keyed by the kind names the EDA registry uses. Used by
# the UI to show which assets a landed part still needs (assets no longer gate entry).
ASSET_LABELS: dict[str, str] = {
    "symbol": "symbol",
    "footprint": "footprint",
    "model": "3D model",
}


class UnmigratableRecord(Exception):
    """A record whose schema version this build cannot upgrade.

    Raised instead of relabelling. The bug this replaces did `max(SCHEMA_VERSION, ...)` in
    `from_dict`, which stamped an old record as CURRENT while leaving its data in the old
    shape - so a stale record silently claimed to be understood, and the next reader had no
    way to tell.
    """


def asset_label(kind: str) -> str:
    """The human label for an asset kind. Falls back to the kind itself so a tool that
    registers a kind we have no label for still reads sensibly rather than crashing."""
    return ASSET_LABELS.get(kind, kind)


def missing_from_presence(present: dict[str, bool]) -> list[str]:
    """Given a {field_key: present} map, return the human labels of the required
    fields that are missing, in passport order. The single source of truth for both
    the complete-to-add gate (checked on staged inputs) and PartRecord.is_complete
    (checked on the canonical record), so the two can never drift apart."""
    return [label for key, label in REQUIRED_FIELDS if not present.get(key)]


def asset_present(value) -> bool:
    """True when an asset (or a bare reference) actually resolves to something.

    Generic across kinds on purpose: an entry-shaped asset (symbol, footprint) is identified by
    `name`, a file-shaped one (3D model) by `file`. A container with no entry (`lib` alone) is
    NOT present - that half-filled state is what produced the dangling `Footprint` property
    fixed in 21fce45. Accepts an `Asset` or a bare `AssetRef` so a caller holding either does
    not have to know which.
    """
    if value is None:
        return False
    return bool(value.is_present())


def tool_assets_ready(record, tool: str) -> bool:
    """True when a part carries both a symbol and a footprint for `tool`, each with a
    resolved entry name. Advisory: gates what a tool's emitter/placer writes, never the
    complete-to-add gate."""
    assets = record.assets_for(tool)
    return asset_present(assets.symbol) and asset_present(assets.footprint)


def tool_place_ready(record, tool: str) -> bool:
    """The single predicate for "this part is placeable in `tool`": that tool's assets are
    present AND the required data fields are (MPN, Manufacturer, Description). Emitters and
    status views both call this, so a "N of M ready" count can never disagree with what is
    actually emitted."""
    return tool_assets_ready(record, tool) and bool(
        record.mpn and record.manufacturer and record.description
    )


@dataclass
class Datasheet:
    file: str = ""
    source_url: str = ""
    fetched_at: str = ""


@dataclass
class PartDocument:
    """One typed document this part references, held apart from every other kind.

    A bare URL string cannot answer the questions a reader actually has - is this the
    manufacturer's own PDF or a distributor's copy, is it the current revision, is it a PDF at
    all or an HTML product page, and do we hold the bytes. Each of those is a separate field
    here so none of them has to be inferred from a filename.

    `local_path` and `remote_url` are independent: a document can be URL-only, file-only, or
    both, and all three are real states. Nothing here is preferred by storage - which datasheet
    wins is DERIVED from this evidence (`stockroom.dossier.documents`), so a stored preference
    can never go stale against a better copy that arrived later.
    """

    document_type: str = "datasheet"
    title: str = ""
    revision: str = ""
    manufacturer: str = ""
    # Who published the copy: "manufacturer", "distributor", "cad_provider", "imported".
    source_type: str = ""
    # The source key that supplied the reference, so a copy can always be traced back.
    source: str = ""
    local_path: str = ""
    remote_url: str = ""
    mime_type: str = ""
    # False when a later revision of the same document supersedes this one. A record that says
    # nothing leaves this True and the projection decides from the revisions it can see.
    is_current: bool = True
    retrieved_at: str = ""
    # Set only when the bytes were actually checked. Never stamped on a reference.
    verified_at: str = ""
    status: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        known = {
            "document_type": self.document_type,
            "title": self.title,
            "revision": self.revision,
            "manufacturer": self.manufacturer,
            "source_type": self.source_type,
            "source": self.source,
            "local_path": self.local_path,
            "remote_url": self.remote_url,
            "mime_type": self.mime_type,
            "is_current": self.is_current,
            "retrieved_at": self.retrieved_at,
            "verified_at": self.verified_at,
            "status": self.status,
        }
        return {**self.extra, **known}

    @classmethod
    def from_dict(cls, d: dict) -> "PartDocument":
        known = {
            "document_type",
            "title",
            "revision",
            "manufacturer",
            "source_type",
            "source",
            "local_path",
            "remote_url",
            "mime_type",
            "is_current",
            "retrieved_at",
            "verified_at",
            "status",
        }
        return cls(
            document_type=str(d.get("document_type", "") or "datasheet"),
            title=str(d.get("title", "")),
            revision=str(d.get("revision", "")),
            manufacturer=str(d.get("manufacturer", "")),
            source_type=str(d.get("source_type", "")),
            source=str(d.get("source", "")),
            local_path=str(d.get("local_path", "")),
            remote_url=str(d.get("remote_url", "")),
            mime_type=str(d.get("mime_type", "")),
            is_current=bool(d.get("is_current", True)),
            retrieved_at=str(d.get("retrieved_at", "")),
            verified_at=str(d.get("verified_at", "")),
            status=str(d.get("status", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class ManufacturerPage:
    """The manufacturer's OWN page for this part, stored where no offer can reach it.

    Kept as its own field rather than as the first sourcing URL because those are different
    facts: a distributor's product page is that distributor's listing, and treating it as the
    official page told a reader the manufacturer said something a reseller said. Whether the
    host really belongs to the manufacturer is DERIVED at projection time from the registry's
    domain data, so a stored `verified` flag can never outlive the check that produced it.
    """

    url: str = ""
    # The source key that supplied the URL ("digikey", "manufacturer", "user", ...).
    source: str = ""
    checked_at: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "url": self.url,
            "source": self.source,
            "checked_at": self.checked_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ManufacturerPage":
        known = {"url", "source", "checked_at"}
        return cls(
            url=str(d.get("url", "")),
            source=str(d.get("source", "")),
            checked_at=str(d.get("checked_at", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class FieldOverride:
    """One reviewed manual decision about a field, and who made it.

    This is the top of the source precedence order, which is exactly why it carries its
    reviewer and its time: a value that outranks the manufacturer's own datasheet has to say
    who decided that. Recording the override never deletes the sourced answers it displaced -
    they stay in `alternates` and still render as candidates.

    TWO kinds of decision live here, because they are decisions about the same thing and a
    field can only be decided once. A VALUE override says "the answer is this"; a PREFERRED
    SOURCE says "believe this source about it". The second is not a value at all, which is why
    `has_value` exists: without it a source pin would have to invent an empty value and the
    projection would show a blank where a real answer was in force. A pin FOLLOWS its source, so
    a later refresh of that source moves the field with it instead of freezing a stale copy.

    `replaced_value` / `replaced_source` are what the decision displaced at the moment it was
    made. They are the difference between "this is 5 V" and "this is 5 V, overriding 3.3 V from
    DigiKey", and they are also what makes clearing genuinely reversible rather than merely
    possible: the reader can always see what the record will fall back to.
    """

    value: object = ""
    note: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    # False when this entry only PINS a source and carries no literal value of its own. True by
    # default and omitted from the JSON when true, so a record written before pins existed keeps
    # its exact meaning: every override that predates this field IS a value override.
    has_value: bool = True
    # Whether the reviewer stands behind this value as checked against the manufacturer's own
    # word. True by default and omitted from the JSON when true, because every override written
    # before this field existed WAS a reviewed decision and a record on disk keeps its meaning.
    # False records the honest other case: a value somebody entered but has not confirmed, which
    # reads as `Unverified` rather than borrowing the authority of a reviewed override.
    verified: bool = True
    # The source key this field is pinned to, or "" when nothing is pinned.
    preferred_source: str = ""
    # The preferred SOURCED answer at the moment this decision was recorded, and who gave it.
    replaced_value: object = None
    replaced_source: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "value": self.value,
            "note": self.note,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            # Emitted only when they say something. An override that is exactly what an override
            # always was must serialize exactly as it always did, so adopting pins and displaced
            # evidence rewrites nothing already on disk.
            **({} if self.has_value else {"has_value": False}),
            **({} if self.verified else {"verified": False}),
            **({"preferred_source": self.preferred_source} if self.preferred_source else {}),
            **({"replaced_value": self.replaced_value} if self.replaced_value is not None else {}),
            **({"replaced_source": self.replaced_source} if self.replaced_source else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FieldOverride":
        known = {
            "value",
            "note",
            "reviewed_by",
            "reviewed_at",
            "has_value",
            "verified",
            "preferred_source",
            "replaced_value",
            "replaced_source",
        }
        return cls(
            value=d.get("value", ""),
            note=str(d.get("note", "")),
            reviewed_by=str(d.get("reviewed_by", "")),
            reviewed_at=str(d.get("reviewed_at", "")),
            has_value=bool(d.get("has_value", True)),
            verified=bool(d.get("verified", True)),
            preferred_source=str(d.get("preferred_source", "")),
            replaced_value=d.get("replaced_value"),
            replaced_source=str(d.get("replaced_source", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )

    def is_empty(self) -> bool:
        """True when this entry decides nothing and should not be kept.

        A record must never carry an override that neither holds a value nor pins a source: it
        would render as a reviewed decision that decides nothing, and it would keep a field
        looking settled after the decision was withdrawn.
        """
        return not self.has_value and not self.preferred_source


@dataclass
class Purchase:
    vendor: str = ""
    url: str = ""
    # The distributor's own order number for this part (e.g. the Mouser part number
    # "667-ERJ-P03F1101V"), distinct from the manufacturer MPN. Blank when unknown.
    part_number: str = ""
    price_breaks: list = field(default_factory=list)
    stock: int | None = None
    currency: str = ""
    fetched_at: str = ""


@dataclass
class Provenance:
    source: str = ""
    source_url: str = ""
    original_zip_sha256: str = ""
    ingested_at: str = ""


@dataclass
class Hashes:
    symbol_content: str = ""
    footprint_content: str = ""
    model_file: str = ""


@dataclass
class EnrichmentField:
    source: str = ""
    confidence: str = ""


@dataclass
class ProviderAssertion:
    """One person's explicit claim about whether a provider carries an artifact for this part.

    This lives on the record rather than in a sidecar because it IS component state: it travels
    with the part through git exactly like every other curated field, and a second file would be
    a second source of truth for the same question.

    `origin` is always "user" and is stored rather than assumed, so a claim can never be read
    back without its attribution. It is not a confidence score and there is no scale here: the
    only two things a person can say are that the artifact is there or that it is not.
    """

    status: str = ""
    origin: str = "user"
    noted_at: str = ""
    note: str = ""
    # Keys a newer build put on this entry, kept verbatim and re-emitted - the same guarantee
    # `SourcedValue.extra` gives, for the same reason: peers share these files through git.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "status": self.status,
            "origin": self.origin,
            "noted_at": self.noted_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderAssertion":
        known = {"status", "origin", "noted_at", "note"}
        return cls(
            status=str(d.get("status", "")),
            # A stored assertion with no origin predates the field; it can only ever have come
            # from a person, because nothing else writes here.
            origin=str(d.get("origin", "")) or "user",
            noted_at=str(d.get("noted_at", "")),
            note=str(d.get("note", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class CadSourcePreference:
    """Which provider's CAD this component prefers, for the whole set and per asset.

    Deliberately NOT a per-asset mix-and-match model. Stockroom accepts a CAD set only when the
    symbol, the footprint and the 3D model come from one provider's evidence manifest, and the
    coherence gate (`cad_variants.same_cad_evidence_set`) enforces that on the bytes. Storing a
    per-asset map here is what makes the RULE writable down: `assets` exists so a person can pin
    one artifact explicitly, and `dossier.cad_preference` refuses any pin that would leave two
    providers in force across the three. Without the map there would be no way to record the
    legitimate case; without the refusal the map would let a person write a set the gate then
    rejects, which is a promise the product cannot keep.

    `provider` and every value in `assets` are provider REGISTRY keys ("ultralibrarian"), never
    display labels and never EDA tool names: this records where files come from, not which
    application can read them.
    """

    provider: str = ""
    assets: dict[str, str] = field(default_factory=dict)
    reviewed_by: str = ""
    reviewed_at: str = ""
    # Keys a newer build wrote here, kept verbatim and re-emitted.
    extra: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        """Whether this decides nothing. An empty preference is omitted from the JSON."""
        return not self.provider and not any(self.assets.values())

    def for_asset(self, kind: str) -> str:
        """The provider pinned for one asset kind: its own pin, else the whole-set pin."""
        return (self.assets.get(kind) or "").strip() or self.provider

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "provider": self.provider,
            "assets": {kind: value for kind, value in self.assets.items() if value},
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CadSourcePreference":
        known = {"provider", "assets", "reviewed_by", "reviewed_at"}
        assets = d.get("assets")
        return cls(
            provider=str(d.get("provider", "")),
            assets={
                str(kind): str(value)
                for kind, value in (assets if isinstance(assets, dict) else {}).items()
                if value
            },
            reviewed_by=str(d.get("reviewed_by", "")),
            reviewed_at=str(d.get("reviewed_at", "")),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class SourcedValue:
    """One value a source offered for a field, with where it came from.

    `value` is deliberately untyped: a tariff rate is a float whose 0.0 is MEANINGFUL (a
    confirmed no-tariff part, not a missing one), while a description is a string.
    """

    value: object = ""
    source: str = ""
    confidence: str = ""
    # Keys a newer build put on this entry that we do not understand, kept verbatim and
    # re-emitted. The same guarantee `PartRecord.extra` gives the record as a whole, applied one
    # level down: peers share these files through git and BOTH write them, so rewriting a
    # neighbour's entry must not quietly strip the half of it we could not read.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        # Unknown keys first so a known one can never be shadowed by a stale preserved copy.
        return {
            **self.extra,
            "value": self.value,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourcedValue":
        known = {"value", "source", "confidence"}
        return cls(
            value=d.get("value", ""),
            source=d.get("source", ""),
            confidence=d.get("confidence", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


# ----------------------------------------------------------------- migrations

# The pre-v2 flat fields, mapped to (default tool, asset kind). A legacy ref carrying an
# explicit `tool` discriminator is honoured over the default here.
_LEGACY_ASSET_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("symbol", "kicad", "symbol"),
    ("footprint", "kicad", "footprint"),
    ("model", "kicad", "model"),
    ("altium_symbol", "altium", "symbol"),
    ("altium_footprint", "altium", "footprint"),
)


def record_version(d: dict) -> int:
    """The schema version a record dict declares. A record with no version predates
    versioning, which is exactly schema 1."""
    try:
        return int(d.get("schema_version", 1))
    except (TypeError, ValueError):
        raise UnmigratableRecord(f"unreadable schema_version {d.get('schema_version')!r}") from None


def _v1_to_v2(d: dict) -> dict:
    """Fold the flat, implicitly-KiCad asset fields into the per-tool `eda` map."""
    out = dict(d)
    eda: dict = dict(out.get("eda") or {})
    for legacy_key, default_tool, kind in _LEGACY_ASSET_FIELDS:
        ref = out.pop(legacy_key, None)
        if not ref:
            continue
        tool = ref.get("tool") or default_tool
        bundle = dict(eda.get(tool) or {})
        bundle[kind] = {
            "lib": ref.get("lib", ""),
            "name": ref.get("name", ""),
            "file": ref.get("file", ""),
        }
        eda[tool] = bundle
    if eda:
        out["eda"] = eda
    out["schema_version"] = 2
    return out


def _v2_to_v3(d: dict) -> dict:
    """Split identity from DERIVED, replace `passive` with `part_class`, and wrap each bare
    asset reference in the ref/origin/checks shape.

    A v2 asset gets `origin: None` rather than a fabricated one: nothing recorded where those
    files came from, and inventing a vendor would be exactly the false confidence this schema
    exists to remove.
    """
    out = dict(d)
    derived = dict(out.get("derived") or {})
    for name in DERIVED_FIELDS:
        if name in out:
            derived.setdefault(name, out.pop(name))
    out["derived"] = derived

    # `passive: true` is the only class v2 could express; everything else was a component.
    out["part_class"] = (
        PartClass.PASSIVE.value if out.pop("passive", False) else DEFAULT_PART_CLASS.value
    )

    eda = out.pop("eda", None) or {}
    assets: dict = {}
    for tool, bundle in eda.items():
        slots: dict = {}
        for kind, ref in (bundle or {}).items():
            if not ref:
                continue
            slots[kind] = {
                "ref": {
                    "lib": ref.get("lib", ""),
                    "name": ref.get("name", ""),
                    "file": ref.get("file", ""),
                }
            }
        if slots:
            assets[tool] = slots
    if assets:
        out["assets"] = assets
    out["schema_version"] = 3
    return out


def _v3_to_v4(d: dict) -> dict:
    """Adopt separate active CAD-variant pointers.

    A v3 asset has no durable link to an immutable evidence object, so migration must leave the
    selection empty rather than infer one from a filename or provenance label.  ``cad_variants``
    is optional on disk; the only required persisted change is the honest schema capability
    stamp.
    """
    out = dict(d)
    out["schema_version"] = 4
    return out


def _v4_to_v5(d: dict) -> dict:
    """Adopt typed documents, the separated manufacturer page, and reviewed overrides.

    Nothing is moved and nothing is deleted. The legacy `datasheet` slot stays exactly where it
    is and keeps its meaning - the dossier projection reads it and types it - so a v4 record
    round-trips byte for byte apart from its version stamp, and re-running this step on an
    already-migrated record is a no-op.

    The manufacturer page is deliberately NOT seeded from `purchase[0].url`. Inferring it from
    an offer is the exact bug this version exists to remove, and a migration that guessed it
    would write that bug permanently into every record on disk.
    """
    out = dict(d)
    out["schema_version"] = 5
    return out


# version present -> the step that upgrades it to the next one. A version with no entry is
# REFUSED rather than restamped.
_MIGRATIONS = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5}


def migrate_record(d: dict) -> dict:
    """Upgrade a record dict to `SCHEMA_VERSION`, one real step at a time.

    Pure: the caller's dict is never mutated. A record from the FUTURE is returned untouched
    and keeps its own version - downgrading the stamp would tell the next reader that a record
    still holding material we never understood is fully understood at our version.

    Raises `UnmigratableRecord` for a version we have no step for. That refusal is the point:
    the previous implementation did `max(SCHEMA_VERSION, ...)` and relabelled instead.
    """
    version = record_version(d)
    if version >= SCHEMA_VERSION:
        return dict(d)
    out = dict(d)
    while version < SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise UnmigratableRecord(
                f"no migration from schema version {version} to {SCHEMA_VERSION} "
                f"(record id {d.get('id')!r})"
            )
        out = step(out)
        moved = record_version(out)
        if moved <= version:
            raise UnmigratableRecord(
                f"migration from schema version {version} did not advance the record"
            )
        version = moved
    return out


# Every top-level key the v4 shape defines. Anything outside this set is a field from a newer
# build and is preserved verbatim in `PartRecord.extra`. Legacy keys are absent on purpose:
# `migrate_record` CONSUMES them before this set is consulted, so a migrated record can never
# carry two contradictory copies of its assets.
_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "id",
        "mpn",
        "manufacturer",
        "part_class",
        "requires_override",
        "derived",
        "sources",
        "assets",
        "cad_variants",
        "tags",
        "datasheet",
        "purchase",
        "provenance",
        "hashes",
        "enrichment",
        "alternates",
        "catalog",
        "provider_assertions",
        "cad_preference",
        "documents",
        "manufacturer_page",
        "overrides",
    }
)


@dataclass
class PartRecord:
    # ---- identity. Never rewritten by a re-derive; only a human or an explicit re-classify
    # changes any of these.
    id: str
    # ---- DERIVED. Recomputable from `sourced/`; grouped under "derived" on disk. Keep this
    # list in step with `DERIVED_FIELDS` - `test_part_record_v3` fails if they drift.
    display_name: str = ""
    category: str = ""
    description: str = ""
    # The component Value shown on a schematic + in a BOM (e.g. "10k" for a passive; the MPN
    # for an active). Mirrored to the symbol's Value property so a placed part is
    # self-describing.
    value: str = ""
    # Normalized spec keys and values. A free-form value bag keyed by spec name
    # (specs["pinout"] is a list of {"pin", "name"} dicts); per-key provenance lives in
    # `enrichment`, and every value a source offered and lost with lives in `alternates`.
    # NOT a completion-gate field: a part without a pinout is still complete.
    specs: dict = field(default_factory=dict)
    derived_at: str = ""
    derived_by: str = ""
    # Keys a newer build wrote INSIDE the derived block. Held here rather than in `extra` so a
    # re-derive replaces them with the block they belong to instead of stranding them at the
    # top level, where they would outlive the values they describe.
    derived_extra: dict = field(default_factory=dict)
    # ---- identity, continued
    mpn: str = ""
    manufacturer: str = ""
    # What this part IS, which decides what files it needs (model/part_class.py). Replaces the
    # two-valued `passive` flag, which had no home for the M3 mounting holes or the
    # button-integral ring LED already in the owner's register.
    part_class: PartClass = DEFAULT_PART_CLASS
    # The per-part escape hatch, so one odd part never forces a new class. None means "use the
    # class default"; an override with empty `needs` means "this part needs nothing", and the
    # two are deliberately different.
    requires_override: RequirementOverride | None = None
    # ---- evidence INDEX. The payloads live in `sourced/<id>/<source>.json`, never here.
    sources: dict[str, SourceEntry] = field(default_factory=dict)
    # ---- the CAD assets, one symmetric bundle per EDA tool, keyed by the tool key in
    # `stockroom.eda.registry` ("kicad", "altium", ...). Every registered tool always has an
    # entry (see __post_init__), so `record.assets_for(tool).symbol = ref` is always a live
    # write; empty bundles are dropped on serialization so the JSON stays minimal.
    assets: dict[str, EdaAssets] = field(default_factory=dict)
    # Active bundle selection is deliberately separate from `assets`: evidence variants are
    # immutable, while the EDA files are a replaceable projection. Empty selections are omitted
    # on disk so migrating a v3 record does not fabricate a link to bytes never digest-bound.
    cad_variants: CadVariantSelections = field(default_factory=CadVariantSelections)
    # ---- curated / vendor data that is neither identity nor recomputed from `sourced/`
    tags: list[str] = field(default_factory=list)
    datasheet: Datasheet | None = None
    # Every OTHER document this part references, each typed and each carrying its own copy
    # story. `datasheet` above stays the single legacy slot so a v4 record keeps its meaning;
    # the dossier projection reads both and types them into one list.
    documents: list[PartDocument] = field(default_factory=list)
    # The manufacturer's own page, stored apart from `purchase` so it can never be taken from a
    # distributor offer. Omitted from the JSON entirely when absent.
    manufacturer_page: ManufacturerPage | None = None
    # Reviewed manual decisions, keyed by canonical field key. Top of the source precedence
    # order; empty for almost every part, so it is omitted from the JSON when empty.
    overrides: dict[str, FieldOverride] = field(default_factory=dict)
    purchase: list[Purchase] = field(default_factory=list)
    provenance: Provenance | None = None
    hashes: Hashes | None = None
    enrichment: dict[str, EnrichmentField] = field(default_factory=dict)
    # Every value a source offered for a field that it did NOT win, with its origin. The
    # winning value stays in its own slot and is repeated as the FIRST entry here, so a reader
    # always sees which answer is in force beside the ones set aside. The key space is shared
    # with `enrichment`. Omitted from the JSON entirely when empty - a part must not gain a key
    # just because this feature exists.
    alternates: dict[str, list[SourcedValue]] = field(default_factory=dict)
    # Provider-keyed, versioned catalogue intelligence captured during intake. This is neither
    # an electrical spec nor a derived display field: CAD/3D availability, media resources,
    # packaging equivalence and relationship classes retain their own structured semantics.
    catalog: dict[str, dict] = field(default_factory=dict)
    # Explicit per-provider, per-artifact claims a PERSON made about CAD coverage, keyed
    # provider key -> asset kind. Kept apart from `catalog` (which is what a distributor said)
    # and from `assets` (which is what Stockroom holds) precisely so the three can never be
    # confused for one another. Omitted from the JSON entirely when empty.
    provider_assertions: dict[str, dict[str, ProviderAssertion]] = field(default_factory=dict)
    # Which provider's CAD set this component prefers. A reviewed DECISION, so it is kept apart
    # from `provider_assertions` (what a person observed about coverage), from `catalog` (what a
    # distributor said) and from `assets` (which files Stockroom actually holds). Omitted from
    # the JSON entirely when it decides nothing.
    cad_preference: CadSourcePreference = field(default_factory=CadSourcePreference)
    # The schema version this record was WRITTEN at. A record read from disk keeps its own
    # value (never downgraded to ours, never RAISED to ours without a real migration), so a
    # build that does not fully understand a newer record cannot claim otherwise to the next
    # reader. See SCHEMA_VERSION and migrate_record.
    schema_version: int = SCHEMA_VERSION
    # Top-level keys this build does not recognise, kept verbatim and re-emitted on write.
    # Without this, an older Stockroom editing one field on a newer peer's part would DELETE
    # every field it had never heard of, and git would record that as an intentional change.
    # Not part of the public shape: never read from here, only preserved through it.
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # An unknown part_class is LOUD, never guessed: it decides which files a part needs, so
        # a wrong guess either demands the impossible or excuses a real gap, invisibly.
        self.part_class = parse_part_class(self.part_class)
        # Canonicalize spec keys/values on construction (covers from_dict + direct build). A
        # later direct mutation of self.specs is re-cleaned by to_dict, so persisted + served
        # data is always clean. Normalizing DERIVED specs is legitimate precisely because the
        # raw value the source returned now survives in `sourced/`.
        self.specs = normalize_specs(self.specs)
        # Every registered tool always has a live bundle, so `assets_for(tool).symbol = ref`
        # can never write into a throwaway object that is silently discarded. Bundles for tools
        # this build does not know (written by a newer peer) are left untouched.
        for tool in all_tools():
            self.assets.setdefault(tool.key, EdaAssets())

    # ------------------------------------------------------------- derived block

    @property
    def derived(self) -> Derived:
        """The recomputable half of this record, as one block.

        Spec keys and values are normalized on the way out as well as on construction, so a
        spec added AFTER construction (as the enrich pipeline does) is still clean by the time
        it reaches disk or the API.
        """
        block = Derived(
            **{name: getattr(self, name) for name in DERIVED_FIELDS}, extra=dict(self.derived_extra)
        )
        block.specs = normalize_specs(block.specs)
        return block

    @derived.setter
    def derived(self, block: Derived) -> None:
        for name in DERIVED_FIELDS:
            setattr(self, name, getattr(block, name))
        self.derived_extra = dict(block.extra)
        self.specs = normalize_specs(self.specs)

    def clear_derived(self) -> None:
        """Drop the whole derived block. Recomputing it must reproduce the record exactly -
        that is what makes `derived` disposable BY CONSTRUCTION rather than by assertion, and
        it is the acceptance test for the schema (spec section 9)."""
        self.derived = Derived()

    def stamp_derived(self, *, at: str, by: str = DERIVED_BY) -> None:
        """Record WHEN this block was computed and by WHICH ruleset, so a library can be swept
        for parts still carrying an older derivation."""
        self.derived_at = at
        self.derived_by = by

    @property
    def passive(self) -> bool:
        """Read-only: a passive is a PART CLASS, not a flag. Kept because "is this a passive"
        is a real question with a real answer; setting it is not, because the answer to "what
        is it if not passive" is one of three things, not one."""
        return self.part_class is PartClass.PASSIVE

    # ------------------------------------------------------------- evidence index

    def record_source(self, source: str, *, fetched_at: str, file: str = "") -> SourceEntry:
        """Index one source's raw payload on this record. Writes NOTHING to `sourced/` - the
        payload is stored by `model.sourced.write_payload`, and keeping the two apart is what
        stops a re-derive from ever touching evidence."""
        entry = SourceEntry(fetched_at=fetched_at, file=file or source_rel_path(self.id, source))
        self.sources[source] = entry
        return entry

    # ------------------------------------------------------------- assets

    def assets_for(self, tool: str) -> EdaAssets:
        """The LIVE asset bundle for `tool` -- mutating it mutates the record.

        Raises KeyError for a tool that is neither registered nor already present on the
        record. Never falls back to KiCad: that silent fallback is exactly what let an
        Altium attach overwrite the KiCad reference (f7d80ac).
        """
        if tool not in self.assets:
            get_tool(tool)  # raises with the known-tool list
            self.assets[tool] = EdaAssets()
        return self.assets[tool]

    # ------------------------------------------------------------- serialization

    def to_dict(self) -> dict:
        # Unknown keys first so a known key can never be shadowed by a stale preserved copy
        # of itself; `dumps` sorts keys anyway, so ordering here is about precedence only.
        return {
            **self.extra,
            "schema_version": self.schema_version,
            "id": self.id,
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "part_class": self.part_class.value,
            "requires_override": (
                self.requires_override.to_dict() if self.requires_override else None
            ),
            "derived": self.derived.to_dict(),
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            # Empty bundles are omitted: a part with only KiCad assets should not carry a
            # wall of nulls for every other tool, and a one-field edit stays a one-line diff.
            "assets": {k: a.to_dict() for k, a in self.assets.items() if not a.is_empty()},
            **(
                {"cad_variants": self.cad_variants.to_dict()}
                if not self.cad_variants.is_empty()
                else {}
            ),
            "tags": list(self.tags),
            "datasheet": asdict(self.datasheet) if self.datasheet else None,
            # All three omitted when empty, like `assets`: adopting v5 must not rewrite every
            # part in a real library to add an empty list, a null and an empty map.
            **({"documents": [doc.to_dict() for doc in self.documents]} if self.documents else {}),
            **(
                {"manufacturer_page": self.manufacturer_page.to_dict()}
                if self.manufacturer_page is not None
                else {}
            ),
            **(
                {"overrides": {k: v.to_dict() for k, v in self.overrides.items()}}
                if self.overrides else {}
            ),
            "purchase": [asdict(p) for p in self.purchase],
            "provenance": asdict(self.provenance) if self.provenance else None,
            "hashes": asdict(self.hashes) if self.hashes else None,
            "enrichment": {k: asdict(v) for k, v in self.enrichment.items()},
            # Omitted when empty, like `assets`: adopting this must not rewrite every part in a
            # real library to add a `{}`.
            **(
                {"alternates": {k: [a.to_dict() for a in v] for k, v in self.alternates.items()}}
                if self.alternates else {}
            ),
            **(
                {"catalog": {key: dict(value) for key, value in self.catalog.items()}}
                if self.catalog else {}
            ),
            **(
                {
                    "provider_assertions": {
                        provider: {
                            kind: assertion.to_dict() for kind, assertion in slots.items()
                        }
                        for provider, slots in self.provider_assertions.items()
                        if slots
                    }
                }
                if any(self.provider_assertions.values()) else {}
            ),
            **(
                {"cad_preference": self.cad_preference.to_dict()}
                if not self.cad_preference.is_empty() else {}
            ),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PartRecord":
        # MIGRATE, never relabel. A record older than us is upgraded field by field or refused;
        # a record newer than us keeps its own stamp and its unknown fields (see `extra`).
        d = migrate_record(d)
        derived = Derived.from_dict(d.get("derived") or {})
        override = d.get("requires_override")
        return cls(
            id=d["id"],
            **{name: getattr(derived, name) for name in DERIVED_FIELDS},
            derived_extra=dict(derived.extra),
            mpn=d.get("mpn", ""),
            manufacturer=d.get("manufacturer", ""),
            part_class=parse_part_class(d.get("part_class", DEFAULT_PART_CLASS)),
            requires_override=(
                RequirementOverride.from_dict(override) if isinstance(override, dict) else None
            ),
            sources={
                k: SourceEntry.from_dict(v)
                for k, v in (d.get("sources") or {}).items()
                if isinstance(v, dict)
            },
            assets={
                tool: EdaAssets.from_dict(a or {}) for tool, a in (d.get("assets") or {}).items()
            },
            cad_variants=CadVariantSelections.from_dict(d.get("cad_variants") or {}),
            tags=list(d.get("tags", [])),
            datasheet=Datasheet(**d["datasheet"]) if d.get("datasheet") else None,
            documents=[
                PartDocument.from_dict(doc)
                for doc in (d.get("documents") or [])
                if isinstance(doc, dict)
            ],
            manufacturer_page=(
                ManufacturerPage.from_dict(d["manufacturer_page"])
                if isinstance(d.get("manufacturer_page"), dict)
                else None
            ),
            overrides={
                str(key): FieldOverride.from_dict(value)
                for key, value in (d.get("overrides") or {}).items()
                if isinstance(value, dict)
            },
            purchase=[Purchase(**p) for p in d.get("purchase", [])],
            provenance=Provenance(**d["provenance"]) if d.get("provenance") else None,
            hashes=Hashes(**d["hashes"]) if d.get("hashes") else None,
            enrichment={k: EnrichmentField(**v) for k, v in d.get("enrichment", {}).items()},
            alternates={
                k: [SourcedValue.from_dict(a) for a in (v or []) if isinstance(a, dict)]
                for k, v in (d.get("alternates") or {}).items()
            },
            catalog={
                str(key): dict(value)
                for key, value in (d.get("catalog") or {}).items()
                if isinstance(value, dict)
            },
            provider_assertions={
                str(provider): {
                    str(kind): ProviderAssertion.from_dict(assertion)
                    for kind, assertion in slots.items()
                    if isinstance(assertion, dict)
                }
                for provider, slots in (d.get("provider_assertions") or {}).items()
                if isinstance(slots, dict)
            },
            cad_preference=(
                CadSourcePreference.from_dict(d["cad_preference"])
                if isinstance(d.get("cad_preference"), dict)
                else CadSourcePreference()
            ),
            schema_version=record_version(d),
            extra={k: v for k, v in d.items() if k not in _KNOWN_KEYS},
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "PartRecord":
        return cls.from_dict(json.loads(text))

    def is_future_schema(self) -> bool:
        """True when this record was written by a build newer than ours. It is still loaded
        and still round-trips losslessly (see `extra`), but a caller that is about to REWRITE
        its structure should say so rather than assume it understood everything."""
        return self.schema_version > SCHEMA_VERSION

    # ------------------------------------------------------------- completeness

    def _presence(self) -> dict[str, bool]:
        return {
            "display_name": bool(self.display_name.strip()),
            "mpn": bool(self.mpn.strip()),
            "manufacturer": bool(self.manufacturer.strip()),
            "category": bool(self.category.strip()),
            "description": bool(self.description.strip()),
            # A datasheet is satisfied by a stored PDF OR a datasheet URL (owner: keep
            # datasheet URLs as a first-class field; a known link should not block).
            "datasheet": self.datasheet is not None
            and (bool(self.datasheet.file) or bool(self.datasheet.source_url)),
            "purchase": any(bool(p.url) for p in self.purchase),
        }

    def missing_fields(self) -> list[str]:
        """Human labels of the required passport fields this record lacks (empty => complete)."""
        return missing_from_presence(self._presence())

    def needs(self, tool: str) -> tuple[str, ...]:
        """The asset kinds this part should END UP holding for `tool`, from its part class and
        any per-part override, intersected with what the tool can actually hold. There is no
        `if passive` and no `if tool == ...` here or below: both answers are data."""
        return needed_kinds(self.part_class, tool, self.requires_override)

    def capturable(self, tool: str) -> tuple[str, ...]:
        """The asset kinds a CAPTURE session can be asked to fetch for this part from `tool`.
        Narrower than `needs`: an Altium 3D body is a real gap that a vendor cannot close."""
        return capturable_kinds(self.part_class, tool, self.requires_override)

    def missing_assets(self, tool: str) -> list[str]:
        """Human labels of the assets `tool` still lacks, in the tool's registered kind order.

        Not part of completeness -- a part is complete without any assets now -- but it tells
        the UI what can still be attached. Only kinds this part's CLASS actually needs are
        reported: a passive needs nothing from any tool, a mechanical part has no symbol, and
        reporting a gap nothing can close is what "CAD Incomplete forever" looked like.
        """
        assets = self.assets_for(tool)
        return [
            asset_label(kind)
            for kind in self.needs(tool)
            if not asset_present(assets.get(kind))
        ]

    def missing_assets_by_tool(self) -> dict[str, list[str]]:
        """`missing_assets` for every registered tool. The generic entry point the API and
        capture layer use, so a third tool is covered by registering it and nothing else."""
        return {tool.key: self.missing_assets(tool.key) for tool in all_tools()}

    def is_complete(self) -> bool:
        return not self.missing_fields()


def new_part_id(parts_dir: Path, mpn: str, fallback_name: str = "") -> str:
    """The id for a new part.

    With an MPN the answer is the decided scheme (`model/part_id.py`):
    `slug(mpn)-sha256(mpn)[:4]`, a PURE function of the MPN. `parts_dir` is not consulted,
    because the id must not depend on what is already on disk: two calls for the same MPN
    return the same id, so a re-import lands on the same file instead of minting `-2`, `-3`,
    ... duplicates of one part.

    `fallback_name` covers the one case the pure function cannot settle. A part with NO MPN has
    no stable identity, so its id is slugged from whatever name it has and de-duplicated
    against the directory - and those ids are NOT stable across a rename, which is exactly why
    an MPN-less part is a gap to close rather than a supported shape.

    The two arguments are separate on purpose: passing `mpn or display_name` in one slot would
    hide which of the two answers a caller got, and `display_name` is a DERIVED field - an id
    minted from it would move the moment the naming scheme changed.
    """
    mpn = (mpn or "").strip()
    if mpn:
        return make_part_id(mpn)
    parts_dir = Path(parts_dir)
    slug = slugify(fallback_name) or "part"
    candidate = slug
    n = 1
    while (parts_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{slug}-{n}"
    return candidate


__all__ = [
    "ASSET_KINDS",
    "ASSET_LABELS",
    "KICAD_MIRROR_FIELDS",
    "REQUIRED_FIELDS",
    "SCHEMA_VERSION",
    "Asset",
    "AssetCheck",
    "AssetOrigin",
    "AssetRef",
    "CadSourcePreference",
    "CadVariantSelections",
    "Datasheet",
    "Derived",
    "EdaAssets",
    "EnrichmentField",
    "FieldOverride",
    "Hashes",
    "ManufacturerPage",
    "PartClass",
    "PartDocument",
    "PartRecord",
    "Provenance",
    "ProviderAssertion",
    "Purchase",
    "RequirementOverride",
    "SourceEntry",
    "SourcedValue",
    "UnmigratableRecord",
    "asset_label",
    "asset_present",
    "migrate_record",
    "missing_from_presence",
    "new_part_id",
    "record_version",
    "tool_assets_ready",
    "tool_place_ready",
]
