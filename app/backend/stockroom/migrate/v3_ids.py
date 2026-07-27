"""Plan and apply the v2 -> v3 library migration: schema write-back + the decided part-id scheme.

THE BLOCKER THIS EXISTS FOR (measured 2026-07-27 against the owner's real library). All 158 records
are `schema_version: 2` ON DISK, carrying `eda` and `passive`. They are migrated to v3 in memory on
every load - `PartRecord.from_dict` calls `migrate_record` - and then never written back. Two
consequences, and the second one blocks real work:

  1. The `derived` block and `part_class` exist only in RAM, so nothing on disk records which
     ruleset produced a name, and a re-derive has nothing to compare against.
  2. **84 of 158 ids contain underscores** (`103at_2`, `10_era_2aeb1182x`), and `model/sourced.py`
     correctly refuses those as path components. So NO raw distributor payload can be filed for
     those parts, which means the importer cannot run and the whole sourced/derived split - the
     owner's requirement 1 - cannot reach the real library at all.

The remaining 74 ids are path-safe but still lack the `-<hash>` suffix the spec decided on, so
every record is renamed, not just the unsafe ones.

WHAT IS RENAMED, and how the list was established (by reading the library, not by assuming):

    parts/<id>.json        -> parts/<new>.json, rewritten in v3 with the new `id`
    datasheets/<id>.pdf    -> datasheets/<new>.pdf, and `record.datasheet.file` updated.
                              MEASURED: 85 of 158 records reference a datasheet, and ALL 85 are
                              named exactly `<id>.pdf`; zero use any other convention.
    sourced/<id>/          -> nothing to move; no payload has ever been written (that is the
                              blocker above, not an oversight).

WHAT IS DELIBERATELY NOT TOUCHED, each checked rather than assumed:

    models/                named by MPN (`103AT-2.step`), not by id. Measured: zero model refs
                           embed a part id.
    symbols/, footprints/  per-CATEGORY libraries (`SR-Resistors.kicad_sym`), never per part.
    the SQLite index       derived and rebuildable by definition; rebuilt after, never migrated.
    altium/*.DbLib         regenerated from the library, and gitignored.

WHAT WOULD BREAK ELSEWHERE, and is reported rather than silently ignored:

    project bindings       a placement bound to a library part stores `_sr_bound_part_id` in the
                           PROJECT's own repo (projects/binding.py), which this migration cannot
                           reach. Measured: zero projects registered on either of the owner's
                           libraries, so there is nothing to break today - but a library that HAS
                           bindings must not be migrated silently, so they are counted and refused
                           unless `--allow-orphan-bindings` is passed.
    rescan state           per-machine, uncommitted, keyed by part id. Goes stale on rename; it is
                           a cache of "when did we last check this part", so a stale entry only
                           costs one redundant check. Reported, not migrated.

SAFETY. The library is a git repository, so a clean tree plus a recorded HEAD IS the verified
backup the plan asks for - there is no separate copy to take, and inventing one would be a second
thing to keep in sync. The migration therefore REFUSES to run against a dirty library tree: with
uncommitted changes present, `git checkout` is no longer a complete undo, and that is exactly when
a bulk rename must not proceed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.model.part import SCHEMA_VERSION, PartRecord
from stockroom.model.part_id import is_valid_part_id, make_part_id
from stockroom.model.sourced import SOURCED_DIRNAME
from stockroom.text import counted


@dataclass
class PartPlan:
    """One record's planned move. `old_id == new_id` is possible and means "rewrite in place"."""

    old_id: str
    new_id: str
    mpn: str
    record_from: Path
    record_to: Path
    # (from, to) for the part's datasheet, when it has one named after the old id.
    datasheet_from: Path | None = None
    datasheet_to: Path | None = None
    old_schema: int = 0
    # A sourced/ directory that would have to move. Expected empty; carried so a library that DOES
    # have payloads is handled rather than quietly half-migrated.
    sourced_from: Path | None = None
    sourced_to: Path | None = None

    @property
    def renames_id(self) -> bool:
        return self.old_id != self.new_id

    @property
    def moves_datasheet(self) -> bool:
        """Whether the datasheet actually CHANGES path.

        Not merely "has a datasheet named after the id": after a migration the two are equal, and
        counting those as moves made the summary report "85 datasheets move" on an already-migrated
        library where nothing would move at all. `apply_migration` skipped them correctly - it was
        the REPORT that overstated, which is the half a person actually reads.
        """
        return (
            self.datasheet_from is not None
            and self.datasheet_to is not None
            and self.datasheet_from != self.datasheet_to
        )


