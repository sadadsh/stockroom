"""High-level, atomic library operations: add / edit / move-category / delete a
part, and drift detection. Each mutation runs inside one git-backed Transaction
so it either commits as a single scoped commit or leaves zero trace (spec
sections 3, 5, 9).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.category import category_nickname, slugify
from stockroom.model.category import category_footprint_lib, category_symbol_lib
from stockroom.model.part import (
    Datasheet,
    LibRef,
    ModelRef,
    PartRecord,
    Provenance,
    new_part_id,
)
from stockroom.mutation.placement import (
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


class LibraryOps:
    def __init__(self, profile: Profile, repo: GitRepo):
        self.profile = profile
        self.repo = repo
        self.lib = profile.library

    def add_part(self, staged: StagedPart) -> PartRecord:
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        self.lib.models_dir.mkdir(parents=True, exist_ok=True)
        self.lib.datasheets_dir.mkdir(parents=True, exist_ok=True)

        part_id = new_part_id(self.lib.parts_dir, staged.mpn or staged.display_name)
        nickname = category_nickname(staged.category)
        sym_lib_path = self.lib.symbol_lib_path(staged.category)
        pretty_dir = self.lib.footprint_lib_path(staged.category)

        with Transaction(self.repo) as txn:
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
        target = None
        for node in sym_lib._doc.root.find_all("symbol"):
            if node.children[1].value == name:
                target = node
                break
        if target is None:
            raise ValueError(f"symbol {name!r} not in {sym_lib_path.name}")
        sym_lib._doc.root.remove_child(target)
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
