"""A review card per candidate part: the converted files, proposed name and
category, honestly-flagged gaps, and provenance. Projects onto the M2
StagedPart seam once the user finalizes it (spec section 5, stages 3 and 5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.ingest.convert import normalize_footprint, normalize_symbol, read_symbol_names
from stockroom.ingest.errors import IngestError
from stockroom.ingest.fingerprint import DetectedSource
from stockroom.ingest.naming import propose_category, propose_display_name, propose_entry_name
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.part import Datasheet, Provenance, Purchase
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
    # Sourcing links a raw package never carries; filled by M4 enrichment or a
    # manual review edit so the candidate can satisfy the complete-to-add gate
    # (spec section 6, purchase link is a required passport field).
    purchase: list[Purchase] = field(default_factory=list)
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
            purchase=list(self.purchase),
        )


def _symbol_metadata(sym_lib: SymbolLib, name: str) -> tuple[str, list[str]]:
    sym = sym_lib.get_symbol(name)
    description = sym.get_property("Description") or ""
    keywords = sym.get_property("ki_keywords") or ""
    tags = [t for t in keywords.split() if t]
    return description, tags


def build_candidates(
    cli: KiCadCli | None,
    detected: DetectedSource,
    workdir: Path,
    provenance: Provenance | None = None,
) -> list[StagingCandidate]:
    workdir = Path(workdir)

    if detected.vendor == "partial" or detected.symbol_path is None:
        return [
            StagingCandidate(
                vendor=detected.vendor,
                symbol_lib_path=None,
                symbol_name="",
                footprint_variants=[],
                model_path=detected.model_path,
                datasheet_path=detected.datasheet_path,
                gaps=["package contains only a 3D model; attach it to an existing part"],
                provenance=provenance,
            )
        ]

    sym_workdir = workdir / "symbol"
    normalized_sym = normalize_symbol(cli, detected.symbol_path, detected.dcm_path, sym_workdir)
    sym_lib = SymbolLib.load(normalized_sym)
    names = read_symbol_names(normalized_sym)
    if not names:
        raise IngestError(f"no symbol found inside {detected.symbol_path.name}")

    variants: list[Path] = []
    for i, fp in enumerate(detected.footprint_paths):
        variants.append(normalize_footprint(cli, fp, workdir / f"fp{i}"))

    candidates: list[StagingCandidate] = []
    for name in names:
        description, tags = _symbol_metadata(sym_lib, name)
        gaps: list[str] = []
        if not variants:
            gaps.append("no footprint in this package")
        if detected.model_path is None:
            gaps.append("no 3D model in this package")
        if detected.datasheet_path is None:
            gaps.append("no datasheet in this package")
        candidates.append(
            StagingCandidate(
                vendor=detected.vendor,
                symbol_lib_path=normalized_sym,
                symbol_name=name,
                footprint_variants=list(variants),
                model_path=detected.model_path,
                datasheet_path=detected.datasheet_path,
                display_name=propose_display_name(name),
                entry_name=propose_entry_name(name),
                category=propose_category(f"{name} {description} {' '.join(tags)}"),
                description=description,
                tags=tags,
                gaps=gaps,
                provenance=provenance,
            )
        )
    return candidates


def _identity_key(text: str) -> str:
    """Case/punctuation-insensitive identity token for matching a fragment to the
    candidate it completes (MPN-B == mpn-b == MPN_B)."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _fragment_keys(c: StagingCandidate) -> set[str]:
    return {k for k in (_identity_key(c.mpn), _identity_key(c.display_name),
                        _identity_key(c.entry_name)) if k}


def _full_keys(c: StagingCandidate) -> set[str]:
    return {k for k in (_identity_key(c.mpn), _identity_key(c.display_name),
                        _identity_key(c.entry_name), _identity_key(c.symbol_name)) if k}


def _refresh_asset_gaps(c: StagingCandidate) -> None:
    c.gaps = [
        g for g in c.gaps
        if not (("3D model" in g and c.model_path is not None)
                or ("datasheet" in g and c.datasheet_path is not None))
    ]


def _absorb(target: StagingCandidate, frag: StagingCandidate) -> bool:
    """Move the fragment's assets onto the target where the target lacks them.
    True only when the whole fragment was consumed; a leftover asset (the target
    already had its own) keeps the fragment alive so nothing is silently dropped."""
    took_any = False
    leftover = False
    if frag.model_path is not None:
        if target.model_path is None:
            target.model_path = frag.model_path
            took_any = True
        else:
            leftover = True
    if frag.datasheet_path is not None:
        if target.datasheet_path is None:
            target.datasheet_path = frag.datasheet_path
            took_any = True
        else:
            leftover = True
    if took_any:
        _refresh_asset_gaps(target)
    return took_any and not leftover


def merge_candidates(candidates: list[StagingCandidate]) -> list[StagingCandidate]:
    """Fold symbol-less fragments (a bare 3D model or datasheet, the second half
    of a split vendor download) into the symbol-bearing candidate they complete.
    Conservative: a fragment with an identity merges into the full candidate whose
    identity matches; an anonymous fragment merges only when exactly ONE full
    candidate exists (the common two-file case). Anything ambiguous stays a
    separate attach-to-existing card, never a guess."""
    fulls = [c for c in candidates if c.symbol_lib_path is not None]
    out: list[StagingCandidate] = []
    for c in candidates:
        if c.symbol_lib_path is not None:
            out.append(c)
            continue
        keys = _fragment_keys(c)
        if keys:
            matches = [f for f in fulls if keys & _full_keys(f)]
        else:
            matches = list(fulls)
        if len(matches) == 1 and _absorb(matches[0], c):
            continue  # fully consumed by the candidate it completes
        out.append(c)
    return out
