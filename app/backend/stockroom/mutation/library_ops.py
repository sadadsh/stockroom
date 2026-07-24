"""High-level, atomic library operations: add / edit / move-category / delete a
part, and drift detection. Each mutation runs inside one git-backed Transaction
so it either commits as a single scoped commit or leaves zero trace (spec
sections 3, 5, 9).
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.sexp.document import SexpDocument

from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.category import category_nickname
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value
from stockroom.model.part import (
    AltiumRef,
    Datasheet,
    EnrichmentField,
    LibRef,
    ModelRef,
    PartRecord,
    Provenance,
    Purchase,
    missing_from_presence,
    new_part_id,
)
from stockroom.mutation.placement import (
    kicad_visible_properties,
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)
from stockroom.mutation.transaction import Transaction
from stockroom.ingest.describe import apply_clean_identity
from stockroom.store.profile import Profile
from stockroom.vcs.repo import GitRepo


# top-level record field -> KiCad property to re-mirror on edit (None => no mirror)
_MIRROR_ON_EDIT = {
    "mpn": "MPN",
    "manufacturer": "Manufacturer",
    "description": "Description",
}

# suffixes/names the repair sweep must be able to re-parse before it commits a file;
# mirrors the transaction's own validation set so a swept file that would abort the
# whole transaction is caught (and reported) up front instead.
_SEXP_SUFFIXES = {".kicad_sym", ".kicad_mod", ".kicad_sch", ".kicad_pcb"}
_SEXP_TABLE_NAMES = {"sym-lib-table", "fp-lib-table"}


@dataclass
class StagedPart:
    display_name: str
    category: str
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    symbol_source: Path | None = None
    symbol_source_name: str = ""
    footprint_source: Path | None = None
    entry_name: str = ""
    model_source: Path | None = None
    datasheet_source: Path | None = None
    provenance: Provenance | None = None
    datasheet_meta: Datasheet | None = None
    purchase: list[Purchase] = field(default_factory=list)
    specs: dict = field(default_factory=dict)


class IncompleteError(ValueError):
    """Raised when add_part is asked to add a part that fails the strict completion
    passport (spec section 6). Carries the list of missing field labels so the caller
    (UI or API) can tell the user exactly what to fill."""

    def __init__(self, missing: list[str]):
        self.missing = list(missing)
        super().__init__("cannot add an incomplete part; missing: " + ", ".join(missing))


def staged_missing_fields(staged: "StagedPart") -> list[str]:
    """The passport fields a staged part is missing, using the SAME required set as
    PartRecord.is_complete (via model.part.missing_from_presence), so the gate and the
    record's own completeness can never disagree."""
    present = {
        "display_name": bool(staged.display_name.strip()),
        "mpn": bool(staged.mpn.strip()),
        "manufacturer": bool(staged.manufacturer.strip()),
        "category": bool(staged.category.strip()),
        "description": bool(staged.description.strip()),
        "symbol": staged.symbol_source is not None and bool(staged.entry_name),
        "footprint": staged.footprint_source is not None,
        "model": staged.model_source is not None,
        # A datasheet is satisfied by a downloaded PDF OR a known link (the same
        # rule PartRecord.is_complete uses), so a pulled datasheet URL is enough to
        # add a part; the two completeness checks can never disagree.
        "datasheet": staged.datasheet_source is not None
        or (staged.datasheet_meta is not None and bool(staged.datasheet_meta.source_url)),
        "purchase": any(bool(p.url) for p in staged.purchase),
    }
    return missing_from_presence(present)


def _reference_commit_message(record: PartRecord) -> str:
    """A plain, one-line commit subject for a file-less add that adapts to whatever refs
    the record already carries (a passive lands with stock lib_ids; an asset-less part
    lands with none, to be attached later)."""
    refs = []
    if record.symbol is not None and record.symbol.name:
        refs.append(f"{record.symbol.lib}:{record.symbol.name} symbol")
    if record.footprint is not None and record.footprint.name:
        refs.append(f"{record.footprint.lib}:{record.footprint.name} footprint")
    kind = "passive" if record.passive else record.category
    detail = (", ".join(refs) + " reference, ") if refs else ""
    return f"Add {record.display_name} ({kind}): {detail}record"


@dataclass
class DriftItem:
    part_id: str
    property: str
    json_value: str
    symbol_value: str


@dataclass
class DriftReport:
    items: list[DriftItem] = field(default_factory=list)
    missing_symbol: list[str] = field(default_factory=list)


@dataclass
class RepairAction:
    """A defect the doctor can heal automatically and idempotently. `before`/`after`
    let the UI show the exact diff before the user commits to the repair."""

    kind: str  # "drift" | "model_path"
    part_id: str
    detail: str
    before: str
    after: str


@dataclass
class RepairFinding:
    """A defect the doctor detected but CANNOT auto-fix (a missing file can't be
    fabricated). Reported honestly with how to resolve it by hand, never silently
    dropped or papered over by deleting the reference."""

    kind: str  # "missing_symbol" | "dangling_model" | "dangling_datasheet" | "dangling_model_link"
    part_id: str
    detail: str
    how_to_fix: str


@dataclass
class RepairPlan:
    fixable: list[RepairAction] = field(default_factory=list)
    manual: list[RepairFinding] = field(default_factory=list)
    uncommitted: list[str] = field(default_factory=list)  # git porcelain lines

    @property
    def is_healthy(self) -> bool:
        return not (self.fixable or self.manual or self.uncommitted)


@dataclass
class RepairResult:
    healed_drift: int = 0
    fixed_paths: int = 0
    committed_files: int = 0
    hidden_metadata: int = 0
    commit: str = ""
    manual: list[RepairFinding] = field(default_factory=list)


