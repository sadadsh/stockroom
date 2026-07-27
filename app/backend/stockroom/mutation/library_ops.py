"""High-level, atomic library operations: add / edit / move-category / delete a
part, and drift detection. Each mutation runs inside one git-backed Transaction
so it either commits as a single scoped commit or leaves zero trace (spec
sections 3, 5, 9).
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.eda.registry import all_tools, get_tool
from stockroom.ingest.describe import apply_clean_identity
from stockroom.kicad.category_lib import create_empty_symbol_lib, ensure_footprint_lib
from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.model.category import category_nickname
from stockroom.model.part import (
    AssetRef,
    Datasheet,
    EdaAssets,
    EnrichmentField,
    PartRecord,
    Provenance,
    Purchase,
    SourcedValue,
    asset_label,
    missing_from_presence,
    new_part_id,
)
from stockroom.model.spec_hygiene import normalize_spec_key, normalize_spec_value
from stockroom.mutation.hygiene import apply_hygiene, hygiene_preview
from stockroom.mutation.placement import (
    kicad_visible_properties,
    merge_symbol_into_lib,
    mirror_fields_to_symbol,
    place_footprint,
)
from stockroom.mutation.transaction import Transaction
from stockroom.sexp.document import SexpDocument
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


def _kicad(record: PartRecord):
    """The record's LIVE KiCad asset bundle.

    LibraryOps owns the KiCad side of the library (it merges `.kicad_sym` entries, places
    `.kicad_mod` files and links `${SR_LIB}` models), so its asset reads are EXPLICITLY
    KiCad rather than implicitly so. Naming the tool at every read is the point of the
    per-EDA record: the old flat `record.symbol` read as tool-neutral while behaving as
    KiCad-only, which is how Altium assets ended up filed over KiCad references.
    """
    return record.assets_for("kicad")


def _altium_log_suffix(log: str) -> str:
    """Altium's own log appended to an error, when there is one.

    A failure message without the tool's own words is what made the 3D embed take ten Altium boots
    to diagnose: "it did not work" is not a diagnosis.
    """
    text = (log or "").strip()
    return f" Altium said: {text}" if text else ""


def _altium(record: PartRecord):
    """The record's LIVE Altium asset bundle (see `_kicad`)."""
    return record.assets_for("altium")


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
    # Where each spec came from, and every value a source offered and lost with. Carried
    # through so add_part can persist both onto the record (see PartRecord.alternates); the
    # candidate computes them, this is only the hop between.
    enrichment: dict = field(default_factory=dict)
    alternates: dict = field(default_factory=dict)


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
        # A datasheet is satisfied by a downloaded PDF OR a known link (the same
        # rule PartRecord.is_complete uses), so a pulled datasheet URL is enough to
        # add a part; the two completeness checks can never disagree.
        "datasheet": staged.datasheet_source is not None
        or (staged.datasheet_meta is not None and bool(staged.datasheet_meta.source_url)),
        "purchase": any(bool(p.url) for p in staged.purchase),
    }
    return missing_from_presence(present)


def derivation_status(index) -> dict:
    """Which derivation ruleset the library's parts currently carry, and how many are behind.

    Answered from the INDEX with one grouped query, never by opening every record file - that is
    the whole reason the `derived_by` stamp is an indexed column. Takes the index rather than
    living on `LibraryOps` because it reads only derived state and writes nothing.

    `stale` counts everything whose stamp is not the running ruleset, INCLUDING the empty stamp
    (never derived) and any stamp from a NEWER build a peer device wrote. Both need a look; only
    one of them needs the same fix, and the per-stamp `counts` is what tells them apart.
    """
    from stockroom.model.derived import DERIVED_BY

    counts = index.derivation_counts() if index is not None else {}
    return {
        "ruleset": DERIVED_BY,
        "counts": counts,
        "current": counts.get(DERIVED_BY, 0),
        "stale": sum(n for stamp, n in counts.items() if stamp != DERIVED_BY),
    }


