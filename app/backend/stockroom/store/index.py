"""The derived SQLite library index.

The per-part JSON records are the git-synced source of truth (spec section 5.1). This
module builds a SQLite database FROM those records as the fast query layer (search,
facets, duplicate detection, completion rollup) - spec section 5.2. It is a rebuildable
cache: never committed, and if lost it rebuilds from the JSON files. Build it on load
and after every git pull.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.eda.registry import all_tools
from stockroom.model.asset import ASSET_KINDS
from stockroom.model.part import PartRecord

# NO `DROP TABLE`, and every object is `IF NOT EXISTS`, because `sync()` updates an index in
# place. Dropping meant every library write - and `rebuild_index` runs after all of them - re-read
# and re-PARSED every record in the library just to reflect one edited part.
#
# `part_assets` and `part_purchase` are CHILD TABLES rather than wider `parts` columns. The old
# shape could not express "has an Altium footprint" at all: it had exactly one `footprint_name` and
# one `model_file`, both read off KiCad and named as such. Wide per-tool columns would fix that
# case and reintroduce the real problem - a THIRD EDA tool would need a schema migration, which is
# precisely the "adding a tool means editing ten places" shape the registry exists to remove. A row
# per (part, tool, kind) needs no schema change for a new tool, and none for a new asset kind.
#
# `source_hash` is the sha256 of the record file's BYTES. Content, not mtime: `touch` is not a
# change, and this repo has already been bitten once by treating an mtime as one.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS parts (
    id             TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    category       TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    mpn            TEXT NOT NULL DEFAULT '',
    manufacturer   TEXT NOT NULL DEFAULT '',
    part_class     TEXT NOT NULL DEFAULT 'component',
    footprint_name TEXT NOT NULL DEFAULT '',
    model_file     TEXT NOT NULL DEFAULT '',
    datasheet_file TEXT NOT NULL DEFAULT '',
    purchase_url   TEXT NOT NULL DEFAULT '',
    is_complete    INTEGER NOT NULL,
    missing        TEXT NOT NULL DEFAULT '',
    search_blob    TEXT NOT NULL,
    source_hash    TEXT NOT NULL DEFAULT '',
    derived_by     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_parts_category ON parts(category);
CREATE INDEX IF NOT EXISTS idx_parts_mpn      ON parts(mpn);
CREATE INDEX IF NOT EXISTS idx_parts_complete ON parts(is_complete);
CREATE INDEX IF NOT EXISTS idx_parts_fp       ON parts(footprint_name);
CREATE INDEX IF NOT EXISTS idx_parts_class    ON parts(part_class);
-- Which derivation ruleset produced each part's `derived` block. Indexed because the stamp only
-- pays for itself if "which parts are behind the current rules" is a QUERY: sweeping a 10,000-part
-- library by opening every record file is the O(n) read this index exists to remove.
CREATE INDEX IF NOT EXISTS idx_parts_derived  ON parts(derived_by);

-- One row per (part, tool, asset kind). `present` mirrors model.part.asset_present, so
-- "is this part ready for Altium" is a query rather than a per-tool column.
-- `origin_vendor` / `origin_url` / `origin_captured_at` are the asset's PROVENANCE, and
-- `checks_json` the raw CHECK FACTS - never a verdict. The pass/fail/unknown judgement is
-- DERIVED on read by model.trust, so tightening a check re-judges the whole library with no
-- re-audit, and a stored verdict can never contradict the numbers printed beside it.
CREATE TABLE IF NOT EXISTS part_assets (
    part_id            TEXT NOT NULL,
    tool               TEXT NOT NULL,
    kind               TEXT NOT NULL,
    lib                TEXT NOT NULL DEFAULT '',
    name               TEXT NOT NULL DEFAULT '',
    file               TEXT NOT NULL DEFAULT '',
    present            INTEGER NOT NULL DEFAULT 0,
    origin_vendor      TEXT NOT NULL DEFAULT '',
    origin_url         TEXT NOT NULL DEFAULT '',
    origin_captured_at TEXT NOT NULL DEFAULT '',
    checks_json        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (part_id, tool, kind)
);
CREATE INDEX IF NOT EXISTS idx_assets_tool    ON part_assets(tool, kind, present);
CREATE INDEX IF NOT EXISTS idx_assets_name    ON part_assets(tool, kind, name);
CREATE INDEX IF NOT EXISTS idx_assets_vendor  ON part_assets(origin_vendor);

-- One row per purchase link, not one `purchase_url` column. A part is genuinely orderable from
-- several distributors and the old shape kept only `purchase[0]`, so every other vendor's link,
-- order number and price ladder was invisible to every query.
CREATE TABLE IF NOT EXISTS part_purchase (
    part_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    vendor      TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    part_number TEXT NOT NULL DEFAULT '',
    stock       INTEGER,
    currency    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (part_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_purchase_vendor ON part_purchase(vendor);
"""