class LibraryOps:
    def __init__(self, profile: Profile, repo: GitRepo, cli=None):
        self.profile = profile
        self.repo = repo
        self.lib = profile.library
        self.cli = cli

    def add_part(self, staged: StagedPart, require_complete: bool = True) -> PartRecord:
        # Complete-to-add gate (spec section 6): the primary library is complete-only.
        # Fails BEFORE any file write, so a rejected add leaves zero trace. An archive
        # profile is grandfathered (spec section 7), so its adds bypass the gate
        # automatically; callers may also pass require_complete=False explicitly.
        if require_complete and not self.profile.is_archive:
            missing = staged_missing_fields(staged)
            if missing:
                raise IncompleteError(missing)
        # A symbol source with no entry name would merge a symbol named "" into the
        # category lib; refuse honestly before any write.
        if staged.symbol_source is not None and not staged.entry_name:
            raise ValueError("a staged symbol needs an entry name to merge under")
        part_id = new_part_id(self.lib.parts_dir, staged.mpn or staged.display_name)
        nickname = category_nickname(staged.category)
        sym_lib_path = self.lib.symbol_lib_path(staged.category)
        pretty_dir = self.lib.footprint_lib_path(staged.category)

        # capture dirs that do not yet exist so a rollback prunes them; git cannot track
        # an empty dir, so a brand-new category's .pretty (and the profile dirs, on the
        # very first add) would otherwise survive a failed mutation (zero-trace, sec 2.2).
        fresh_dirs = [
            d
            for d in (self.lib.parts_dir, self.lib.models_dir, self.lib.datasheets_dir, pretty_dir)
            if not d.exists()
        ]
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        self.lib.models_dir.mkdir(parents=True, exist_ok=True)
        self.lib.datasheets_dir.mkdir(parents=True, exist_ok=True)

        with Transaction(self.repo) as txn:
            txn.track_dir(*fresh_dirs)
            # Every asset step is conditional: the primary add flow lands a part on its
            # identity + sourcing alone (owner 2026-07-16 / 2026-07-24) and the guided
            # capture attaches both EDA formats afterwards. A file-less add fabricates
            # NO asset files and records None refs, never a dangling LibRef.
            # 0. ensure the category libraries exist (idempotent); a freshly created
            # empty symbol lib is tracked so it commits atomically.
            if staged.footprint_source is not None:
                ensure_footprint_lib(pretty_dir)
            if staged.symbol_source is not None and not sym_lib_path.exists():
                if self.cli is None:
                    raise ValueError(
                        f"category symbol library {sym_lib_path.name} is missing and "
                        "no kicad-cli was provided to create it"
                    )
                create_empty_symbol_lib(self.cli, sym_lib_path)
                txn.track(sym_lib_path)

            # 1. merge the symbol (renamed to entry_name) into the category lib
            if staged.symbol_source is not None:
                merge_symbol_into_lib(
                    sym_lib_path, staged.symbol_source, staged.symbol_source_name, staged.entry_name
                )
                txn.track(sym_lib_path)

            # 2. place the footprint into the category .pretty
            fp_path = None
            if staged.footprint_source is not None:
                fp_path = place_footprint(pretty_dir, staged.footprint_source, staged.entry_name)
                txn.track(fp_path)

            # 3. model file + (model ...) link (the link only when a footprint landed)
            model_ref = None
            if staged.model_source is not None:
                model_name = f"{staged.entry_name or part_id}{Path(staged.model_source).suffix}"
                model_dst = self.lib.models_dir / model_name
                shutil.copyfile(staged.model_source, model_dst)
                txn.track(model_dst)
                if fp_path is not None:
                    fp = Footprint.load(fp_path)
                    fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
                    fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
                model_ref = ModelRef(file=f"models/{model_name}")

            # 4. datasheet: a downloaded PDF, a known link, or both. A URL-only
            # datasheet still lands on the record (the link is a first-class field),
            # so a part added from a pulled link keeps that link.
            datasheet = staged.datasheet_meta
            if staged.datasheet_source is not None:
                ds_name = f"{part_id}.pdf"
                ds_dst = self.lib.datasheets_dir / ds_name
                shutil.copyfile(staged.datasheet_source, ds_dst)
                txn.track(ds_dst)
                datasheet = staged.datasheet_meta or Datasheet()
                datasheet.file = ds_name

            # 5. the symbol's Footprint property, then mirror KiCad-visible fields
            record = PartRecord(
                id=part_id,
                display_name=staged.display_name,
                category=staged.category,
                description=staged.description,
                tags=list(staged.tags),
                mpn=staged.mpn,
                manufacturer=staged.manufacturer,
                datasheet=datasheet,
                symbol=LibRef(lib=nickname, name=staged.entry_name)
                if staged.symbol_source is not None else None,
                footprint=LibRef(lib=nickname, name=staged.entry_name)
                if staged.footprint_source is not None else None,
                model=model_ref,
                provenance=staged.provenance,
                purchase=list(staged.purchase),
                specs=dict(staged.specs),
            )
            if staged.symbol_source is not None:
                sym_lib = SymbolLib.load(sym_lib_path)
                sym = sym_lib.get_symbol(staged.entry_name)
                sym.set_property("Footprint", f"{nickname}:{staged.entry_name}")
                mirror_fields_to_symbol(sym, record)
                sym_lib.save(sym_lib_path)

            # 6. the JSON record
            json_path = self.lib.parts_dir / f"{part_id}.json"
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)

            placed = [p for p, there in (
                ("symbol", staged.symbol_source is not None),
                ("footprint", staged.footprint_source is not None),
                ("3D model", model_ref is not None),
                ("datasheet", datasheet is not None),
            ) if there]
            txn.commit(
                f"Add {staged.entry_name or staged.mpn or staged.display_name} "
                f"({staged.category}): {', '.join(placed + ['record'])}"
            )
        return record

    def add_passive_part(self, record: PartRecord, require_complete: bool = True) -> PartRecord:
        """Commit a file-less passive part. A passive references KiCad STOCK
        symbol/footprint/3D by lib_id (the generic package is already in KiCad), so no
        asset files are copied and no category symbol lib entry is created: this writes
        ONLY the JSON record, inside one atomic git Transaction (a single scoped commit,
        or zero trace on failure). The complete-to-add gate still applies, passive-aware
        (stock refs satisfy symbol/footprint, no owned model required, a datasheet URL
        counts). An archive profile is grandfathered, as with add_part."""
        if require_complete and not self.profile.is_archive:
            missing = record.missing_fields()
            if missing:
                raise IncompleteError(missing)
        # A freshly scraped passive keeps a clean spec-derived name + description instead of
        # the decoder's raw string or a symbol blurb (same rule as the migration).
        record.display_name, record.description = apply_clean_identity(
            record.specs, record.category,
            display_name=record.display_name, description=record.description,
            mpn=record.mpn, manufacturer=record.manufacturer,
        )
        part_id = new_part_id(self.lib.parts_dir, record.mpn or record.display_name)
        record.id = part_id
        fresh_dirs = [self.lib.parts_dir] if not self.lib.parts_dir.exists() else []
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        sym = record.symbol
        fp = record.footprint
        with Transaction(self.repo) as txn:
            txn.track_dir(*fresh_dirs)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(
                f"Add {record.display_name} (passive, {record.category}): stock "
                f"{sym.lib}:{sym.name} symbol + {fp.lib}:{fp.name} footprint reference, record"
            )
        return record

    def add_reference_part(self, record: PartRecord, require_complete: bool = True) -> PartRecord:
        """Commit a file-LESS record: writes ONLY the JSON, inside one atomic git
        Transaction (a single scoped commit, or zero trace on failure). Every KiCad asset
        (symbol / footprint / 3D model) is OPTIONAL now (owner 2026-07-16): a part lands on
        identity + sourcing and its assets are attached AFTERWARDS (attach_symbol /
        attach_footprint / attach_model). Any refs already on the record (e.g. a passive's
        stock Device:R lib_ids) are kept verbatim. The completion gate still applies
        (identity + datasheet + purchase), archive-grandfathered as elsewhere. This is the
        path a whole-BOM import uses to land every part immediately."""
        if require_complete and not self.profile.is_archive:
            missing = record.missing_fields()
            if missing:
                raise IncompleteError(missing)
        # A freshly imported/scraped part keeps a clean spec-derived name + description.
        record.display_name, record.description = apply_clean_identity(
            record.specs, record.category,
            display_name=record.display_name, description=record.description,
            mpn=record.mpn, manufacturer=record.manufacturer,
        )
        part_id = new_part_id(self.lib.parts_dir, record.mpn or record.display_name)
        record.id = part_id
        fresh_dirs = [self.lib.parts_dir] if not self.lib.parts_dir.exists() else []
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            txn.track_dir(*fresh_dirs)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(_reference_commit_message(record))
        return record

    def attach_symbol(self, part_id: str, lib: str, name: str, tool: str = "kicad") -> PartRecord:
        """Attach (or repoint) a symbol REFERENCE on an existing record, tagged with the EDA
        `tool` ("kicad" today, "altium" later). Reference-only: no symbol file is copied
        (the lib_id points at an existing library). One atomic commit."""
        return self._attach_libref(part_id, "symbol", lib, name, tool)

    def attach_footprint(self, part_id: str, lib: str, name: str, tool: str = "kicad") -> PartRecord:
        """Attach (or repoint) a footprint REFERENCE on an existing record, tagged with the
        EDA `tool`. Reference-only (lib_id, no file copied). One atomic commit."""
        return self._attach_libref(part_id, "footprint", lib, name, tool)

    def _attach_libref(self, part_id: str, field: str, lib: str, name: str, tool: str) -> PartRecord:
        if not name.strip():
            raise ValueError(f"a {field} reference needs a name")
        record = self.load_record(part_id)
        setattr(record, field, LibRef(lib=lib, name=name, tool=tool))
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Attach {tool} {field} {lib}:{name} to {part_id}")
        return record

    def regenerate_altium_dblib(self) -> dict:
        """Regenerate the SQLite data source (stockroom-parts.db) for every place-ready part
        and the .DbLib, BOTH committed in one atomic commit (owner decision 2026-07-23: a
        fresh clone is placeable with no regenerate step). Parts missing Altium assets or the
        required data fields are excluded and reported (never half-placed). The emitter is
        byte-deterministic, so an unchanged library produces no commit."""
        from stockroom.altium.datasource import emit_db
        from stockroom.altium.dblib import emit_dblib
        from stockroom.model.part import altium_place_ready

        altium_dir = self.lib.parts_dir.parent / "altium"
        altium_dir.mkdir(parents=True, exist_ok=True)
        db_path = altium_dir / "stockroom-parts.db"
        dblib_path = altium_dir / "Stockroom.DbLib"
        # Retire the Excel-era artifacts: the derived .xlsx (was untracked) and the local
        # .gitignore that hid it (was committed; `git add -A` in commit() stages its deletion).
        # A fresh library never had them, so the ignore file only joins the commit when git
        # actually tracks it (a pathspec for a never-known file aborts `commit --only`).
        gitignore_path = altium_dir / ".gitignore"
        retire_ignore = self.repo._is_tracked(gitignore_path)
        gitignore_path.unlink(missing_ok=True)
        (altium_dir / "stockroom-parts.xlsx").unlink(missing_ok=True)

        ready, skipped = [], []
        for json_path in sorted(self.lib.parts_dir.glob("*.json")):
            record = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            # value is intentionally NOT required (nothing persists it; the emitter derives the
            # Value column). altium_place_ready is the shared predicate the status view also uses.
            if altium_place_ready(record):
                ready.append(record)
            else:
                skipped.append(record.id)

        emit_db(ready, db_path)
        with Transaction(self.repo) as txn:
            emit_dblib("Parts", db_path.name, dblib_path)
            txn.track(dblib_path)
            txn.track(db_path)
            if retire_ignore:
                txn.track(gitignore_path)  # tracked-but-deleted: stages the removal
            txn.commit(f"Regenerate Altium DbLib: {len(ready)} place-ready parts")
        return {"emitted": len(ready), "skipped": skipped, "dblib": dblib_path, "db": db_path}

    def attach_altium_assets(self, part_id: str, *sources) -> PartRecord:
        """Store a part's Altium assets verbatim under <profile>/altium/ and set
        altium_symbol/altium_footprint. `*sources` is EITHER a loose .SchLib + .PcbLib pair OR
        a single compiled .IntLib (auto-extracted in pure Python, no Altium). Only the loose
        .SchLib/.PcbLib are stored; the .IntLib is not. One atomic commit; on any error every
        touched path is restored (zero trace). Fails loud if the source cannot be normalized or
        an entry name cannot be read (part left untouched)."""
        from stockroom.altium.extract import normalize_altium_source
        from stockroom.altium.oleread import pick_entry, read_footprint_names, read_symbol_names

        record = self.load_record(part_id)
        altium_dir = self.lib.parts_dir.parent / "altium"
        json_path = self.lib.parts_dir / f"{part_id}.json"

        with tempfile.TemporaryDirectory() as td:
            # normalize to a loose (schlib, pcblib) pair, EITHER side possibly None (split
            # vendor delivery attaches one side per capture forward; the other side keeps
            # whatever the record already carries)
            sch_src, pcb_src = normalize_altium_source(*sources, out_dir=td)
            # best-effort entry binding (exact MPN, then the name containing it, then the
            # first entry): a multi-entry vendor library must never refuse the capture
            sym_name = (
                pick_entry(read_symbol_names(sch_src), "symbol", prefer=record.mpn)
                if sch_src is not None else None
            )
            fp_name = (
                pick_entry(read_footprint_names(pcb_src), "footprint", prefer=record.mpn)
                if pcb_src is not None else None
            )

            # mkdir AFTER validation so a normalize/read failure leaves zero trace
            fresh = [] if altium_dir.exists() else [altium_dir]
            altium_dir.mkdir(parents=True, exist_ok=True)
            with Transaction(self.repo) as txn:
                txn.track_dir(*fresh)
                landed: list[str] = []
                # track EACH file right after its copy so a failure of the second copy still
                # rolls back the first (no leaked .SchLib on a partial failure)
                if sch_src is not None:
                    sch_dst = altium_dir / f"{part_id}.SchLib"
                    shutil.copyfile(sch_src, sch_dst)
                    txn.track(sch_dst)
                    record.altium_symbol = AltiumRef(lib=sch_dst.name, name=sym_name)
                    landed.append(sym_name or sch_dst.name)
                if pcb_src is not None:
                    pcb_dst = altium_dir / f"{part_id}.PcbLib"
                    shutil.copyfile(pcb_src, pcb_dst)
                    txn.track(pcb_dst)
                    record.altium_footprint = AltiumRef(lib=pcb_dst.name, name=fp_name)
                    landed.append(fp_name or pcb_dst.name)
                json_path.write_text(record.dumps(), encoding="utf-8")
                txn.track(json_path)
                txn.commit(f"Attach Altium assets to {part_id}: {' + '.join(landed)}")
        return record

    def detach_asset(self, part_id: str, kind: str) -> PartRecord:
        """Remove ONE element from a part (owner 2026-07-24): the file goes, the record
        ref nulls, one scoped commit; everything else on the part stands. `kind` is one of
        symbol / footprint / model / datasheet / altium_symbol / altium_footprint. A kind
        the part does not carry is a loud ValueError, never a silent no-op (so the UI can
        never pretend to remove something that was not there)."""
        record = self.load_record(part_id)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        altium_dir = self.lib.parts_dir.parent / "altium"

        def _missing(what: str):
            return ValueError(f"{part_id} has no {what} to remove")

        with Transaction(self.repo) as txn:
            if kind == "symbol":
                if record.symbol is None:
                    raise _missing("symbol")
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                if sym_lib_path.exists():
                    sym_lib = SymbolLib.load(sym_lib_path)
                    if record.symbol.name in sym_lib.symbol_names:
                        sym_lib.remove_symbol(record.symbol.name)
                        sym_lib.save(sym_lib_path)
                        txn.track(sym_lib_path)
                record.symbol = None
            elif kind == "footprint":
                if record.footprint is None:
                    raise _missing("footprint")
                fp_path = (
                    self.lib.footprint_lib_path(record.category)
                    / f"{record.footprint.name}.kicad_mod"
                )
                if fp_path.exists():
                    txn.track(fp_path)
                    fp_path.unlink()
                record.footprint = None
            elif kind == "model":
                if record.model is None:
                    raise _missing("3D model")
                model_path = self.lib.parts_dir.parent / record.model.file
                if model_path.exists():
                    txn.track(model_path)
                    model_path.unlink()
                # strip the dangling (model ...) link from the footprint, if one stands
                if record.footprint is not None:
                    fp_path = (
                        self.lib.footprint_lib_path(record.category)
                        / f"{record.footprint.name}.kicad_mod"
                    )
                    if fp_path.exists():
                        fp = Footprint.load(fp_path)
                        if fp.model_path:
                            fp.set_model_path("")
                            fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
                            txn.track(fp_path)
                record.model = None
            elif kind == "datasheet":
                if record.datasheet is None:
                    raise _missing("datasheet")
                if record.datasheet.file:
                    ds_path = self.lib.datasheets_dir / record.datasheet.file
                    if ds_path.exists():
                        txn.track(ds_path)
                        ds_path.unlink()
                record.datasheet = None
            elif kind == "altium_symbol":
                if record.altium_symbol is None:
                    raise _missing("Altium symbol")
                sch = altium_dir / f"{part_id}.SchLib"
                if sch.exists():
                    txn.track(sch)
                    sch.unlink()
                record.altium_symbol = None
            elif kind == "altium_footprint":
                if record.altium_footprint is None:
                    raise _missing("Altium footprint")
                pcb = altium_dir / f"{part_id}.PcbLib"
                if pcb.exists():
                    txn.track(pcb)
                    pcb.unlink()
                record.altium_footprint = None
            else:
                raise ValueError(f"unknown asset kind: {kind!r}")
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Remove {kind.replace('_', ' ')} from {part_id}")
        return record

    def load_record(self, part_id: str) -> PartRecord:
        path = self.lib.parts_dir / f"{part_id}.json"
        return PartRecord.loads(path.read_text(encoding="utf-8"))

    def edit_field(self, part_id: str, field: str, value) -> PartRecord:
        record = self.load_record(part_id)
        if not hasattr(record, field):
            raise ValueError(f"unknown field: {field}")
        # The datasheet is a structured ref, but the UI edits it as a bare URL (the Complete-Part
        # window): coerce a plain string into a Datasheet so the record stays well-formed. A blank
        # string clears it.
        if field == "datasheet" and isinstance(value, str):
            value = Datasheet(source_url=value.strip()) if value.strip() else None
        setattr(record, field, value)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        sym_lib_path = self.lib.symbol_lib_path(record.category)
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            prop = _MIRROR_ON_EDIT.get(field)
            if prop is not None or field == "tags":
                sym_lib = SymbolLib.load(sym_lib_path)
                sym = sym_lib.get_symbol(record.symbol.name)
                if field == "tags":
                    sym.set_property("ki_keywords", " ".join(record.tags))
                else:
                    sym.set_property(prop, str(value))
                sym_lib.save(sym_lib_path)
                txn.track(sym_lib_path)
            txn.commit(f"Edit {part_id}: {field}")
        return record

    def renormalize_descriptions(self, *, dry_run: bool = False) -> list[dict]:
        """Rebuild machine names + placeholder descriptions from each record's specs (a
        one-time backfill of a library seeded with concatenated names like "1.10k 1% 0603
        Panasonic ERJ-P03F1101V" and the KiCad symbol's blurb like "Resistor, small
        symbol"). A spec-derived name replaces the stored one only when the specs support
        a clean one; a spec-derived description replaces the stored one only when the
        stored one is a placeholder. A genuinely custom name/description is left untouched.
        All changes land in ONE atomic commit, or none. Returns a per-part change report of
        {id, display_name?: (old, new), description?: (old, new)}."""
        planned: list[tuple] = []
        for path in sorted(self.lib.parts_dir.glob("*.json")):
            record = PartRecord.loads(path.read_text(encoding="utf-8"))
            change: dict[str, tuple[str, str]] = {}
            name, desc = apply_clean_identity(
                record.specs,
                record.category,
                display_name=record.display_name,
                description=record.description,
                mpn=record.mpn,
                manufacturer=record.manufacturer,
            )
            if name != record.display_name:
                change["display_name"] = (record.display_name, name)
            if desc != record.description:
                change["description"] = (record.description, desc)
            if change:
                planned.append((path, record, change))
        report = [{"id": r.id, **c} for _p, r, c in planned]
        if planned and not dry_run:
            with Transaction(self.repo) as txn:
                for path, record, change in planned:
                    if "display_name" in change:
                        record.display_name = change["display_name"][1]
                    if "description" in change:
                        record.description = change["description"][1]
                    path.write_text(record.dumps(), encoding="utf-8")
                    txn.track(path)
                txn.commit(f"Rebuild {len(planned)} names + descriptions from part specs")
        return report

    def set_specs(self, part_id: str, specs: dict, *, overwrite: bool = False) -> PartRecord:
        """Persist canonical spec data (e.g. the pinout extracted at enrich time) into
        the record so a viewer reads the source of truth, not a transient enrich call.

        Each incoming entry is {key: {"value": ..., "source": ..., "confidence": ...}};
        the value lands in record.specs[key] and its provenance in record.enrichment[key]
        (finally putting that field to work). Merges key-by-key: an existing key is kept
        unless overwrite=True, mirroring EnrichmentResult.merge_missing so enrichment
        never silently clobbers. Specs are NOT a completion-gate field, so completeness is
        untouched. A change-free call is a true no-op (no empty commit)."""
        record = self.load_record(part_id)
        changed = False
        for raw_key, entry in specs.items():
            # Normalize the incoming key/value to the SAME canonical form the record
            # persists (part.to_dict), so the guard / no-op / merge below operate on one
            # key-space. Without this a raw duplicated-label key from the scraper would
            # slip past the dedup, add a twin, and get silently collapsed on write.
            key = normalize_spec_key(raw_key)
            if not key:
                continue
            if not overwrite and key in record.specs:
                continue
            value = entry.get("value") if isinstance(entry, dict) else entry
            value = normalize_spec_value(value)
            source = entry.get("source", "") if isinstance(entry, dict) else ""
            confidence = entry.get("confidence", "") if isinstance(entry, dict) else ""
            if record.specs.get(key) == value and record.enrichment.get(key) == EnrichmentField(
                source=source, confidence=confidence
            ):
                continue
            record.specs[key] = value
            record.enrichment[key] = EnrichmentField(source=source, confidence=confidence)
            changed = True
        # When enrichment lands rich specs (a value, a product line), a still-machine name
        # and a still-placeholder description are rebuilt from them, so a newly scraped part
        # reads as clean as a migrated one. A clean/custom name + a real description pass
        # through unchanged (idempotent), so a later pinout-only set_specs never renames.
        if changed:
            name, desc = apply_clean_identity(
                record.specs,
                record.category,
                display_name=record.display_name,
                description=record.description,
                mpn=record.mpn,
                manufacturer=record.manufacturer,
            )
            if name != record.display_name:
                record.display_name = name
            if desc != record.description:
                record.description = desc
        if not changed:
            return record
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Set specs on {part_id}: {', '.join(sorted(specs))}")
        return record

    def refresh_procurement(self, part_id: str, per_vendor, now_iso: str) -> PartRecord:
        """Refresh a part's volatile procurement data (price / stock / lifecycle / distributor
        P/N / fetched_at) from the per-vendor distributor-API results, atomically. A change-free
        refresh is a true no-op (no empty commit), mirroring set_specs."""
        from stockroom.enrich.refresh import apply_procurement_refresh

        record = self.load_record(part_id)
        if not apply_procurement_refresh(record, per_vendor, now_iso):
            return record
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Refresh {part_id}: procurement")
        return record

    def rebuild_part(self, part_id: str, per_vendor, now_iso: str) -> PartRecord:
        """Rebuild a part in ONE atomic commit: refresh its procurement data AND re-derive its
        spec-aware display name (what it IS), so a whole-library rebuild lands fresh data + a proper
        name per part in a single commit. A change-free rebuild is a true no-op (no empty commit)."""
        from stockroom.enrich.refresh import apply_procurement_refresh
        from stockroom.ingest.component_naming import propose_component_name_from_record

        record = self.load_record(part_id)
        changed = apply_procurement_refresh(record, per_vendor, now_iso)
        new_name = propose_component_name_from_record(record)
        if new_name and new_name != record.display_name:
            record.display_name = new_name
            changed = True
        if not changed:
            return record
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Rebuild {part_id}: data + name")
        return record

    def _remove_symbol_node(self, sym_lib_path: Path, name: str) -> str:
        """Remove the named symbol node from a lib and return the new file text."""
        sym_lib = SymbolLib.load(sym_lib_path)
        sym_lib.remove_symbol(name)
        return sym_lib.serialize()

    def move_category(self, part_id: str, new_category: str) -> PartRecord:
        record = self.load_record(part_id)
        old_cat = record.category
        if new_category == old_cat:
            return record
        json_path = self.lib.parts_dir / f"{part_id}.json"
        # A passive owns no symbol/footprint files and its stock lib_ids
        # (Device:R, Resistor_SMD:...) do not depend on the category, so moving it is
        # just a category field change on the record. A FILE-LESS part (the link-add
        # path: symbol and footprint both None, capture pending) moves the same way -
        # there is nothing category-placed to relocate, and reading record.symbol.name
        # here crashed the move (same defect as delete, 2026-07-24).
        if record.passive or (record.symbol is None and record.footprint is None):
            with Transaction(self.repo) as txn:
                record.category = new_category
                json_path.write_text(record.dumps(), encoding="utf-8")
                txn.track(json_path)
                txn.commit(f"Move {part_id}: {old_cat} -> {new_category}")
            return record
        if record.symbol is None or record.footprint is None:
            # a partially-detached part would need a per-asset relocation this move does
            # not model; refuse loud rather than half-move (re-attach or detach the rest)
            raise ValueError(
                f"{part_id} has only one of symbol/footprint; detach it or complete the "
                "part before moving categories"
            )
        name = record.symbol.name
        old_sym = self.lib.symbol_lib_path(old_cat)
        new_sym = self.lib.symbol_lib_path(new_category)
        old_fp = self.lib.footprint_lib_path(old_cat) / f"{name}.kicad_mod"
        new_pretty = self.lib.footprint_lib_path(new_category)
        new_fp = new_pretty / f"{name}.kicad_mod"
        new_nickname = category_nickname(new_category)
        json_path = self.lib.parts_dir / f"{part_id}.json"

        with Transaction(self.repo) as txn:
            # symbol: append to new lib (byte-preserving), then remove from old
            merge_symbol_into_lib(new_sym, old_sym, name, name)
            txn.track(new_sym)
            old_sym.write_text(self._remove_symbol_node(old_sym, name), encoding="utf-8", newline="")
            txn.track(old_sym)
            # footprint: move file between .pretty dirs
            new_pretty.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_fp), str(new_fp))
            txn.track(old_fp, new_fp)
            # symbol Footprint property + record fields
            sym_lib = SymbolLib.load(new_sym)
            sym_lib.get_symbol(name).set_property("Footprint", f"{new_nickname}:{name}")
            sym_lib.save(new_sym)
            record.category = new_category
            record.symbol = LibRef(lib=new_nickname, name=name)
            record.footprint = LibRef(lib=new_nickname, name=name)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Move {part_id}: {old_cat} -> {new_category}")
        return record

    def delete_part(self, part_id: str) -> None:
        record = self.load_record(part_id)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            # Each owned asset is removed off ITS OWN ref, independently: a passive
            # references KiCad stock lib_ids (nothing to remove), a file-less link-add
            # carries None refs (live 2026-07-24: reading record.symbol.name here crashed
            # every delete of the primary add flow's parts), and a detach_asset may have
            # nulled one side already - so no ref may ever be derived from another.
            if not record.passive and record.symbol is not None:
                name = record.symbol.name
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib_path.write_text(
                    self._remove_symbol_node(sym_lib_path, name), encoding="utf-8", newline=""
                )
                txn.track(sym_lib_path)
            if not record.passive and record.footprint is not None:
                fp_path = (
                    self.lib.footprint_lib_path(record.category)
                    / f"{record.footprint.name}.kicad_mod"
                )
                if fp_path.exists():
                    fp_path.unlink()
                    txn.track(fp_path)
            if json_path.exists():
                json_path.unlink()
                txn.track(json_path)
            if record.model and record.model.file:
                mp = self.lib.root / record.model.file
                if mp.exists():
                    mp.unlink()
                    txn.track(mp)
            if record.datasheet and record.datasheet.file:
                dp = self.lib.datasheets_dir / record.datasheet.file
                if dp.exists():
                    dp.unlink()
                    txn.track(dp)
            # the part's per-part Altium libs go with it - never orphaned in the tree
            altium_dir = self.lib.parts_dir.parent / "altium"
            for suffix in (".SchLib", ".PcbLib", ".IntLib"):
                ap = altium_dir / f"{part_id}{suffix}"
                if ap.exists():
                    ap.unlink()
                    txn.track(ap)
            txn.commit(f"Delete {part_id}")

    def detect_drift(self) -> DriftReport:
        """Compare each part's JSON (the source of truth) against its symbol's
        mirrored properties; report mismatches. Detection only: healing is the
        M6 doctor UI (shows a diff before healing, spec section 3)."""
        report = DriftReport()
        parts_dir = self.lib.parts_dir
        if not parts_dir.exists():
            return report
        for json_path in sorted(parts_dir.glob("*.json")):
            record = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            if record.symbol is None:
                continue
            # A passive owns no symbol in the category lib (it references KiCad stock,
            # which Stockroom never mutates), so it can never drift and must not be
            # reported as a missing symbol.
            if record.passive:
                continue
            sym_lib_path = self.lib.symbol_lib_path(record.category)
            try:
                sym = SymbolLib.load(sym_lib_path).get_symbol(record.symbol.name)
            except Exception:
                report.missing_symbol.append(record.id)
                continue
            for prop, expected in kicad_visible_properties(record).items():
                actual = sym.get_property(prop)
                if actual is not None and actual != expected:
                    report.items.append(
                        DriftItem(part_id=record.id, property=prop, json_value=expected, symbol_value=actual)
                    )
        return report

    def _footprint_file(self, record: PartRecord) -> Path | None:
        """The on-disk .kicad_mod for a part's footprint (or None if the record has no
        footprint reference). Footprints live under the category .pretty keyed on the
        footprint entry name, mirroring how add_part places them."""
        if record.footprint is None or not record.footprint.name:
            return None
        return self.lib.footprint_lib_path(record.category) / f"{record.footprint.name}.kicad_mod"

    def _load_records(self) -> dict[str, PartRecord]:
        parts_dir = self.lib.parts_dir
        if not parts_dir.exists():
            return {}
        out: dict[str, PartRecord] = {}
        for json_path in sorted(parts_dir.glob("*.json")):
            rec = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            out[rec.id] = rec
        return out

    def _unparseable_reason(self, path: Path) -> str | None:
        """Why a working-tree file cannot be committed by the repair (it would abort the
        transaction's validation), or None if it is safe to sweep. A deletion (the path no
        longer exists) is always safe; a KiCad or JSON file that no longer parses is not."""
        if not path.exists():
            return None
        if path.suffix in _SEXP_SUFFIXES or path.name in _SEXP_TABLE_NAMES:
            try:
                SexpDocument.load(path)
            except Exception:
                return "the KiCad file does not parse"
        elif path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return "the JSON file does not parse"
        return None

    def _model_path_action(self, record: PartRecord) -> tuple[RepairAction | None, RepairFinding | None]:
        """Inspect a part's footprint 3D-model link. Returns a fixable action when the
        link is non-portable but the model resolves under models/ (rewrite to the
        canonical ${SR_LIB}/models/<file>), a manual finding when the link points at a
        file that is not present, or (None, None) when the link is already canonical or
        absent. Portability is the whole point of the SR_LIB substitution, so a link that
        resolves only on this machine is exactly what a hand-off would break."""
        fp_file = self._footprint_file(record)
        if fp_file is None or not fp_file.exists():
            return None, None
        model_path = Footprint.load(fp_file).model_path
        if not model_path:
            return None, None
        basename = re.split(r"[\\/]", model_path)[-1]
        canonical = f"${{SR_LIB}}/models/{basename}"
        model_present = bool(basename) and (self.lib.models_dir / basename).exists()
        if not model_present:
            # The record's own model reference (record.model.file) is checked separately
            # and reports the SAME missing file as a dangling_model. When both point at
            # that file, let the record-level finding own it rather than double-reporting.
            record_basename = (
                re.split(r"[\\/]", record.model.file)[-1]
                if record.model and record.model.file
                else None
            )
            if record_basename == basename:
                return None, None
            return None, RepairFinding(
                kind="dangling_model_link",
                part_id=record.id,
                detail=f"footprint 3D-model link points at a missing file: {model_path}",
                how_to_fix="re-import the 3D model, or repoint the footprint's model path",
            )
        if model_path != canonical:
            return (
                RepairAction(
                    kind="model_path",
                    part_id=record.id,
                    detail=f"footprint 3D-model link is not portable: {model_path}",
                    before=model_path,
                    after=canonical,
                ),
                None,
            )
        return None, None

    def _iter_visible_metadata(self, records, libs: dict | None = None):
        """(record, property) pairs whose mirrored metadata property renders as
        VISIBLE schematic text (pre-fix parts): they splat URLs over a schematic
        and drown the symbol preview. `libs` lets apply_repairs reuse its
        in-memory SymbolLib instances so earlier heals are not lost."""
        cache: dict = dict(libs) if libs else {}
        for record in records.values():
            if record.symbol is None:
                continue
            sym_lib_path = self.lib.symbol_lib_path(record.category)
            if not sym_lib_path.exists():
                continue
            sym_lib = cache.get(sym_lib_path)
            if sym_lib is None:
                try:
                    sym_lib = SymbolLib.load(sym_lib_path)
                except Exception:  # noqa: BLE001 - unparseable files are manual findings
                    continue
                cache[sym_lib_path] = sym_lib
            try:
                sym = sym_lib.get_symbol(record.symbol.name)
            except Exception:  # noqa: BLE001 - a missing symbol is its own finding
                continue
            for prop in kicad_visible_properties(record):
                if sym.property_hidden(prop) is False:
                    yield record, prop

    def scan_repairs(self) -> RepairPlan:
        """A read-only health pass (spec section 3: show the diff BEFORE healing).
        Reports every self-healable defect (drift + non-portable model links) as a
        RepairAction, every unfixable defect (missing symbol, dangling asset files) as
        a RepairFinding, and every uncommitted working-tree change. Never writes."""
        plan = RepairPlan()
        records = self._load_records()

        drift = self.detect_drift()
        for it in drift.items:
            plan.fixable.append(
                RepairAction(
                    kind="drift",
                    part_id=it.part_id,
                    detail=f'{it.property}: symbol shows "{it.symbol_value}", record has "{it.json_value}"',
                    before=it.symbol_value,
                    after=it.json_value,
                )
            )
        for part_id in drift.missing_symbol:
            plan.manual.append(
                RepairFinding(
                    kind="missing_symbol",
                    part_id=part_id,
                    detail="the part's symbol is missing from its category library",
                    how_to_fix="re-add or re-ingest the part to recreate its symbol",
                )
            )

        for record, prop in self._iter_visible_metadata(records):
            plan.fixable.append(
                RepairAction(
                    kind="visible_metadata",
                    part_id=record.id,
                    detail=f'"{prop}" is visible text on the schematic symbol',
                    before="visible",
                    after="hidden",
                )
            )

        for record in records.values():
            if record.model and record.model.file and not (self.lib.root / record.model.file).exists():
                plan.manual.append(
                    RepairFinding(
                        kind="dangling_model",
                        part_id=record.id,
                        detail=f"3D model file is missing: {record.model.file}",
                        how_to_fix="re-import the 3D model for this part",
                    )
                )
            if (
                record.datasheet
                and record.datasheet.file
                and not (self.lib.datasheets_dir / record.datasheet.file).exists()
            ):
                plan.manual.append(
                    RepairFinding(
                        kind="dangling_datasheet",
                        part_id=record.id,
                        detail=f"datasheet file is missing: {record.datasheet.file}",
                        how_to_fix="re-fetch the datasheet for this part",
                    )
                )
            action, finding = self._model_path_action(record)
            if action is not None:
                plan.fixable.append(action)
            if finding is not None:
                plan.manual.append(finding)

        # Uncommitted working-tree changes, scoped to the ACTIVE profile so a shared repo
        # never leaks (or sweeps) another profile's in-progress edits. A file that no
        # longer parses can't be committed (it would abort the whole transaction), so it
        # is surfaced as a manual finding instead of blocking the repair.
        for path in self.repo.dirty_paths(self.lib.root):
            reason = self._unparseable_reason(path)
            if reason:
                plan.manual.append(
                    RepairFinding(
                        kind="unparseable_file",
                        part_id="",
                        detail=f"{path.name}: {reason}",
                        how_to_fix="fix or remove the malformed file, then repair again",
                    )
                )
            else:
                plan.uncommitted.append(str(path))
        return plan

    def apply_repairs(self) -> RepairResult:
        """Heal every fixable defect and sweep every uncommitted change into ONE scoped
        commit, atomically (spec sections 5, 9). Drift heals toward the JSON source of
        truth; non-portable model links rewrite to ${SR_LIB}. Manual findings are
        returned untouched — a missing file is never "fixed" by deleting the reference to
        it. A healthy library is a true no-op: no empty commit."""
        plan = self.scan_repairs()
        result = RepairResult(manual=plan.manual)
        if not plan.fixable and not plan.uncommitted:
            return result

        records = self._load_records()
        with Transaction(self.repo) as txn:
            # 1. heal drift toward JSON (re-run detection so we carry the property + value)
            touched_libs: dict[Path, SymbolLib] = {}
            for it in self.detect_drift().items:
                record = records.get(it.part_id)
                if record is None or record.symbol is None:
                    continue
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib = touched_libs.get(sym_lib_path)
                if sym_lib is None:
                    sym_lib = SymbolLib.load(sym_lib_path)
                    touched_libs[sym_lib_path] = sym_lib
                sym_lib.get_symbol(record.symbol.name).set_property(it.property, it.json_value)
                result.healed_drift += 1
            # 1b. hide mirrored metadata properties still rendering as schematic text
            for record, prop in self._iter_visible_metadata(records, touched_libs):
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib = touched_libs.get(sym_lib_path)
                if sym_lib is None:
                    sym_lib = SymbolLib.load(sym_lib_path)
                    touched_libs[sym_lib_path] = sym_lib
                sym = sym_lib.get_symbol(record.symbol.name)
                sym.set_property(prop, sym.get_property(prop) or "", hide=True)
                result.hidden_metadata += 1

            for sym_lib_path, sym_lib in touched_libs.items():
                sym_lib.save(sym_lib_path)
                txn.track(sym_lib_path)

            # 2. rewrite non-portable 3D-model links to the canonical ${SR_LIB} form
            for action in [a for a in plan.fixable if a.kind == "model_path"]:
                record = records.get(action.part_id)
                fp_file = self._footprint_file(record) if record else None
                if fp_file is None or not fp_file.exists():
                    continue
                fp = Footprint.load(fp_file)
                fp.set_model_path(action.after)
                fp_file.write_text(fp.serialize(), encoding="utf-8", newline="")
                txn.track(fp_file)
                result.fixed_paths += 1

            # 3. sweep every committable uncommitted change (scoped to the active
            # profile; unparseable files already filtered into manual findings) into the
            # same commit. dirty_paths already yields absolute paths and both sides of a
            # rename, so the deletion of a renamed file's old name is staged too.
            for path in plan.uncommitted:
                txn.track(Path(path))
                result.committed_files += 1

            result.commit = txn.commit("Repair library")
        return result