@dataclass
class MigrationPlan:
    parts: list[PartPlan] = field(default_factory=list)
    # Blocking problems. A non-empty list means the migration must not be applied.
    errors: list[str] = field(default_factory=list)
    # Non-blocking things a person should know about.
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        renamed = sum(1 for p in self.parts if p.renames_id)
        upgraded = sum(1 for p in self.parts if p.old_schema < SCHEMA_VERSION)
        sheets = sum(1 for p in self.parts if p.moves_datasheet)
        return (
            f"{counted(len(self.parts), 'record')}: {renamed} get a new id, {upgraded} upgrade to "
            f"schema v{SCHEMA_VERSION}, {counted(sheets, 'datasheet')} move. "
            f"{counted(len(self.errors), 'blocking error')}, {counted(len(self.notes), 'note')}."
        )


def _load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_migration(library_root: Path) -> MigrationPlan:
    """Work out every move, and every reason not to make them. Reads only; writes nothing."""
    plan = MigrationPlan()
    parts_dir = library_root / "parts"
    datasheets_dir = library_root / "datasheets"
    sourced_dir = library_root / SOURCED_DIRNAME

    if not parts_dir.is_dir():
        plan.errors.append(f"no parts directory at {parts_dir.as_posix()}")
        return plan

    claimed: dict[str, str] = {}  # new_id -> the old id that claimed it first

    for path in sorted(parts_dir.glob("*.json")):
        try:
            raw = _load_raw(path)
        except (OSError, ValueError) as exc:
            plan.errors.append(f"{path.name}: unreadable ({type(exc).__name__}: {exc})")
            continue

        old_id = str(raw.get("id") or "").strip()
        mpn = str(raw.get("mpn") or "").strip()
        if not old_id:
            plan.errors.append(f"{path.name}: record has no id")
            continue
        if path.stem != old_id:
            # A filename that disagrees with the id inside is a pre-existing inconsistency, and
            # renaming it would silently pick one of the two as truth. Refuse and name both.
            plan.errors.append(
                f"{path.name}: filename stem {path.stem!r} disagrees with the record's id "
                f"{old_id!r}; resolve that by hand first - a migration must not choose for you"
            )
            continue
        if not mpn:
            # The new id is a pure function of the MPN, so without one there is nothing to compute.
            plan.errors.append(
                f"{old_id}: no MPN, so a v3 id cannot be derived (it is slug(mpn)+hash). "
                f"Give it an MPN or delete the record."
            )
            continue

        new_id = make_part_id(mpn)
        if not is_valid_part_id(new_id):
            plan.errors.append(f"{old_id}: computed id {new_id!r} is itself not path-safe")
            continue
        if new_id in claimed:
            # The 4-hex suffix of the exact MPN is what makes this near-impossible; if it happens
            # it is two records for genuinely the same MPN, which is a duplicate to resolve by
            # hand, never something to silently merge by overwriting one file with the other.
            plan.errors.append(
                f"COLLISION: {old_id!r} and {claimed[new_id]!r} both map to {new_id!r} "
                f"(same MPN {mpn!r}). Merge or delete one first - migrating would DESTROY one."
            )
            continue
        claimed[new_id] = old_id

        item = PartPlan(
            old_id=old_id,
            new_id=new_id,
            mpn=mpn,
            record_from=path,
            record_to=parts_dir / f"{new_id}.json",
            old_schema=int(raw.get("schema_version", 1) or 1),
        )

        sheet = ((raw.get("datasheet") or {}) or {}).get("file") or ""
        if sheet:
            src = datasheets_dir / sheet
            if not src.is_file():
                plan.notes.append(
                    f"{old_id}: datasheet {sheet!r} is referenced but missing on disk; the "
                    f"reference will be carried over unchanged rather than invented"
                )
            elif Path(sheet).stem == old_id:
                item.datasheet_from = src
                item.datasheet_to = datasheets_dir / f"{new_id}{Path(sheet).suffix}"
            else:
                plan.notes.append(
                    f"{old_id}: datasheet {sheet!r} is not named after the part id, so it is left "
                    f"alone (the reference stays valid either way)"
                )

        old_payloads = sourced_dir / old_id
        if old_payloads.is_dir():
            item.sourced_from = old_payloads
            item.sourced_to = sourced_dir / new_id

        plan.parts.append(item)

    # Nothing may be written on top of an existing file that is not itself moving away.
    moving_away = {p.record_from for p in plan.parts if p.renames_id}
    for p in plan.parts:
        if p.renames_id and p.record_to.exists() and p.record_to not in moving_away:
            plan.errors.append(
                f"{p.old_id}: target {p.record_to.name} already exists and is not itself being "
                f"renamed - refusing to overwrite a record"
            )
    return plan


