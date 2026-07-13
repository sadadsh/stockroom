"""High-level, atomic library operations: add / edit / move-category / delete a
part, and drift detection. Each mutation runs inside one git-backed Transaction
so it either commits as a single scoped commit or leaves zero trace (spec
sections 3, 5, 9).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.sexp.document import SexpDocument

from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.category import category_nickname
from stockroom.model.part import (
    Datasheet,
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
        "datasheet": staged.datasheet_source is not None,
        "purchase": any(bool(p.url) for p in staged.purchase),
    }
    return missing_from_presence(present)


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
            # 0. ensure the category libraries exist (idempotent); a freshly created
            # empty symbol lib is tracked so it commits atomically.
            ensure_footprint_lib(pretty_dir)
            if not sym_lib_path.exists():
                if self.cli is None:
                    raise ValueError(
                        f"category symbol library {sym_lib_path.name} is missing and "
                        "no kicad-cli was provided to create it"
                    )
                create_empty_symbol_lib(self.cli, sym_lib_path)
                txn.track(sym_lib_path)

            # 1. merge the symbol (renamed to entry_name) into the category lib
            merge_symbol_into_lib(
                sym_lib_path, staged.symbol_source, staged.symbol_source_name, staged.entry_name
            )
            txn.track(sym_lib_path)

            # 2. place the footprint into the category .pretty
            fp_path = place_footprint(pretty_dir, staged.footprint_source, staged.entry_name)
            txn.track(fp_path)

            # 3. model file + (model ...) link
            model_ref = None
            if staged.model_source is not None:
                model_name = f"{staged.entry_name}{Path(staged.model_source).suffix}"
                model_dst = self.lib.models_dir / model_name
                shutil.copyfile(staged.model_source, model_dst)
                txn.track(model_dst)
                fp = Footprint.load(fp_path)
                fp.set_model_path(f"${{SR_LIB}}/models/{model_name}")
                fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
                model_ref = ModelRef(file=f"models/{model_name}")

            # 4. datasheet file
            datasheet = None
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
                symbol=LibRef(lib=nickname, name=staged.entry_name),
                footprint=LibRef(lib=nickname, name=staged.entry_name),
                model=model_ref,
                provenance=staged.provenance,
                purchase=list(staged.purchase),
            )
            sym_lib = SymbolLib.load(sym_lib_path)
            sym = sym_lib.get_symbol(staged.entry_name)
            sym.set_property("Footprint", f"{nickname}:{staged.entry_name}")
            mirror_fields_to_symbol(sym, record)
            sym_lib.save(sym_lib_path)

            # 6. the JSON record
            json_path = self.lib.parts_dir / f"{part_id}.json"
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)

            txn.commit(f"Add {staged.entry_name} ({staged.category}): symbol, footprint, "
                       f"{'3D model, ' if model_ref else ''}"
                       f"{'datasheet, ' if datasheet else ''}record")
        return record

    def load_record(self, part_id: str) -> PartRecord:
        path = self.lib.parts_dir / f"{part_id}.json"
        return PartRecord.loads(path.read_text(encoding="utf-8"))

    def edit_field(self, part_id: str, field: str, value) -> PartRecord:
        record = self.load_record(part_id)
        if not hasattr(record, field):
            raise ValueError(f"unknown field: {field}")
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
        name = record.symbol.name
        sym_lib_path = self.lib.symbol_lib_path(record.category)
        fp_path = self.lib.footprint_lib_path(record.category) / f"{name}.kicad_mod"
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            sym_lib_path.write_text(self._remove_symbol_node(sym_lib_path, name), encoding="utf-8", newline="")
            txn.track(sym_lib_path)
            for p in (fp_path, json_path):
                if p.exists():
                    p.unlink()
                    txn.track(p)
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