@dataclass
class IndexRow:
    id: str
    display_name: str
    category: str
    mpn: str
    manufacturer: str
    is_complete: bool
    missing: list[str] = field(default_factory=list)


@dataclass
class SyncStats:
    """What one `sync()` actually did. Reported so "the index is current" is a measurement.

    `unchanged` is the interesting number: on a library write it should be everything-but-one, and
    if it is ever 0 the incremental path has silently degraded back into a full rebuild.
    """

    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0

    @property
    def parsed(self) -> int:
        return self.added + self.updated

    def __str__(self) -> str:
        return (f"+{self.added} ~{self.updated} -{self.removed} "
                f"({self.unchanged} unchanged, {self.parsed} parsed)")


@dataclass
class Facets:
    by_category: dict[str, int]
    by_manufacturer: dict[str, int]
    complete: int
    incomplete: int


class LibraryIndex:
    """A derived SQLite index over a profile's JSON part records.

    Build with `LibraryIndex.build(parts_dir)` (in-memory by default, or pass a
    `db_path` under per-machine state). Rebuild whenever the source files change.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        # Every read holds this. The connection is warm and long-lived, and FastAPI runs sync route
        # handlers in a threadpool, so several requests read it at once (opening one part fires the
        # symbol, footprint and model previews in parallel, and each resolves the part through `get`).
        #
        # A single `sqlite3.Connection` is NOT safe for concurrent use, and `check_same_thread=False`
        # only silences Python's own guard; it does not make the connection safe. The sqlite3 module
        # RELEASES the GIL around the SQLite C calls precisely so other threads can run, so two workers
        # really are inside execute/fetch at the same time. SQLite answers that with SQLITE_MISUSE
        # (surfacing as `InterfaceError: bad parameter or other API misuse`) and with torn reads that
        # hand back values never stored, which is how `missing` came back None from a column declared
        # NOT NULL DEFAULT ''. Both live-app 500s traced to exactly this.
        #
        # An RLock, not a Lock: a reader that ever calls another reader would deadlock on a plain one,
        # and that is a trap to disarm now rather than discover later. Serializing costs nothing worth
        # measuring here because these are in-memory reads.
        #
        # Thread-local connections were the obvious alternative and are WRONG for this index: the
        # default db_path is ":memory:", so each thread would get its own EMPTY database.
        self._lock = threading.RLock()

    # ---- build -----------------------------------------------------------------

    @classmethod
    def build(cls, parts_dir: Path, db_path: str | Path = ":memory:") -> "LibraryIndex":
        # check_same_thread=False so the warm index can be read from the API's threadpool worker
        # threads (FastAPI runs sync route handlers off the thread that built the connection).
        # That flag only silences Python's own guard; the SERIALIZATION is `self._lock` in
        # `__init__`, and every write still goes through the M2 atomic engine, not this connection.
        #
        # This comment used to read "reads stay serialized by the GIL". That was FALSE - sqlite3
        # releases the GIL around its C calls - and it is why the torn-read 500s survived: it sat
        # here reading as a reason not to look.
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.commit()
        index = cls(conn)
        index.sync(parts_dir)
        return index

    def sync(self, parts_dir: Path) -> "SyncStats":
        """Bring the index in line with the record files. INCREMENTAL: no DROP, no full re-parse.

        `rebuild_index` runs after EVERY library write (eight call sites), and each one previously
        re-read AND re-PARSED every record in the library to reflect a single edited part - O(n) work
        for an O(1) change. This reads each file's BYTES and hashes them, and only parses the ones
        whose hash moved. Reading and hashing is cheap; `PartRecord.loads` plus the row build is the
        expensive half, and it is now paid only for what actually changed.

        Hashing CONTENT rather than trusting mtime is deliberate: `touch` is not a change, and this
        repo has already shipped one bug from treating an mtime as one.

        A record file that has disappeared has its rows DELETED, so a part removed on a peer and
        pulled in really does leave the index - the old full-rebuild got that for free by dropping
        everything, and an incremental path has to do it on purpose.
        """
        parts_dir = Path(parts_dir)
        stats = SyncStats()
        with self._lock:
            known = {
                r["id"]: r["source_hash"]
                for r in self._conn.execute("SELECT id, source_hash FROM parts")
            }
            seen: set[str] = set()
            if parts_dir.exists():
                for json_path in sorted(parts_dir.glob("*.json")):
                    raw = json_path.read_bytes()
                    digest = hashlib.sha256(raw).hexdigest()
                    part_id = json_path.stem
                    seen.add(part_id)
                    if known.get(part_id) == digest:
                        stats.unchanged += 1
                        continue
                    record = PartRecord.loads(raw.decode("utf-8"))
                    # The FILE is the authority on the id (the migration guarantees stem == id), so
                    # a record whose inner id disagrees would otherwise write a row nothing can
                    # find. Keyed on the record's own id, and the mismatch is left to the audit
                    # rather than silently reconciled here.
                    self._upsert(record, digest)
                    if part_id in known:
                        stats.updated += 1
                    else:
                        stats.added += 1
            for gone in set(known) - seen:
                self._delete(gone)
                stats.removed += 1
            self._conn.commit()
        return stats

    def _delete(self, part_id: str) -> None:
        for table in ("part_assets", "part_purchase", "parts"):
            self._conn.execute(f"DELETE FROM {table} WHERE part_id = ?"
                               if table != "parts" else "DELETE FROM parts WHERE id = ?",
                               (part_id,))

    def _upsert(self, rec: PartRecord, source_hash: str) -> None:
        """Write one record's rows. Child rows are replaced wholesale, never merged: an asset that
        was DETACHED must disappear, and merging would leave it in the index forever."""
        self._conn.execute(
            "INSERT OR REPLACE INTO parts (id, display_name, category, description, mpn, "
            "manufacturer, part_class, footprint_name, model_file, datasheet_file, purchase_url, "
            "is_complete, missing, search_blob, source_hash, derived_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _row_values(rec, source_hash),
        )
        self._conn.execute("DELETE FROM part_assets WHERE part_id = ?", (rec.id,))
        self._conn.executemany(
            "INSERT INTO part_assets (part_id, tool, kind, lib, name, file, present, "
            "origin_vendor, origin_url, origin_captured_at, checks_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            _asset_rows(rec),
        )
        self._conn.execute("DELETE FROM part_purchase WHERE part_id = ?", (rec.id,))
        self._conn.executemany(
            "INSERT INTO part_purchase (part_id, seq, vendor, url, part_number, stock, currency) "
            "VALUES (?,?,?,?,?,?,?)",
            _purchase_rows(rec),
        )

    # ---- queries ---------------------------------------------------------------

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]

    def derivation_counts(self) -> dict[str, int]:
        """How many parts each derivation ruleset produced, stamp -> count.

        A record that has never been derived carries an EMPTY stamp and appears under `""`. It is
        reported rather than folded into the current ruleset, because "never derived" and "derived
        by the rules running now" are different states and only one of them needs work.
        """
        with self._lock:
            return {
                r[0]: r[1]
                for r in self._conn.execute(
                    "SELECT derived_by, COUNT(*) FROM parts GROUP BY derived_by ORDER BY derived_by"
                )
            }

    def parts_not_derived_by(self, ruleset: str) -> list[str]:
        """The ids of every part whose derived block came from some OTHER ruleset, in id order.

        Equality, never a version comparison: a stamp is an opaque label, and a library can hold a
        block produced by a ruleset NEWER than the one running (a peer device on a later build).
        Ordered so a resumed sweep walks the same parts in the same order.
        """
        with self._lock:
            return [
                r[0]
                for r in self._conn.execute(
                    "SELECT id FROM parts WHERE derived_by IS NOT ? ORDER BY id", (ruleset,)
                )
            ]

    def search(
        self, query: str = "", category: str | None = None, complete_only: bool = False
    ) -> list[IndexRow]:
        """Case-insensitive substring search over name/MPN/manufacturer/description/tags,
        optionally scoped to a category and to complete parts only."""
        sql = "SELECT * FROM parts WHERE 1=1"
        args: list = []
        if query.strip():
            sql += " AND search_blob LIKE ?"
            args.append(f"%{query.strip().lower()}%")
        if category:
            sql += " AND category = ?"
            args.append(category)
        if complete_only:
            sql += " AND is_complete = 1"
        sql += " ORDER BY display_name COLLATE NOCASE"
        # The lock spans the COMPREHENSION, not just the execute: the cursor is consumed lazily, so
        # releasing after execute would leave another thread free to reset the statement mid-iteration.
        # Every reader below follows the same rule for the same reason.
        with self._lock:
            return [_to_row(r) for r in self._conn.execute(sql, args)]

    def get(self, part_id: str) -> IndexRow | None:
        with self._lock:
            r = self._conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
            return _to_row(r) if r else None

    def find_by_mpn(self, mpn: str) -> list[IndexRow]:
        """Exact-part match for a BOM line: case and separator insensitive
        (TPS-62130-RGTR matches tps62130rgtr) but never substring-loose, so a
        prefix or a different suffix is honestly a miss."""
        key = _mpn_key(mpn)
        if not key:
            return []
        with self._lock:
            return [
                _to_row(r)
                for r in self._conn.execute(
                    "SELECT * FROM parts WHERE mpn <> '' ORDER BY display_name COLLATE NOCASE"
                )
                if _mpn_key(r["mpn"]) == key
            ]

    def facets(self) -> Facets:
        with self._lock:
            by_category = {
                r["category"]: r["n"]
                for r in self._conn.execute(
                    "SELECT category, COUNT(*) n FROM parts GROUP BY category ORDER BY category"
                )
            }
            by_manufacturer = {
                r["manufacturer"]: r["n"]
                for r in self._conn.execute(
                    "SELECT manufacturer, COUNT(*) n FROM parts WHERE manufacturer <> '' "
                    "GROUP BY manufacturer ORDER BY manufacturer"
                )
            }
            complete = self._conn.execute(
                "SELECT COUNT(*) FROM parts WHERE is_complete = 1").fetchone()[0]
            incomplete = self._conn.execute(
                "SELECT COUNT(*) FROM parts WHERE is_complete = 0").fetchone()[0]
        return Facets(by_category, by_manufacturer, complete, incomplete)

    def duplicates_by_mpn(self) -> dict[str, list[str]]:
        """MPN -> the part ids sharing it, for MPNs used by more than one part."""
        return self._group_duplicates("mpn")

    def duplicates_by_footprint(self) -> dict[str, list[str]]:
        return self._group_duplicates("footprint_name")

    def _group_duplicates(self, column: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        with self._lock:
            for r in self._conn.execute(
                f"SELECT {column} AS key, GROUP_CONCAT(id) ids, COUNT(*) n "
                f"FROM parts WHERE {column} <> '' GROUP BY {column} HAVING n > 1"
            ):
                out[r["key"]] = sorted(r["ids"].split(","))
        return out

    # ---- per-tool asset queries (what the old single-tool shape could not express) ----

    def assets_for_tool(self, tool: str) -> dict[str, dict[str, bool]]:
        """`{part_id: {kind: present}}` for one EDA tool. A part with no bundle is absent.

        The question "which parts have an Altium footprint" was UNANSWERABLE before: the index held
        one `footprint_name`, read off KiCad and named as such, so every Altium gap was invisible to
        every query and the completion rollup could only ever describe one tool.
        """
        out: dict[str, dict[str, bool]] = {}
        with self._lock:
            for r in self._conn.execute(
                "SELECT part_id, kind, present FROM part_assets WHERE tool = ?", (tool,)
            ):
                out.setdefault(r["part_id"], {})[r["kind"]] = bool(r["present"])
        return out

    def parts_missing_asset(self, tool: str, kind: str) -> list[str]:
        """Part ids with no PRESENT asset of this kind for this tool, newest question first.

        A LEFT JOIN, deliberately: a part with no row at all for (tool, kind) is missing it just as
        surely as one whose row says `present = 0`, and an inner join would silently exclude exactly
        the parts that have never been touched for that tool - the majority, and the ones that
        matter.
        """
        with self._lock:
            return [
                r["id"]
                for r in self._conn.execute(
                    "SELECT p.id FROM parts p "
                    "LEFT JOIN part_assets a ON a.part_id = p.id AND a.tool = ? AND a.kind = ? "
                    "WHERE COALESCE(a.present, 0) = 0 ORDER BY p.display_name COLLATE NOCASE",
                    (tool, kind),
                )
            ]

    def purchase_rows(self, part_id: str) -> list[dict]:
        """Every purchase link on a part, in the record's own priority order."""
        with self._lock:
            return [
                {k: r[k] for k in ("vendor", "url", "part_number", "stock", "currency")}
                for r in self._conn.execute(
                    "SELECT vendor, url, part_number, stock, currency FROM part_purchase "
                    "WHERE part_id = ? ORDER BY seq", (part_id,)
                )
            ]

    def vendors(self) -> dict[str, int]:
        """How many parts each distributor can supply. Impossible on a single `purchase_url`."""
        with self._lock:
            return {
                r["vendor"]: r["n"]
                for r in self._conn.execute(
                    "SELECT vendor, COUNT(DISTINCT part_id) n FROM part_purchase "
                    "WHERE vendor <> '' GROUP BY vendor ORDER BY n DESC"
                )
            }

    def asset_trust(self, part_id: str, tool: str, kind: str):
        """The DERIVED trust verdict for one asset, computed from the stored check FACTS.

        The verdict is never stored (see the schema comment and model/trust.py): it is computed here
        from the measurements every time, so tightening a check re-judges the whole library with no
        re-audit and no stale verdict can contradict the numbers beside it.
        """
        from stockroom.model.trust import AssetCheck, verdict_for

        with self._lock:
            row = self._conn.execute(
                "SELECT checks_json FROM part_assets WHERE part_id = ? AND tool = ? AND kind = ?",
                (part_id, tool, kind),
            ).fetchone()
        if row is None:
            return None
        raw = row["checks_json"]
        checks = [AssetCheck.from_dict(c) for c in json.loads(raw)] if raw else []
        return verdict_for(checks)

    def assets_by_origin(self) -> dict[str, int]:
        """How many assets came from each vendor, and how many are UNATTRIBUTED.

        The owner's complaint verbatim: *"its not trusted where we've gotten them"*. An empty vendor
        is counted under "(unrecorded)" rather than dropped, because "we do not know where this came
        from" is the answer that question most needs to surface.
        """
        out: dict[str, int] = {}
        with self._lock:
            for r in self._conn.execute(
                "SELECT origin_vendor v, COUNT(*) n FROM part_assets WHERE present = 1 "
                "GROUP BY origin_vendor ORDER BY n DESC"
            ):
                out[r["v"] or "(unrecorded)"] = r["n"]
        return out

    def incomplete(self) -> list[IndexRow]:
        with self._lock:
            return [
                _to_row(r)
                for r in self._conn.execute(
                    "SELECT * FROM parts WHERE is_complete = 0 ORDER BY display_name COLLATE NOCASE"
                )
            ]

    def close(self) -> None:
        # Closing while another thread is mid-read is the same misuse as reading concurrently, so it
        # takes the lock too.
        with self._lock:
            self._conn.close()


