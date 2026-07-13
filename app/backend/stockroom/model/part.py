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

# KiCad-visible fields mirrored INTO symbol properties so KiCad shows a complete
# part even without Stockroom (spec section 3). Maps record-derived value ->
# KiCad property name; the actual value extraction lives in mutation/placement.
KICAD_MIRROR_FIELDS: tuple[str, ...] = (
    "MPN",
    "Manufacturer",
    "Datasheet",
    "Description",
    "ki_keywords",
    "Purchase",
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
    price_breaks: list = field(default_factory=list)
    stock: int | None = None
    currency: str = ""
    fetched_at: str = ""


@dataclass
class LibRef:
    lib: str = ""
    name: str = ""


@dataclass
class ModelRef:
    file: str = ""


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
    datasheet: Datasheet | None = None
    purchase: list[Purchase] = field(default_factory=list)
    symbol: LibRef | None = None
    footprint: LibRef | None = None
    model: ModelRef | None = None
    provenance: Provenance | None = None
    hashes: Hashes | None = None
    enrichment: dict[str, EnrichmentField] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "tags": list(self.tags),
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "datasheet": asdict(self.datasheet) if self.datasheet else None,
            "purchase": [asdict(p) for p in self.purchase],
            "symbol": asdict(self.symbol) if self.symbol else None,
            "footprint": asdict(self.footprint) if self.footprint else None,
            "model": asdict(self.model) if self.model else None,
            "provenance": asdict(self.provenance) if self.provenance else None,
            "hashes": asdict(self.hashes) if self.hashes else None,
            "enrichment": {k: asdict(v) for k, v in self.enrichment.items()},
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
            datasheet=Datasheet(**d["datasheet"]) if d.get("datasheet") else None,
            purchase=[Purchase(**p) for p in d.get("purchase", [])],
            symbol=LibRef(**d["symbol"]) if d.get("symbol") else None,
            footprint=LibRef(**d["footprint"]) if d.get("footprint") else None,
            model=ModelRef(**d["model"]) if d.get("model") else None,
            provenance=Provenance(**d["provenance"]) if d.get("provenance") else None,
            hashes=Hashes(**d["hashes"]) if d.get("hashes") else None,
            enrichment={
                k: EnrichmentField(**v) for k, v in d.get("enrichment", {}).items()
            },
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "PartRecord":
        return cls.from_dict(json.loads(text))


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