def _reference_commit_message(record: PartRecord) -> str:
    """A plain, one-line commit subject for a file-less add that adapts to whatever refs
    the record already carries (a passive lands with stock lib_ids; an asset-less part
    lands with none, to be attached later)."""
    refs = []
    k = _kicad(record)
    if k.symbol is not None and k.symbol.name:
        refs.append(f"{k.symbol.lib}:{k.symbol.name} symbol")
    if k.footprint is not None and k.footprint.name:
        refs.append(f"{k.footprint.lib}:{k.footprint.name} footprint")
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


    # -- workspace hygiene (Batch 2) ------------------------------------------
    #
    # The library holds assets for EVERY registered EDA tool at once, so it takes the union of their
    # rules rather than one tool's set. A per-project sync can never cover it, and a peer cloning the
    # library is exactly who inherits a committed `fp-info-cache`.

    def _hygiene_tools(self) -> list[str]:
        from stockroom.eda.registry import all_tools

        return [tool.key for tool in all_tools()]

    def hygiene_read(self) -> dict:
        """What syncing the library's workspace hygiene would change: {writes, untracked}.
        Read-only."""
        return hygiene_preview(self.repo.root, self._hygiene_tools(), repo=self.repo)

    def hygiene_apply(self) -> dict:
        """Write the library's ignore/attributes rules and untrack the per-user files they now
        cover, as ONE commit. An unchanged library is an honest no-commit no-op."""
        return apply_hygiene(self.repo.root, self._hygiene_tools(), repo=self.repo)

    def lfs_status(self) -> dict:
        """Where this library's binary payloads are stored, and what adopting git-lfs would cover.

        No network: locking is a remote round trip and is probed separately, only when someone is
        actually deciding whether to turn `lockable` on.
        """
        from stockroom.vcs import lfs as lfs_backend

        st = lfs_backend.status(self.repo)
        covers: list[str] = []
        for tool in all_tools():
            covers.extend(p for p in tool.lfs if p not in covers)
        return {
            **st.to_dict(),
            # what adoption WOULD route through LFS, so the offer is concrete rather than a promise
            "covers": covers,
            # adoption is a property of the repo's own .gitattributes, never a setting stored
            # elsewhere that could disagree with it
            "adopted": bool(st.tracked_patterns),
        }

    def lfs_adopt(self) -> dict:
        """Route this library's binary payloads through git-lfs, as ONE hygiene commit.

        Deliberately does NOT convert existing history: that needs `git lfs migrate`, which rewrites
        commits and therefore needs a force-push, which this project forbids. Files already
        committed stay ordinary blobs and are counted as `legacy_blobs`, so the limit is visible.
        """
        result = apply_hygiene(self.repo.root, self._hygiene_tools(), repo=self.repo, lfs=True)
        return {**result, **self.lfs_status()}

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
        part_id = new_part_id(self.lib.parts_dir, staged.mpn, staged.display_name)
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
                model_ref = AssetRef(file=f"models/{model_name}")

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

            # A part added with no human name arrives here with display_name == "" or the
            # bare MPN (the UI seeds "" and candidateFromResult falls back to the MPN), which
            # shipped ICs named "TPS62130RGTR". The namer that produces
            # "<Product Type> <MPN> <package>" already existed but was only reachable via the
            # rescan's rebuild_part, so a name was only fixed if the part happened to be
            # rescanned later. Derive at ADD time. Only ever fills a blank-or-MPN name; a name
            # the user actually typed is never overwritten.
            from stockroom.ingest.component_naming import propose_component_name

            display_name = staged.display_name
            if not display_name.strip() or display_name.strip() == staged.mpn.strip():
                display_name = (
                    propose_component_name(
                        staged.category, staged.specs, staged.mpn, staged.description
                    )
                    or staged.display_name
                )

            # 5. the symbol's Footprint property, then mirror KiCad-visible fields
            record = PartRecord(
                id=part_id,
                display_name=display_name,
                category=staged.category,
                description=staged.description,
                tags=list(staged.tags),
                mpn=staged.mpn,
                manufacturer=staged.manufacturer,
                datasheet=datasheet,
                assets={
                    "kicad": EdaAssets(
                        symbol=AssetRef(lib=nickname, name=staged.entry_name)
                        if staged.symbol_source is not None else None,
                        footprint=AssetRef(lib=nickname, name=staged.entry_name)
                        if staged.footprint_source is not None else None,
                        model=model_ref,
                    )
                },
                provenance=staged.provenance,
                purchase=list(staged.purchase),
                specs=dict(staged.specs),
                enrichment={
                    k: EnrichmentField(source=v.get("source", ""),
                                       confidence=v.get("confidence", ""))
                    for k, v in staged.enrichment.items() if isinstance(v, dict)
                },
                alternates={
                    k: [SourcedValue.from_dict(a) for a in entries if isinstance(a, dict)]
                    for k, entries in staged.alternates.items()
                },
            )
            if staged.symbol_source is not None:
                sym_lib = SymbolLib.load(sym_lib_path)
                sym = sym_lib.get_symbol(staged.entry_name)
                # Guard on the FOOTPRINT, not the symbol. A symbol-only add is legitimate
                # (the footprint is attached later), and stamping the property off symbol
                # presence shipped a symbol claiming a footprint the .pretty does not hold
                # while the record's footprint stayed None -- a broken link on placement, and
                # a schematic that reads as "has a footprint" when the library disagrees.
                # Mirrors the attach path's guard in ingest/pipeline.py.
                fp_ref = _kicad(record).footprint
                if fp_ref is not None:
                    sym.set_property("Footprint", f"{fp_ref.lib}:{fp_ref.name}")
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
        part_id = new_part_id(self.lib.parts_dir, record.mpn, record.display_name)
        record.id = part_id
        fresh_dirs = [self.lib.parts_dir] if not self.lib.parts_dir.exists() else []
        self.lib.parts_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.lib.parts_dir / f"{part_id}.json"
        sym = _kicad(record).symbol
        fp = _kicad(record).footprint
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
        part_id = new_part_id(self.lib.parts_dir, record.mpn, record.display_name)
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
        # Storage is symmetric now (every tool has its own symbol/footprint/model slot), so
        # this no longer risks clobbering the KiCad reference. It is still KiCad-only for a
        # REAL reason: a KiCad lib_id resolves against a library KiCad already knows, while
        # an Altium [Library Ref] only resolves if the .SchLib/.PcbLib actually sits in the
        # profile -- which only the attach path that COPIES those files can guarantee.
        # Filing a bare Altium reference here would produce a DbLib row pointing at nothing.
        # `tool` is unvalidated caller input from the API body, so refuse loudly.
        if tool != "kicad":
            raise ValueError(
                f"cannot attach a {field} reference for tool {tool!r}: this path files a "
                f"reference only, and a non-KiCad reference is unresolvable without its "
                f"library files. Altium assets attach through "
                f"POST /api/altium/parts/{{id}}/attach, which copies the real files."
            )
        record = self.load_record(part_id)
        record.assets_for(tool).set(field, AssetRef(lib=lib, name=name))
        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Attach {tool} {field} {lib}:{name} to {part_id}")
        return record

    def _altium_dir(self) -> Path:
        return self.lib.parts_dir.parent / "altium"

    def _altium_place_ready(self) -> tuple[list, list[str]]:
        """The place-ready records the data source emits, and the ids of everything excluded.

        Reads parts_dir directly (never the derived index) because this is the SAME source the
        status view globs, and a count that disagrees with the emitter is how a surface starts
        lying about how many parts are placeable.
        """
        from stockroom.model.part import tool_place_ready

        ready, skipped = [], []
        for json_path in sorted(self.lib.parts_dir.glob("*.json")):
            record = PartRecord.loads(json_path.read_text(encoding="utf-8"))
            # value is intentionally NOT required (nothing persists it; the emitter derives the
            # Value column). tool_place_ready is the shared predicate the status view also uses.
            if tool_place_ready(record, "altium"):
                ready.append(record)
            else:
                skipped.append(record.id)
        return ready, skipped

    def ensure_altium_datasource(self, allow_tracked: bool = False) -> dict:
        """Make BOTH derived Altium artifacts on disk match the library, committing NOTHING.

        This is what replaced committing the `.db` (Batch 2 item 3). The commit had been bought to
        keep a fresh clone placeable with no regenerate step; rebuilding on demand buys the same
        thing without sharing a derived binary that two peers can never merge.

        Called at context build and on a profile/library switch, so by the time anyone opens Altium
        the file is there and current. Returns {path, rows, written, reason} where reason is
        "missing", "stale", "current" or "shared".

        The staleness test is a byte comparison against a freshly emitted copy. That is sound
        because `emit_db` is byte-deterministic ON ONE MACHINE (measured); it is deliberately NOT
        relied on ACROSS machines, where SQLite stamps its own library version into the header.

        `allow_tracked=False` (the default, used by the automatic callers) refuses to touch a copy
        git still TRACKS, reporting "shared". Two peers on different SQLite builds hold
        byte-different but content-IDENTICAL files, so a boot-time rewrite there would achieve
        nothing except dirtying a tree that has not been migrated yet, which is the exact churn
        this item exists to remove. An explicit regenerate passes True.
        """
        from stockroom.altium.datasource import emit_db

        altium_dir = self._altium_dir()
        altium_dir.mkdir(parents=True, exist_ok=True)
        db_path = altium_dir / "stockroom-parts.db"
        ready, _skipped = self._altium_place_ready()
        if not allow_tracked and db_path.exists() and self.repo._is_tracked(db_path):
            # A still-tracked data source means this library has not been migrated, so the
            # automatic ensure touches NOTHING here - not even the .DbLib, whose absence would
            # otherwise be "fixed" by dropping a fresh untracked file into a tree with no ignore
            # rule for it yet. An explicit regenerate migrates both and writes both.
            return {"path": db_path, "rows": len(ready), "written": False, "reason": "shared",
                    "dblib": {"path": db_path.parent / "Stockroom.DbLib", "written": False,
                              "reason": "shared"}}

        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "stockroom-parts.db"
            rows = emit_db(ready, candidate)
            if not db_path.exists():
                reason, written = "missing", True
            elif db_path.read_bytes() != candidate.read_bytes():
                reason, written = "stale", True
            else:
                reason, written = "current", False
            if written:
                shutil.copyfile(candidate, db_path)
        return {"path": db_path, "rows": rows, "written": written, "reason": reason,
                "dblib": self._ensure_altium_dblib(db_path, allow_tracked)}

    def _ensure_altium_dblib(self, db_path: Path, allow_tracked: bool) -> dict:
        """Write the .DbLib beside its data source. Derived since 2026-07-26, for the reason in
        `altium/dblib.py`: its connection string must name the database ABSOLUTELY or real Altium
        cannot open it, and a machine-specific path cannot be shared through git.

        Written at BOOT rather than only on an explicit regenerate, because Altium is opened by a
        person and not by Stockroom: a fresh clone whose .DbLib only appears after someone happens
        to press Regenerate is a library that silently does not work on a new machine.

        `allow_tracked=False` refuses to touch a copy git still tracks, exactly as for the `.db` -
        a pre-migration library gets dirtied by nothing until an explicit regenerate migrates it.
        """
        from stockroom.altium.dblib import absolute_data_source, emit_dblib, render_dblib

        path = db_path.parent / "Stockroom.DbLib"
        if not allow_tracked and path.exists() and self.repo._is_tracked(path):
            return {"path": path, "written": False, "reason": "shared"}
        # The SAME path computation the write uses. This line used to call `.resolve()`
        # independently, so the "is it current?" comparison and the file it compares against
        # were two copies of one rule: any divergence rewrites the file on every check or never
        # rewrites it at all, and neither failure is visible.
        wanted = render_dblib("Parts", db_path.name, db_path=absolute_data_source(db_path))
        if path.exists() and path.read_text(encoding="utf-8") == wanted:
            return {"path": path, "written": False, "reason": "current"}
        reason = "stale" if path.exists() else "missing"
        emit_dblib("Parts", db_path.name, path, db_path=db_path)
        return {"path": path, "written": True, "reason": reason}

    def regenerate_altium_dblib(self) -> dict:
        """Regenerate BOTH derived Altium artifacts for every place-ready part.

        NEITHER is committed. The `.db` stopped being shared on 2026-07-25 (two peers adding
        different parts produce unmergeable binaries carrying nothing the records do not already
        hold); the `.DbLib` followed on 2026-07-26, because real Altium cannot open a data source
        named by a relative path and the absolute one it needs is machine-specific. See
        `eda.registry` `_ALTIUM.derived` and `altium/dblib.py` for both measurements.

        A library from before those dates still has a derived copy COMMITTED, and an ignore rule
        has no effect on a file git already tracks, so this MIGRATES it first by running the
        library's own workspace hygiene: that writes the ignore rule and untracks the file in one
        commit, leaving a clean tree. Hygiene is reused rather than reimplemented here because a
        second, weaker "stop sharing this file" is exactly the duplication that drifts. If hygiene
        refuses (it will not run over staged changes), the regenerate still completes and the
        refusal is REPORTED as `migration_blocked` rather than swallowed.

        Parts missing Altium assets or the required data fields are excluded and reported (never
        half-placed). With nothing left to share, an ordinary regenerate makes no commit at all.
        """
        altium_dir = self._altium_dir()
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

        migration_blocked = ""
        # BOTH derived artifacts migrate the same way. Checking only the `.db` left a library that
        # had committed the `.DbLib` (every library made before 2026-07-26) sharing it forever.
        if any(p.exists() and self.repo._is_tracked(p) for p in (db_path, dblib_path)):
            try:
                self.hygiene_apply()
            except ValueError as exc:
                migration_blocked = str(exc)

        ready, skipped = self._altium_place_ready()
        self.ensure_altium_datasource(allow_tracked=True)
        with Transaction(self.repo) as txn:
            if retire_ignore:
                txn.track(gitignore_path)  # tracked-but-deleted: stages the removal
            txn.commit(f"Regenerate Altium DbLib: {len(ready)} place-ready parts")
        return {
            "emitted": len(ready), "skipped": skipped, "dblib": dblib_path, "db": db_path,
            "migration_blocked": migration_blocked,
        }

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
                    # pick_entry returns None when the library names no entry; an AssetRef holds
                    # strings, and a None name would read as "attached but unnamed".
                    _altium(record).symbol = AssetRef(lib=sch_dst.name, name=sym_name or "")
                    landed.append(sym_name or sch_dst.name)
                if pcb_src is not None:
                    pcb_dst = altium_dir / f"{part_id}.PcbLib"
                    shutil.copyfile(pcb_src, pcb_dst)
                    txn.track(pcb_dst)
                    _altium(record).footprint = AssetRef(lib=pcb_dst.name, name=fp_name or "")
                    landed.append(fp_name or pcb_dst.name)
                json_path.write_text(record.dumps(), encoding="utf-8")
                txn.track(json_path)
                txn.commit(f"Attach Altium assets to {part_id}: {' + '.join(landed)}")
        return record

    def _model_source(self, record: PartRecord):
        """The file-shaped 3D model this part already holds, from whichever tool carries one.

        A STEP file is tool-agnostic: one file serves every tool. That is exactly why an embed
        CONSUMES the model the part already has instead of asking a capture session for a second,
        tool-specific copy, and it is why the registry lists Altium's model as embeddable but not
        capturable. Registry order decides the preference, so this stays generic.
        """
        for tool in all_tools():
            ref = record.assets_for(tool.key).model
            if ref is not None and ref.file:
                return ref
        return None

    def embed_altium_model(self, part_id: str, *, replace: bool = False, driver=None) -> dict:
        """Embed the part's 3D model into its Altium footprint's `.PcbLib`, atomically.

        Altium stores a 3D body INSIDE the `.PcbLib` binary, so this is the one mutation Stockroom
        cannot perform itself: it drives the installed Altium (see `stockroom.altium.embed3d`) and
        then verifies the container from outside Altium before believing it.

        The `.PcbLib` is a tracked binary, so the whole thing is ONE transaction: the modified
        library and the updated record land in a single scoped commit, and any failure restores the
        original bytes and leaves zero trace. That matters more here than usual, because a
        half-written OLE container is not something a peer could repair by hand.
        """
        from stockroom.altium.embed3d import embed_model

        record = self.load_record(part_id)
        altium = _altium(record)
        footprint = altium.footprint
        if footprint is None or not footprint.lib:
            raise ValueError(
                f"{part_id} has no Altium footprint, and a 3D body lives inside the footprint's "
                ".PcbLib. Attach the Altium library first."
            )
        pcblib = self.lib.parts_dir.parent / "altium" / footprint.lib
        if not pcblib.exists():
            raise ValueError(f"the Altium library {footprint.lib} is missing from this profile")

        source = self._model_source(record)
        if source is None:
            raise ValueError(
                f"{part_id} has no 3D model file to embed. Attach a 3D model first; the same file "
                "serves every tool."
            )
        step = self.lib.root / source.file
        if not step.exists():
            raise ValueError(f"the 3D model file is missing: {source.file}")

        json_path = self.lib.parts_dir / f"{part_id}.json"
        with Transaction(self.repo) as txn:
            # Tracked BEFORE Altium touches it, unlike an attach which tracks after its copy: this
            # modifies a file that already exists, so the pre-edit bytes are what rollback restores.
            txn.track(pcblib)
            result = embed_model(
                pcblib,
                step,
                footprints=(footprint.name,) if footprint.name else (),
                replace=replace,
                driver=driver,
            )
            if not result.ok:
                # Raised, not returned, so the transaction rolls the .PcbLib back. Altium's own
                # words are carried through, because "it did not work" without the reason is what
                # made this feature take ten boots to diagnose.
                raise ValueError(f"{result.detail}{_altium_log_suffix(result.altium_log)}")
            # The Altium model asset is a FILE-shaped ref that also names its container, because
            # unlike KiCad's the payload lives inside the footprint library rather than beside it.
            altium.model = AssetRef(lib=footprint.lib, name=footprint.name, file=source.file)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            sha = txn.commit(f"Embed 3D model into {part_id} Altium footprint")
        return {
            "part_id": part_id,
            "status": result.status,
            "detail": result.detail,
            "embedded": result.embedded,
            "payload_bytes": result.payload_bytes,
            "orphaned": result.orphaned,
            "pcblib": footprint.lib,
            "model": source.file,
            "commit": sha,
        }

    def _altium_embed_candidate(self, record: PartRecord) -> bool:
        """True when this part COULD gain an embedded 3D body and does not have one yet.

        Three ways to not be a candidate, none of them an error: no Altium footprint (a 3D body
        lives inside the footprint's `.PcbLib`, so there is nowhere to put it), no 3D model file
        on the record at all, or an Altium model slot that is already filled. A real library is a
        mixture of all four states, and calling the first three "failures" would bury the one
        thing the owner actually needs to read.

        Decided from the RECORD, never by opening the OLE container. Parsing every `.PcbLib` to
        answer "how many are pending" would make a status call cost the whole library in disk
        reads. Both ways of being wrong are already safe: a record that claims a model the
        container lost is simply not offered (and the per-part action still works), while a record
        missing the ref for a container that HAS the payload costs one embed attempt, which detects
        the payload from outside Altium and no-ops in 0.055s without taking a license seat.
        """
        altium = _altium(record)
        footprint = altium.footprint
        if footprint is None or not footprint.lib:
            return False
        if altium.model is not None:
            return False
        if self._model_source(record) is None:
            return False
        return (self.lib.parts_dir.parent / "altium" / footprint.lib).exists()

    def altium_models_pending(self) -> list[str]:
        """The part ids a bulk embed would actually work on, so a button never promises work it
        cannot do or hides work it will. Sorted, so the number and the order are stable."""
        pending = []
        for path in sorted(self.lib.parts_dir.glob("*.json")):
            try:
                record = self.load_record(path.stem)
            except Exception:  # noqa: BLE001 - one unreadable record never hides the rest
                continue
            if self._altium_embed_candidate(record):
                pending.append(record.id)
        return pending

    def embed_altium_models(self, part_ids: list[str] | None = None, *, replace: bool = False,
                            driver=None, on_progress=None) -> dict:
        """Embed the 3D model of EVERY part that needs one, in a single action.

        The owner's deadline ask was "no work on my end", and a whole library at one click per part
        is work. Each part is still its own atomic transaction, so a failure in the middle leaves
        the parts already done committed and the failing one untouched - the alternative, one giant
        transaction, would throw away an hour of successful embeds because part 41 had a bad
        container.

        This LOOPS the single-part embed rather than generating one DelphiScript that does every
        job in a single Altium boot. The script is the hard-won part (nine ruled-out hypotheses,
        and the breakthrough that a body must be added to the BOARD, not the footprint), each
        iteration on it costs an Altium boot and a license seat, and an already-embedded model is
        detected from OUTSIDE Altium and skipped in 0.055s with no boot at all. So a re-run is
        nearly free and only genuinely new work costs time. One-boot-many-jobs is a real
        optimisation, but it is an optimisation, not a prerequisite.

        `on_progress(done, total, part_id)` fires after each part, because this can run for
        minutes and a silent bar is indistinguishable from a hang.
        """
        if part_ids is None:
            targets, skipped = self.altium_models_pending(), []
        else:
            targets, skipped = [], []
            for pid in part_ids:
                record = self.load_record(pid)
                (targets if self._altium_embed_candidate(record) else skipped).append(pid)
        if part_ids is None:
            # Report the non-candidates too, so "3 of 40" is explained rather than mysterious.
            skipped = [p.stem for p in sorted(self.lib.parts_dir.glob("*.json"))
                       if p.stem not in set(targets)]

        results: list[dict] = []
        embedded = failed = 0
        for i, pid in enumerate(targets, start=1):
            try:
                result = self.embed_altium_model(pid, replace=replace, driver=driver)
                embedded += 1
            except Exception as exc:  # noqa: BLE001 - one bad part never abandons the rest
                failed += 1
                # Altium's own words survive to the report: "it did not work" without the reason
                # is what made this feature take ten boots to diagnose in the first place.
                result = {"part_id": pid, "status": "failed", "detail": str(exc)}
            results.append(result)
            if on_progress is not None:
                on_progress(i, len(targets), pid)
        return {
            "embedded": embedded, "failed": failed, "attempted": len(targets),
            "skipped": skipped, "results": results,
        }

    def detach_asset(self, part_id: str, kind: str) -> PartRecord:
        """Remove ONE element from a part (owner 2026-07-24): the file goes, the record
        ref nulls, one scoped commit; everything else on the part stands.

        `kind` is "datasheet" or a `<tool>_<asset kind>` pair drawn from the EDA registry
        ("kicad_symbol", "altium_footprint", ...) -- the same vocabulary
        `stockroom.capture.requirements` speaks, so a third tool becomes detachable by
        registering it. A kind the part does not carry is a loud ValueError, never a silent
        no-op, so the UI can never pretend to remove something that was not there.
        """
        record = self.load_record(part_id)
        json_path = self.lib.parts_dir / f"{part_id}.json"

        with Transaction(self.repo) as txn:
            if kind == "datasheet":
                if record.datasheet is None:
                    raise ValueError(f"{part_id} has no datasheet to remove")
                if record.datasheet.file:
                    ds_path = self.lib.datasheets_dir / record.datasheet.file
                    if ds_path.exists():
                        txn.track(ds_path)
                        ds_path.unlink()
                record.datasheet = None
            else:
                self._detach_eda_asset(record, kind, txn)
            json_path.write_text(record.dumps(), encoding="utf-8")
            txn.track(json_path)
            txn.commit(f"Remove {kind.replace('_', ' ')} from {part_id}")
        return record

    def _is_stockroom_authored(self, record: PartRecord, tool: str, asset_kind: str, ref) -> bool:
        """Does this reference point at a file THIS LIBRARY holds?

        The distinction that makes a library-wide clear safe. Two kinds of reference live in the
        same slot and only one of them is a file:

          STOCKROOM-AUTHORED  an entry in `SR-<Category>.kicad_sym`, a `.kicad_mod` under
                              `SR-<Category>.pretty`, a `.step` under `models/`, or an Altium
                              `.SchLib`/`.PcbLib` in the profile's `altium/`. Captured files.
          KICAD-STOCK         `Device:R`, `Resistor_SMD:R_0402_1005Metric` - KiCad's OWN installed
                              libraries. No file here to delete, and clearing the reference would
                              blank the part for good, because `capture_needs` returns `[]` for a
                              passive so nothing would ever refill it.

        Decided by WHERE THE FILE WOULD BE, never by the part's class: measured on the owner's
        library, 10 passives carry `SR-` symbols and footprints from the now-distrusted LCSC lane,
        and those are captured files like any other.
        """
        if ref is None or not ref.is_present():
            return False
        if ref.file:
            return True  # a file-shaped ref is always a path inside this profile
        if tool != "kicad":
            return True  # an Altium ref names a .SchLib/.PcbLib this profile stores verbatim
        # A KiCad lib_id resolves against a NICKNAME. Ours is `SR-<Category>`; anything else is a
        # library KiCad installed, which this app neither wrote nor may delete.
        return ref.lib == category_nickname(record.category)

    def clear_cad_assets(self, *, dry_run: bool = False) -> dict:
        """Remove every CAD asset this library HOLDS - the files and their references - in ONE
        atomic commit.

        Owner, 2026-07-27: *"remove all the current cad files before guided capture"*. The point is
        to start the trusted-capture pass from nothing, because the existing files came from
        sources the owner has since ruled out (*"a lot of our symbols, footprints, and 3d models
        are broken so its not trusted where we've gotten them"*).

        SCOPE, and it is the whole safety story: only STOCKROOM-AUTHORED references are cleared
        (see `_is_stockroom_authored`). A KiCad-stock reference is counted and LEFT, because it
        names no file this app owns and removing it would empty a part permanently.

        Touches CAD only. Identity, the derived block, `sourced/` evidence and the datasheet all
        stand - this removes assets, not parts.
        """
        report: dict = {"cleared": 0, "kept_stock": 0, "items": [], "failed": []}
        paths = sorted(self.lib.parts_dir.glob("*.json"))
        # One transaction around the whole sweep, opened before the walk so nothing accumulates
        # and a failure anywhere restores every touched path. `dry_run` opens none at all: a run
        # that writes nothing must be UNABLE to commit, not merely choose not to.
        with (Transaction(self.repo) if not dry_run else contextlib.nullcontext()) as txn:
            for path in paths:
                try:
                    record = PartRecord.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001 - one bad record cannot abandon the sweep
                    report["failed"].append({"id": path.stem, "error": str(exc)})
                    continue
                removed: list[str] = []
                for tool in all_tools():
                    assets = record.assets_for(tool.key)
                    for asset_kind in tool.asset_kinds:
                        ref = assets.get(asset_kind)
                        if ref is None or not ref.is_present():
                            continue
                        if not self._is_stockroom_authored(record, tool.key, asset_kind, ref):
                            report["kept_stock"] += 1
                            continue
                        removed.append(f"{tool.key}_{asset_kind}")
                if not removed:
                    continue
                report["cleared"] += len(removed)
                report["items"].append({"part_id": record.id, "assets": removed})
                if txn is None:
                    continue
                try:
                    for kind in removed:
                        self._detach_eda_asset(record, kind, txn)
                    path.write_text(record.dumps(), encoding="utf-8")
                    txn.track(path)
                except Exception as exc:  # noqa: BLE001 - reported, and the transaction still holds
                    report["failed"].append({"id": record.id, "error": str(exc)})
            if txn is not None and report["items"]:
                report_n = report["cleared"]
                txn.commit(f"Remove {report_n} CAD assets from {len(report['items'])} parts")
        return report

    def _detach_eda_asset(self, record: PartRecord, kind: str, txn) -> None:
        """Remove one tool's asset: its on-disk file(s) and its record reference.

        The on-disk half is genuinely per-tool -- a KiCad symbol is one entry INSIDE a
        shared category `.kicad_sym`, while an Altium symbol is a whole `.SchLib` file of
        its own -- so file removal dispatches on the tool. Everything around it (parsing the
        kind, validating it against the registry, nulling the ref, the commit) is generic.
        """
        tool, _, asset_kind = kind.partition("_")
        try:
            spec = get_tool(tool) if tool else None
        except KeyError:
            spec = None
        if spec is None or asset_kind not in spec.asset_kinds:
            raise ValueError(f"unknown asset kind: {kind!r}")

        assets = record.assets_for(tool)
        ref = assets.get(asset_kind)
        if ref is None:
            raise ValueError(
                f"{record.id} has no {spec.label} {asset_label(asset_kind)} to remove"
            )

        remove = getattr(self, f"_remove_{tool}_asset", None)
        if remove is None:
            raise ValueError(
                f"{spec.label} assets cannot be removed through Stockroom yet "
                f"(no file-removal adapter is registered for {tool!r})"
            )
        remove(record, asset_kind, ref, txn)
        assets.set(asset_kind, None)

    def _remove_kicad_asset(self, record: PartRecord, asset_kind: str, ref, txn) -> None:
        """KiCad file removal: a symbol is an entry inside the category `.kicad_sym`, a
        footprint is one `.kicad_mod`, a model is a file under `models/` whose `(model ...)`
        link must also be stripped from the footprint so nothing dangles."""
        if asset_kind == "symbol":
            sym_lib_path = self.lib.symbol_lib_path(record.category)
            if sym_lib_path.exists():
                sym_lib = SymbolLib.load(sym_lib_path)
                if ref.name in sym_lib.symbol_names:
                    sym_lib.remove_symbol(ref.name)
                    sym_lib.save(sym_lib_path)
                    txn.track(sym_lib_path)
        elif asset_kind == "footprint":
            fp_path = self.lib.footprint_lib_path(record.category) / f"{ref.name}.kicad_mod"
            if fp_path.exists():
                txn.track(fp_path)
                fp_path.unlink()
        elif asset_kind == "model":
            model_path = self.lib.parts_dir.parent / ref.file
            if model_path.exists():
                txn.track(model_path)
                model_path.unlink()
            # strip the now-dangling (model ...) link from the footprint, if one stands
            fp_ref = _kicad(record).footprint
            if fp_ref is not None:
                fp_path = (
                    self.lib.footprint_lib_path(record.category) / f"{fp_ref.name}.kicad_mod"
                )
                if fp_path.exists():
                    fp = Footprint.load(fp_path)
                    if fp.model_path:
                        fp.set_model_path("")
                        fp_path.write_text(fp.serialize(), encoding="utf-8", newline="")
                        txn.track(fp_path)

    def _remove_altium_asset(self, record: PartRecord, asset_kind: str, ref, txn) -> None:
        """Altium file removal: each asset is its own OLE2 compound file in the profile's
        `altium/` directory, named for the part."""
        altium_dir = self.lib.parts_dir.parent / "altium"
        suffix = {"symbol": "SchLib", "footprint": "PcbLib"}.get(asset_kind)
        if suffix is None:
            # A 3D body lives INSIDE the .PcbLib, so there is no standalone file to unlink;
            # clearing the reference is the whole removal.
            return
        path = altium_dir / f"{record.id}.{suffix}"
        if path.exists():
            txn.track(path)
            path.unlink()

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
                sym = sym_lib.get_symbol(_kicad(record).symbol.name)
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

    def rederive_library(
        self, *, now_iso: str, scheme: str = "", dry_run: bool = False, progress=None
    ) -> dict:
        """Recompute every record's DERIVED block from its stored evidence, in one atomic commit.

        This is the sweep the `derived_by` stamp exists for: a derivation-rules change (a new
        naming scheme, a cleaned-up description, a different spec normalization) makes every
        record's derived block stale, and the owner must be able to close that from inside the
        app rather than by someone running a script at their machine.

        THREE PROPERTIES, each load-bearing:

        * **Credential-free.** It reads `sourced/` and nothing else - no network, no API key.
          A fresh clone that has never been given credentials can still rebuild the library it
          just pulled, which is what device parity requires.
        * **Non-destructive.** A record with NO stored evidence is SKIPPED and counted, never
          rewritten. `derive.engine.rederive` on its own recomputes an empty block from no
          payloads - correct for one part mid-import, and a silent wipe of every hand-added
          part's description if applied blindly across a library.
        * **Atomic.** "The library is on ruleset N" is one fact, so it is one commit and one
          rollback. A part that cannot be read is reported by id and does not abandon the rest.

        Streams: one record is held in memory at a time, so a 10,000-part library costs the same
        as a 10-part one. `derived_at` is only re-stamped when the block actually changed, so a
        second pass over an already-current library is a true no-op rather than a full rewrite.
        """
        from stockroom.derive.engine import rederive
        from stockroom.derive.naming import DEFAULT_SCHEME
        from stockroom.model.derived import DERIVED_BY
        from stockroom.model.sourced import list_sources

        library_root = self.lib.parts_dir.parent
        report = {
            "ruleset": DERIVED_BY,
            "checked": 0,
            "rewritten": 0,
            "unchanged": 0,
            "no_evidence": 0,
            "failed": [],
        }
        paths = sorted(self.lib.parts_dir.glob("*.json"))
        # The transaction is opened BEFORE the walk, so a rewritten record is written and tracked
        # immediately and nothing accumulates. Holding the new text of every changed record until
        # the end would be ~300 MB at the 10,000-part scale this is built for, which is exactly
        # the shape the streaming worklist elsewhere in this repo exists to avoid.
        # `dry_run` opens no transaction at all: a run that writes nothing must not be able to
        # commit, rather than merely choosing not to.
        with (Transaction(self.repo) if not dry_run else contextlib.nullcontext()) as txn:
            for i, path in enumerate(paths):
                report["checked"] += 1
                if progress is not None:
                    progress(i + 1, len(paths), path.stem)
                try:
                    record = PartRecord.loads(path.read_text(encoding="utf-8"))
                    # Evidence is checked on DISK, not from the record's `sources` index: an
                    # index entry pointing at a payload that is not there would blank the part.
                    if not list_sources(library_root, record.id):
                        report["no_evidence"] += 1
                        continue
                    before = record.derived.to_dict()
                    # Derive with the record's EXISTING timestamp so an unchanged block compares
                    # equal. Stamping `now` up front would make every part differ every run,
                    # churning the library and making the `unchanged` count meaningless.
                    rederive(
                        record,
                        library_root,
                        derived_at=record.derived_at or now_iso,
                        scheme=scheme or DEFAULT_SCHEME,
                    )
                    if record.derived.to_dict() == before:
                        report["unchanged"] += 1
                        continue
                    record.derived_at = now_iso
                    report["rewritten"] += 1
                    if txn is not None:
                        path.write_text(record.dumps(), encoding="utf-8")
                        txn.track(path)
                except Exception as exc:  # noqa: BLE001 - one bad record cannot abandon the sweep
                    report["failed"].append({"id": path.stem, "error": str(exc)})
            if txn is not None and report["rewritten"]:
                txn.commit(f"Re-derive {report['rewritten']} parts onto {DERIVED_BY}")
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
        from stockroom.enrich.pipeline import refile_category
        from stockroom.enrich.refresh import apply_procurement_refresh
        from stockroom.ingest.component_naming import propose_component_name_from_record
        from stockroom.text import fullest_name

        record = self.load_record(part_id)
        # RE-FILE an unclassified record FIRST, and through `move_category`, which is the only
        # thing that knows a category is not just a field: the part's symbol lives in that
        # category's `.kicad_sym` and its footprint in that category's `.pretty`, and the record's
        # lib nicknames name them. Setting `record.category` here directly - which this did in its
        # first version - left the symbol in the OLD library while the record claimed the new one.
        # Caught by checking the owner's REAL part before running anything against it: theirs is
        # filed "Other" AND owns both files, so it was precisely the case that would have broken.
        #
        # `9bcb033` taught the ADD path to classify from the distributors' Product Category; a
        # record added before that kept "Other" forever, because nothing re-derived it and Move
        # Category by hand was the only route back.
        #
        # Its own atomic commit, deliberately: relocating two files is a different operation from
        # refreshing a record's data, and pretending otherwise is what would make the rollback of
        # one silently undo the other. It also runs BEFORE the rename, because the display name is
        # spec-aware and a correctly filed part can name itself better.
        new_category = refile_category(record)
        if new_category:
            # A partially-detached part raises here rather than half-moving. Left to propagate on
            # purpose: the message names what to do, and the bulk rescan reports per part.
            record = self.move_category(part_id, new_category)
        changed = apply_procurement_refresh(record, per_vendor, now_iso)
        # Prefer the SPELLED-OUT maker among the answers sources actually gave. Whichever source
        # answers first decides the form, so a part can sit under "TI" while another
        # distributor's "Texas Instruments" waits in `alternates` - and the Altium DbLib's
        # Manufacturer column reads this field verbatim, so the abbreviation reaches a placed
        # component too. Never invents a name: `fullest_name` only reorders answers on record.
        # Every answer ON THE RECORD, in priority order: the stored field, the answers it
        # displaced, then the distributors' own Manufacturer / Brand specs. That last pair is
        # where the spelled-out name actually lives - measured on the owner's real part, the field
        # held LCSC's shorthand `TI` while `specs["Manufacturer"]` and `specs["Brand"]` both read
        # "Texas Instruments" with provenance recorded against them. Consulting only `alternates`
        # missed it entirely, which is why this needs no network and no lookup table.
        maker = fullest_name(
            [record.manufacturer]
            + [a.value for a in (record.alternates.get("manufacturer") or [])]
            + [record.specs.get("Manufacturer"), record.specs.get("Brand")]
        )
        if maker and maker != record.manufacturer:
            record.manufacturer = maker
            changed = True
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
        # there is nothing category-placed to relocate, and reading _kicad(record).symbol.name
        # here crashed the move (same defect as delete, 2026-07-24).
        if record.passive or (_kicad(record).symbol is None and _kicad(record).footprint is None):
            with Transaction(self.repo) as txn:
                record.category = new_category
                json_path.write_text(record.dumps(), encoding="utf-8")
                txn.track(json_path)
                txn.commit(f"Move {part_id}: {old_cat} -> {new_category}")
            return record
        if _kicad(record).symbol is None or _kicad(record).footprint is None:
            # a partially-detached part would need a per-asset relocation this move does
            # not model; refuse loud rather than half-move (re-attach or detach the rest)
            raise ValueError(
                f"{part_id} has only one of symbol/footprint; detach it or complete the "
                "part before moving categories"
            )
        name = _kicad(record).symbol.name
        old_sym = self.lib.symbol_lib_path(old_cat)
        new_sym = self.lib.symbol_lib_path(new_category)
        old_fp = self.lib.footprint_lib_path(old_cat) / f"{name}.kicad_mod"
        new_pretty = self.lib.footprint_lib_path(new_category)
        new_fp = new_pretty / f"{name}.kicad_mod"
        new_nickname = category_nickname(new_category)
        json_path = self.lib.parts_dir / f"{part_id}.json"

        with Transaction(self.repo) as txn:
            # The destination category may have no symbol library yet - moving a part into a
            # category nothing has been added to is the ordinary case, not an exotic one. Without
            # this, `merge_symbol_into_lib` opened a file that does not exist and the move died on
            # a bare FileNotFoundError naming a path, with nothing saying what to do about it.
            # Created exactly as `add_part` creates one, including the same honest refusal when
            # there is no kicad-cli to author it.
            if not new_sym.exists():
                if self.cli is None:
                    raise ValueError(
                        f"category symbol library {new_sym.name} is missing and no kicad-cli "
                        "was provided to create it"
                    )
                new_sym.parent.mkdir(parents=True, exist_ok=True)
                create_empty_symbol_lib(self.cli, new_sym)
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
            _kicad(record).symbol = AssetRef(lib=new_nickname, name=name)
            _kicad(record).footprint = AssetRef(lib=new_nickname, name=name)
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
            # carries None refs (live 2026-07-24: reading _kicad(record).symbol.name here crashed
            # every delete of the primary add flow's parts), and a detach_asset may have
            # nulled one side already - so no ref may ever be derived from another.
            if not record.passive and _kicad(record).symbol is not None:
                name = _kicad(record).symbol.name
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib_path.write_text(
                    self._remove_symbol_node(sym_lib_path, name), encoding="utf-8", newline=""
                )
                txn.track(sym_lib_path)
            if not record.passive and _kicad(record).footprint is not None:
                fp_path = (
                    self.lib.footprint_lib_path(record.category)
                    / f"{_kicad(record).footprint.name}.kicad_mod"
                )
                if fp_path.exists():
                    fp_path.unlink()
                    txn.track(fp_path)
            if json_path.exists():
                json_path.unlink()
                txn.track(json_path)
            if _kicad(record).model and _kicad(record).model.file:
                mp = self.lib.root / _kicad(record).model.file
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
            if _kicad(record).symbol is None:
                continue
            # A passive owns no symbol in the category lib (it references KiCad stock,
            # which Stockroom never mutates), so it can never drift and must not be
            # reported as a missing symbol.
            if record.passive:
                continue
            sym_lib_path = self.lib.symbol_lib_path(record.category)
            try:
                sym = SymbolLib.load(sym_lib_path).get_symbol(_kicad(record).symbol.name)
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
        if _kicad(record).footprint is None or not _kicad(record).footprint.name:
            return None
        return self.lib.footprint_lib_path(record.category) / f"{_kicad(record).footprint.name}.kicad_mod"

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
            # The record's own model reference (_kicad(record).model.file) is checked separately
            # and reports the SAME missing file as a dangling_model. When both point at
            # that file, let the record-level finding own it rather than double-reporting.
            record_basename = (
                re.split(r"[\\/]", _kicad(record).model.file)[-1]
                if _kicad(record).model and _kicad(record).model.file
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
            if _kicad(record).symbol is None:
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
                sym = sym_lib.get_symbol(_kicad(record).symbol.name)
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
            if _kicad(record).model and _kicad(record).model.file and not (self.lib.root / _kicad(record).model.file).exists():
                plan.manual.append(
                    RepairFinding(
                        kind="dangling_model",
                        part_id=record.id,
                        detail=f"3D model file is missing: {_kicad(record).model.file}",
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
                if record is None or _kicad(record).symbol is None:
                    continue
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib = touched_libs.get(sym_lib_path)
                if sym_lib is None:
                    sym_lib = SymbolLib.load(sym_lib_path)
                    touched_libs[sym_lib_path] = sym_lib
                sym_lib.get_symbol(_kicad(record).symbol.name).set_property(it.property, it.json_value)
                result.healed_drift += 1
            # 1b. hide mirrored metadata properties still rendering as schematic text
            for record, prop in self._iter_visible_metadata(records, touched_libs):
                sym_lib_path = self.lib.symbol_lib_path(record.category)
                sym_lib = touched_libs.get(sym_lib_path)
                if sym_lib is None:
                    sym_lib = SymbolLib.load(sym_lib_path)
                    touched_libs[sym_lib_path] = sym_lib
                sym = sym_lib.get_symbol(_kicad(record).symbol.name)
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