def _mpn_key(text: str) -> str:
    """Case/separator-insensitive MPN token: alphanumerics only, lowercased."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _asset_rows(rec: PartRecord) -> list[tuple]:
    """One row per (tool, kind) the part actually holds an asset slot for.

    Iterates the EDA REGISTRY, so a third tool becomes indexed by being registered - there is no
    per-tool column to add and no branch here. Tools the part carries nothing for produce no rows,
    which is why `present` is queried with a LEFT JOIN rather than assumed.

    `checks_json` carries the raw measurements only. NO VERDICT is stored: model.trust derives
    pass/fail/unknown from these facts on read, so tightening a check re-judges the library with no
    re-audit and a verdict can never go stale against its own evidence.
    """
    rows: list[tuple] = []
    for tool in all_tools():
        bundle = rec.assets.get(tool.key)
        if bundle is None:
            continue
        for kind in ASSET_KINDS:
            asset = bundle.get(kind)
            if asset is None:
                continue
            origin = asset.origin
            rows.append((
                rec.id,
                tool.key,
                kind,
                asset.ref.lib,
                asset.ref.name,
                asset.ref.file,
                1 if asset.is_present() else 0,
                origin.vendor if origin else "",
                origin.url if origin else "",
                origin.captured_at if origin else "",
                json.dumps([c.to_dict() for c in asset.checks]) if asset.checks else "",
            ))
    return rows


def _purchase_rows(rec: PartRecord) -> list[tuple]:
    """Every purchase link, not just `purchase[0]`.

    A part is genuinely orderable from several distributors, and the single `purchase_url` column
    kept exactly one - so every other vendor's link and order number was invisible to any query.
    `seq` preserves the record's own order, which is priority order.
    """
    return [
        (rec.id, i, p.vendor, p.url, p.part_number,
         p.stock if isinstance(p.stock, int) else None, p.currency)
        for i, p in enumerate(rec.purchase)
    ]


def _row_values(rec: PartRecord, source_hash: str = "") -> tuple:
    missing = rec.missing_fields()
    # The index's footprint_name / model_file columns exist for duplicate grouping and the
    # doctor's dangling-file sweep, both of which operate on the KiCad library this app
    # actually writes. Named explicitly rather than read off a tool-neutral-looking field.
    # They are now a CONVENIENCE over `part_assets`, not the only place asset data lives.
    kicad = rec.assets_for("kicad")
    purchase_url = rec.purchase[0].url if rec.purchase and rec.purchase[0].url else ""
    search_blob = " ".join(
        filter(
            None,
            [rec.display_name, rec.mpn, rec.manufacturer, rec.description, " ".join(rec.tags), rec.category],
        )
    ).lower()
    return (
        rec.id,
        rec.display_name,
        rec.category,
        rec.description,
        rec.mpn,
        rec.manufacturer,
        rec.part_class.value,
        kicad.footprint.name if kicad.footprint else "",
        kicad.model.file if kicad.model else "",
        rec.datasheet.file if rec.datasheet else "",
        purchase_url,
        0 if missing else 1,
        ",".join(missing),
        search_blob,
        source_hash,
        rec.derived.derived_by,
    )


def _to_row(r: sqlite3.Row) -> IndexRow:
    return IndexRow(
        id=r["id"],
        display_name=r["display_name"],
        category=r["category"],
        mpn=r["mpn"],
        manufacturer=r["manufacturer"],
        is_complete=bool(r["is_complete"]),
        missing=[m for m in r["missing"].split(",") if m],
    )
