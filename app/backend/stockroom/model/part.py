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

from stockroom.model.category import slugify
from stockroom.model.spec_hygiene import normalize_specs

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

# The KiCad assets that are attachable AFTER a part is added (no longer gate entry). Used
# by the UI to show which assets a landed part still needs. (presence-key, human label).
ATTACHABLE_ASSETS: tuple[tuple[str, str], ...] = (
    ("symbol", "symbol"),
    ("footprint", "footprint"),
    ("model", "3D model"),
)


def missing_from_presence(present: dict[str, bool]) -> list[str]:
    """Given a {field_key: present} map, return the human labels of the required
    fields that are missing, in passport order. The single source of truth for both
    the complete-to-add gate (checked on staged inputs) and PartRecord.is_complete
    (checked on the canonical record), so the two can never drift apart."""
    return [label for key, label in REQUIRED_FIELDS if not present.get(key)]


def missing_assets_from_presence(present: dict[str, bool]) -> list[str]:
    """Human labels of the attachable KiCad assets (symbol / footprint / 3D model) a
    part does not yet carry. These no longer gate entry (a part is added first, assets
    attached after), so this drives the "still needs" affordance in the UI, NOT the gate."""
    return [label for key, label in ATTACHABLE_ASSETS if not present.get(key)]


def altium_assets_ready(record) -> bool:
    """True when a part carries both an Altium symbol and footprint with resolved entry
    names. Advisory: gates only what the DbLib emitter writes, not the complete-to-add gate.
    (Whether the footprint embeds a STEP body is not checkable here; that is the owner's
    manual step.)"""
    return (
        record.altium_symbol is not None and bool(record.altium_symbol.name)
        and record.altium_footprint is not None and bool(record.altium_footprint.name)
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
class LibRef:
    lib: str = ""
    name: str = ""
    # Which EDA tool this symbol/footprint targets. "kicad" today; "altium" (etc.) later,
    # so one part can carry a symbol/footprint per tool. Surfaced as a pill in the UI.
    # Defaults to "kicad" so every pre-existing record reads back as a KiCad asset.
    tool: str = "kicad"


@dataclass
class ModelRef:
    file: str = ""
    # A 3D model (STEP/WRL) is largely tool-neutral, but tag it too so a future Altium
    # import can carry its own model without ambiguity.
    tool: str = "kicad"


@dataclass
class AltiumRef:
    """An Altium symbol/footprint reference: the .SchLib/.PcbLib filename (relative to
    <profile>/altium/) + the exact entry name inside that OLE compound file (the value
    Altium's [Library Ref]/[Footprint Ref] resolves). Vendor files are stored verbatim;
    Stockroom only reads their names, never edits them."""
    lib: str = ""
    name: str = ""
    tool: str = "altium"


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
    symbol: LibRef | None = None
    footprint: LibRef | None = None
    model: ModelRef | None = None
    # The Altium half of the cross-EDA asset pair (parallel to symbol/footprint above). The
    # shared 3D `model` above is EDA-neutral and serves both. None until acquired.
    altium_symbol: AltiumRef | None = None
    altium_footprint: AltiumRef | None = None
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

    def __post_init__(self) -> None:
        # Canonicalize spec keys/values on construction (covers from_dict + direct
        # build). A later direct mutation of self.specs (as the enrich pipeline does)
        # is re-cleaned by to_dict, so persisted + served data is always clean.
        self.specs = normalize_specs(self.specs)

    def to_dict(self) -> dict:
        return {
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
            "symbol": asdict(self.symbol) if self.symbol else None,
            "footprint": asdict(self.footprint) if self.footprint else None,
            "model": asdict(self.model) if self.model else None,
            "altium_symbol": asdict(self.altium_symbol) if self.altium_symbol else None,
            "altium_footprint": asdict(self.altium_footprint) if self.altium_footprint else None,
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
            symbol=LibRef(**d["symbol"]) if d.get("symbol") else None,
            footprint=LibRef(**d["footprint"]) if d.get("footprint") else None,
            model=ModelRef(**d["model"]) if d.get("model") else None,
            altium_symbol=AltiumRef(**d["altium_symbol"]) if d.get("altium_symbol") else None,
            altium_footprint=AltiumRef(**d["altium_footprint"]) if d.get("altium_footprint") else None,
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
            "symbol": self.symbol is not None and bool(self.symbol.name),
            "footprint": self.footprint is not None and bool(self.footprint.name),
            # A passive inherits the stock footprint's own 3D model, so it needs no
            # owned model file to be complete.
            "model": self.passive or (self.model is not None and bool(self.model.file)),
            # A datasheet is satisfied by a stored PDF OR a datasheet URL (owner: keep
            # datasheet URLs as a first-class field; a known link should not block).
            "datasheet": self.datasheet is not None
            and (bool(self.datasheet.file) or bool(self.datasheet.source_url)),
            "purchase": any(bool(p.url) for p in self.purchase),
        }

    def missing_fields(self) -> list[str]:
        """Human labels of the required passport fields this record lacks (empty => complete)."""
        return missing_from_presence(self._presence())

    def missing_assets(self) -> list[str]:
        """Human labels of the attachable KiCad assets this part still lacks (symbol /
        footprint / 3D model). Not part of completeness - a part is complete without them
        now - but tells the UI what can still be attached."""
        return missing_assets_from_presence(self._presence())

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
