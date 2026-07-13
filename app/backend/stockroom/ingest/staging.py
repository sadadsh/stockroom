"""A review card per candidate part: the converted files, proposed name and
category, honestly-flagged gaps, and provenance. Projects onto the M2
StagedPart seam once the user finalizes it (spec section 5, stages 3 and 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.errors import IngestError
from stockroom.model.part import Datasheet, Provenance
from stockroom.mutation.library_ops import StagedPart


@dataclass
class StagingCandidate:
    vendor: str
    symbol_lib_path: Path | None
    symbol_name: str
    footprint_variants: list[Path]
    chosen_footprint_index: int = 0
    model_path: Path | None = None
    datasheet_path: Path | None = None
    display_name: str = ""
    entry_name: str = ""
    category: str = "Other"
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    @property
    def chosen_footprint(self) -> Path | None:
        if not self.footprint_variants:
            return None
        idx = self.chosen_footprint_index
        if idx < 0 or idx >= len(self.footprint_variants):
            raise IngestError(f"footprint index {idx} out of range")
        return self.footprint_variants[idx]

    def to_staged_part(self) -> StagedPart:
        if self.symbol_lib_path is None:
            raise IngestError("candidate has no symbol; cannot stage")
        fp = self.chosen_footprint
        if fp is None:
            raise IngestError("candidate has no footprint; cannot stage")
        datasheet_meta = None
        if self.provenance is not None and self.provenance.source_url:
            datasheet_meta = Datasheet(source_url=self.provenance.source_url)
        return StagedPart(
            display_name=self.display_name,
            category=self.category,
            mpn=self.mpn,
            manufacturer=self.manufacturer,
            description=self.description,
            tags=list(self.tags),
            symbol_source=self.symbol_lib_path,
            symbol_source_name=self.symbol_name,
            footprint_source=fp,
            entry_name=self.entry_name,
            model_source=self.model_path,
            datasheet_source=self.datasheet_path,
            provenance=self.provenance,
            datasheet_meta=datasheet_meta,
        )
