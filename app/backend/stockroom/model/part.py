"""The Stockroom part record: one JSON file per part.

One file per part is git-merge friendly by construction: concurrent adds on two
machines land in different files and cannot conflict (spec section 3). JSON is
emitted canonically (sorted keys, 2-space indent, trailing newline) so a
one-field edit produces a minimal, stable diff.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from stockroom.eda.registry import all_tools, get_tool
from stockroom.model.category import slugify
from stockroom.model.spec_hygiene import normalize_specs

# The record schema version this build WRITES. Bump it when the shape changes in a way an
# older build cannot faithfully reproduce.
#   1 = flat, implicitly-KiCad `symbol`/`footprint`/`model` plus `altium_symbol`/`altium_footprint`
#   2 = the per-tool `eda` map (one symmetric EdaAssets bundle per EDA registry key)
#
# This exists because peers share these records through git and BOTH write them. Kubernetes'
# API conventions state the rule: patching a resource at schema version N-1 must not erase
# fields defined at version N. Before this, an older build editing one field on a newer
# peer's part silently deleted every field it did not recognise, and git recorded the
# deletion as an intentional change. `extra` (below) is the other half of that guarantee.
SCHEMA_VERSION = 2

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
# its IDENTITY + SOURCING alone. The KiCad assets (symbol / footprint / 3D model) are NO
# LONGER gated - a part is added first and its assets are attached afterwards (attach_symbol
# / attach_footprint / attach_model). This lets a whole BOM land as tracked records
# immediately, then be completed at leisure. Each pair is (presence-flag key, human label);
# the key names a flag, not a record attribute directly, so the same set gates staged inputs
# and finished records alike. symbol/footprint/model presence is still COMPUTED (for the
# "assets attached?" UI + drift checks), just not REQUIRED here.
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


def asset_present(ref) -> bool:
    """True when an asset reference actually resolves to something.

    Generic across kinds on purpose: an entry-shaped asset (symbol, footprint) is
    identified by `name`, a file-shaped one (3D model) by `file`. A container with no
    entry (`lib` alone) is NOT present -- that half-filled state is what produced the
    dangling `Footprint` property fixed in 21fce45.
    """
    return ref is not None and bool(ref.name or ref.file)


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
class AssetRef:
    """One EDA asset reference, in a shape every tool shares.

    `lib` names the container (a KiCad `.kicad_sym` library nickname, an Altium `.SchLib`
    / `.PcbLib` filename relative to `<profile>/altium/`), `name` the exact entry inside
    it (the value KiCad's `lib_id` or Altium's `[Library Ref]` / `[Footprint Ref]`
    resolves), and `file` the repo-relative path for a file-shaped asset such as a 3D
    model, which has no container or entry name. A kind fills the fields it needs and
    leaves the rest blank; nothing here is tool-specific, because per-tool facts belong in
    `stockroom.eda.registry`, not in the record shape.

    Vendor library files are stored verbatim -- Stockroom only reads their entry names.
    """

    lib: str = ""
    name: str = ""
    file: str = ""


@dataclass
class EdaAssets:
    """Everything ONE EDA tool holds for one part.

    Each tool gets a full, symmetric bundle. That symmetry is the point: the previous
    record had implicitly-KiCad flat `symbol`/`footprint`/`model` fields plus bolted-on
    `altium_symbol`/`altium_footprint` and NO Altium model slot, so readiness code had to
    branch on the tool -- which is how every part read "CAD Incomplete" forever and how an
    Altium attach silently clobbered the KiCad reference.
    """

    symbol: AssetRef | None = None
    footprint: AssetRef | None = None
    model: AssetRef | None = None

    def get(self, kind: str) -> AssetRef | None:
        """The reference for an asset kind, or None. Lets generic code iterate a tool's
        registered `asset_kinds` instead of naming symbol/footprint/model by hand."""
        return getattr(self, kind, None)

    def set(self, kind: str, ref: AssetRef | None) -> None:
        if not hasattr(self, kind):
            raise KeyError(f"unknown asset kind {kind!r}")
        setattr(self, kind, ref)

    def is_empty(self) -> bool:
        return self.symbol is None and self.footprint is None and self.model is None

    def to_dict(self) -> dict:
        return {
            "symbol": asdict(self.symbol) if self.symbol else None,
            "footprint": asdict(self.footprint) if self.footprint else None,
            "model": asdict(self.model) if self.model else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EdaAssets":
        def ref(key):
            raw = d.get(key)
            if not raw:
                return None
            # Tolerate an unknown extra key (e.g. a legacy `tool` discriminator) rather
            # than exploding on a record written by another build.
            return AssetRef(
                lib=raw.get("lib", ""), name=raw.get("name", ""), file=raw.get("file", "")
            )

        return cls(symbol=ref("symbol"), footprint=ref("footprint"), model=ref("model"))


# The pre-cutover flat fields, mapped to (default tool, asset kind). Records written before
# the per-EDA cutover are folded into `eda` on read so the owner's existing library upgrades
# in place on its next write instead of losing every attached asset. A legacy ref carrying an
# explicit `tool` discriminator is honoured over the default here.
_LEGACY_ASSET_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("symbol", "kicad", "symbol"),
    ("footprint", "kicad", "footprint"),
    ("model", "kicad", "model"),
    ("altium_symbol", "altium", "symbol"),
    ("altium_footprint", "altium", "footprint"),
)


# Every top-level key this build understands: the current shape, plus the legacy asset fields
# that `_read_eda` CONSUMES (folding them into `eda`). Anything outside this set is a field
# from a newer build and is preserved verbatim in `PartRecord.extra`. A legacy field must be
# listed here or the record would carry two contradictory copies of its assets.
_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "id",
        "display_name",
        "category",
        "description",
        "tags",
        "mpn",
        "manufacturer",
        "value",
        "passive",
        "datasheet",
        "purchase",
        "eda",
        "provenance",
        "hashes",
        "enrichment",
        "specs",
    }
    | {legacy for legacy, _, _ in _LEGACY_ASSET_FIELDS}
)


def _read_eda(d: dict) -> dict[str, EdaAssets]:
    """The per-tool asset map for a record dict, in either format.

    The new `eda` map wins outright when present; otherwise the legacy flat fields are
    folded in. Tool keys this build does not recognise are preserved verbatim rather than
    dropped -- a peer running a newer Stockroom must not lose their work on our next write.
    """
    raw = d.get("eda")
    if raw:
        return {tool: EdaAssets.from_dict(a or {}) for tool, a in raw.items()}

    out: dict[str, EdaAssets] = {}
    for legacy_key, default_tool, kind in _LEGACY_ASSET_FIELDS:
        ref = d.get(legacy_key)
        if not ref:
            continue
        tool = ref.get("tool") or default_tool
        out.setdefault(tool, EdaAssets()).set(
            kind,
            AssetRef(
                lib=ref.get("lib", ""), name=ref.get("name", ""), file=ref.get("file", "")
            ),
        )
    return out


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
class PartRecord:
    id: str
    display_name: str
    category: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    mpn: str = ""
    manufacturer: str = ""
    # The component Value shown on a schematic + in a BOM (e.g. "10k", "1µF" for a
    # passive; the MPN for an active). Mirrored to the symbol's Value property so a
    # placed part is self-describing. Derived on rebuild (ingest/component_naming).
    value: str = ""
    # A passive (R/C/L) references KiCad STOCK symbol/footprint/3D by lib_id rather
    # than owning copied asset files (the generic package is already in KiCad). The
    # completion gate is relaxed accordingly: a passive needs no owned 3D model, and
    # its symbol/footprint are satisfied by the stock lib_ids (spec: drop-in passives).
    passive: bool = False
    datasheet: Datasheet | None = None
    purchase: list[Purchase] = field(default_factory=list)
    # The CAD assets, one symmetric bundle per EDA tool, keyed by the tool key in
    # `stockroom.eda.registry` ("kicad", "altium", ...). Every registered tool always has an
    # entry (see __post_init__), so `record.eda[tool].symbol = ref` is always a live write;
    # empty bundles are dropped on serialization so the JSON stays minimal.
    eda: dict[str, EdaAssets] = field(default_factory=dict)
    provenance: Provenance | None = None
    hashes: Hashes | None = None
    enrichment: dict[str, EnrichmentField] = field(default_factory=dict)
    # Canonical, high-confidence spec data persisted from enrichment (e.g. the
    # pinout extracted from the datasheet) so a viewer reads the source of truth,
    # not a transient enrich call. A free-form value bag keyed by spec name
    # (specs["pinout"] is a list of {"pin", "name"} dicts); per-key provenance
    # lives in `enrichment`. NOT a completion-gate field (spec section 6): a part
    # without a pinout is still complete.
    specs: dict = field(default_factory=dict)
    # The schema version this record was WRITTEN at. A record read from disk keeps its own
    # value (never downgraded to ours), so a build that does not fully understand a newer
    # record cannot claim otherwise to the next reader. See SCHEMA_VERSION.
    schema_version: int = SCHEMA_VERSION
    # Top-level keys this build does not recognise, kept verbatim and re-emitted on write.
    # Without this, an older Stockroom editing one field on a newer peer's part would DELETE
    # every field it had never heard of, and git would record that as an intentional change.
    # Not part of the public shape: never read from here, only preserved through it.
    extra: dict = field(default_factory=dict)

    def is_future_schema(self) -> bool:
        """True when this record was written by a build newer than ours. It is still loaded
        and still round-trips losslessly (see `extra`), but a caller that is about to REWRITE
        its structure should say so rather than assume it understood everything."""
        return self.schema_version > SCHEMA_VERSION

    def __post_init__(self) -> None:
        # Canonicalize spec keys/values on construction (covers from_dict + direct
        # build). A later direct mutation of self.specs (as the enrich pipeline does)
        # is re-cleaned by to_dict, so persisted + served data is always clean.
        self.specs = normalize_specs(self.specs)
        # Every registered tool always has a live bundle, so `assets_for(tool).symbol = ref`
        # can never write into a throwaway object that is silently discarded. Bundles for
        # tools this build does not know (written by a newer peer) are left untouched.
        for tool in all_tools():
            self.eda.setdefault(tool.key, EdaAssets())

    def assets_for(self, tool: str) -> EdaAssets:
        """The LIVE asset bundle for `tool` -- mutating it mutates the record.

        Raises KeyError for a tool that is neither registered nor already present on the
        record. Never falls back to KiCad: that silent fallback is exactly what let an
        Altium attach overwrite the KiCad reference (f7d80ac).
        """
        if tool not in self.eda:
            get_tool(tool)  # raises with the known-tool list
            self.eda[tool] = EdaAssets()
        return self.eda[tool]

    def to_dict(self) -> dict:
        # Unknown keys first so a known key can never be shadowed by a stale preserved copy
        # of itself; `dumps` sorts keys anyway, so ordering here is about precedence only.
        return {
            **self.extra,
            "schema_version": self.schema_version,
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "tags": list(self.tags),
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "value": self.value,
            "passive": self.passive,
            "datasheet": asdict(self.datasheet) if self.datasheet else None,
            "purchase": [asdict(p) for p in self.purchase],
            # Empty bundles are omitted: a part with only KiCad assets should not carry a
            # wall of nulls for every other tool, and a one-field edit stays a one-line diff.
            "eda": {k: a.to_dict() for k, a in self.eda.items() if not a.is_empty()},
            "provenance": asdict(self.provenance) if self.provenance else None,
            "hashes": asdict(self.hashes) if self.hashes else None,
            "enrichment": {k: asdict(v) for k, v in self.enrichment.items()},
            "specs": normalize_specs(self.specs),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PartRecord":
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            category=d["category"],
            description=d.get("description", ""),
            tags=list(d.get("tags", [])),
            mpn=d.get("mpn", ""),
            manufacturer=d.get("manufacturer", ""),
            value=d.get("value", ""),
            passive=bool(d.get("passive", False)),
            datasheet=Datasheet(**d["datasheet"]) if d.get("datasheet") else None,
            purchase=[Purchase(**p) for p in d.get("purchase", [])],
            eda=_read_eda(d),
            # A record with no version predates versioning, which is exactly schema 1. The
            # value we carry (and re-emit) is the HIGHER of that and ours, because both
            # directions matter: reading a v1 record UPGRADES it (we fold it into the v2
            # shape in memory and write it that way), while reading a future record must not
            # DOWNGRADE the stamp -- that would tell the next reader a record still holding
            # material we never understood is fully understood at our version.
            schema_version=max(SCHEMA_VERSION, int(d.get("schema_version", 1))),
            extra={k: v for k, v in d.items() if k not in _KNOWN_KEYS},
            provenance=Provenance(**d["provenance"]) if d.get("provenance") else None,
            hashes=Hashes(**d["hashes"]) if d.get("hashes") else None,
            enrichment={
                k: EnrichmentField(**v) for k, v in d.get("enrichment", {}).items()
            },
            specs=dict(d.get("specs", {})),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "PartRecord":
        return cls.from_dict(json.loads(text))

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

    def missing_assets(self, tool: str) -> list[str]:
        """Human labels of the assets `tool` still lacks, in the tool's registered kind
        order. Not part of completeness -- a part is complete without any assets now -- but
        it tells the UI what can still be attached.

        A kind the tool cannot take by reference at all (Altium's 3D model, which lives
        inside the footprint's `.PcbLib` binary) is skipped: reporting it would be a gap
        that can never be closed. A passive inherits the stock footprint's own 3D model, so
        it needs no owned model file.
        """
        assets = self.assets_for(tool)
        spec = get_tool(tool)
        out: list[str] = []
        for kind in spec.asset_kinds:
            if kind in spec.unsupported_assets:
                continue
            if kind == "model" and self.passive:
                continue
            if not asset_present(assets.get(kind)):
                out.append(asset_label(kind))
        return out

    def missing_assets_by_tool(self) -> dict[str, list[str]]:
        """`missing_assets` for every registered tool. The generic entry point the API and
        capture layer use, so a third tool is covered by registering it and nothing else."""
        return {tool.key: self.missing_assets(tool.key) for tool in all_tools()}

    def is_complete(self) -> bool:
        return not self.missing_fields()


def new_part_id(parts_dir: Path, base: str) -> str:
    """A stable, unique, never-reused id derived from `base` (an MPN or name).

    Slug of `base`; if `parts/<slug>.json` exists, suffix -2, -3, ... A base
    that slugifies to empty falls back to 'part'."""
    parts_dir = Path(parts_dir)
    slug = slugify(base) or "part"
    candidate = slug
    n = 1
    while (parts_dir / f"{candidate}.json").exists():
        n += 1
        candidate = f"{slug}-{n}"
    return candidate