def apply_migration(plan: MigrationPlan, library_root: Path) -> list[str]:
    """Carry out a plan. Returns the repo-relative paths touched, for the caller to commit.

    Order matters and is deliberate: every record is rewritten to its NEW path first (carrying the
    updated id and datasheet reference), and only then are the old paths removed. A crash midway
    therefore leaves BOTH copies rather than neither, which git shows plainly and a person can
    resolve - where removing first would lose data if the write failed.
    """
    if not plan.ok:
        raise ValueError("refusing to apply a plan with blocking errors")

    touched: list[str] = []

    for item in plan.parts:
        record = PartRecord.from_dict(_load_raw(item.record_from))
        record.id = item.new_id

        if item.datasheet_from is not None and item.datasheet_to is not None:
            if item.datasheet_to != item.datasheet_from:
                item.datasheet_to.parent.mkdir(parents=True, exist_ok=True)
                item.datasheet_from.replace(item.datasheet_to)
                touched.append(item.datasheet_to.relative_to(library_root).as_posix())
                touched.append(item.datasheet_from.relative_to(library_root).as_posix())
            if record.datasheet is not None:
                record.datasheet.file = item.datasheet_to.name

        if item.sourced_from is not None and item.sourced_to is not None:
            if item.sourced_to != item.sourced_from:
                item.sourced_to.parent.mkdir(parents=True, exist_ok=True)
                item.sourced_from.replace(item.sourced_to)
                touched.append(item.sourced_to.relative_to(library_root).as_posix())
            # The `sources` index stores the repo-relative payload path, so it moves with the tree.
            for name, entry in record.sources.items():
                entry.file = f"{SOURCED_DIRNAME}/{item.new_id}/{name}.json"

        # Written to the NEW path before the old one is removed (see the docstring).
        item.record_to.write_text(record.dumps(), encoding="utf-8")
        touched.append(item.record_to.relative_to(library_root).as_posix())

    for item in plan.parts:
        if item.renames_id and item.record_from.exists():
            item.record_from.unlink()
            touched.append(item.record_from.relative_to(library_root).as_posix())

    return sorted(set(touched))


def count_orphan_bindings(library_root: Path) -> int:
    """How many registered projects hold bindings this migration cannot reach.

    A binding lives in the PROJECT's repo, not the library's, so renaming a part id here silently
    breaks it. Counted so the caller can refuse rather than discover it later.
    """
    projects_dir = library_root / "projects"
    if not projects_dir.is_dir():
        return 0
    return sum(1 for _ in projects_dir.glob("*.json"))
