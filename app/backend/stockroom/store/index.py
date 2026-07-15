"""The derived SQLite library index.

The per-part JSON records are the git-synced source of truth (spec section 5.1). This
module builds a SQLite database FROM those records as the fast query layer (search,
facets, duplicate detection, completion rollup) - spec section 5.2. It is a rebuildable
cache: never committed, and if lost it rebuilds from the JSON files. Build it on load
and after every git pull.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from stockroom.model.part import PartRecord

_SCHEMA = """
DROP TABLE IF EXISTS parts;
CREATE TABLE parts (
    id             TEXT PRIMARY KEY,
    display_name   TEXT NOT NULL,
    category       TEXT NOT NULL,
    description    TEXT NOT NULL DEFAULT '',
    mpn            TEXT NOT NULL DEFAULT '',
    manufacturer   TEXT NOT NULL DEFAULT '',
    footprint_name TEXT NOT NULL DEFAULT '',
    model_file     TEXT NOT NULL DEFAULT '',
    datasheet_file TEXT NOT NULL DEFAULT '',
    purchase_url   TEXT NOT NULL DEFAULT '',
    is_complete    INTEGER NOT NULL,
    missing        TEXT NOT NULL DEFAULT '',
    search_blob    TEXT NOT NULL
);
CREATE INDEX idx_parts_category ON parts(category);
CREATE INDEX idx_parts_mpn      ON parts(mpn);
CREATE INDEX idx_parts_complete ON parts(is_complete);
CREATE INDEX idx_parts_fp       ON parts(footprint_name);
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

    # ---- build -----------------------------------------------------------------

    @classmethod
    def build(cls, parts_dir: Path, db_path: str | Path = ":memory:") -> "LibraryIndex":
        # check_same_thread=False so the warm index can be read from the API's
        # threadpool worker threads (FastAPI runs sync route handlers off the
        # thread that built the connection); reads stay serialized by the GIL and
        # every write still goes through the M2 atomic engine, not this connection.
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        parts_dir = Path(parts_dir)
        if parts_dir.exists():
            rows = []
            for json_path in sorted(parts_dir.glob("*.json")):
                rows.append(_row_values(PartRecord.loads(json_path.read_text(encoding="utf-8"))))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO parts (id, display_name, category, description, mpn, "
                    "manufacturer, footprint_name, model_file, datasheet_file, purchase_url, "
                    "is_complete, missing, search_blob) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
        conn.commit()
        return cls(conn)

    # ---- queries ---------------------------------------------------------------

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]

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
        return [_to_row(r) for r in self._conn.execute(sql, args)]

    def get(self, part_id: str) -> IndexRow | None:
        r = self._conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
        return _to_row(r) if r else None

    def find_by_mpn(self, mpn: str) -> list[IndexRow]:
        """Exact-part match for a BOM line: case and separator insensitive
        (TPS-62130-RGTR matches tps62130rgtr) but never substring-loose, so a
        prefix or a different suffix is honestly a miss."""
        key = _mpn_key(mpn)
        if not key:
            return []
        return [
            _to_row(r)
            for r in self._conn.execute(
                "SELECT * FROM parts WHERE mpn <> '' ORDER BY display_name COLLATE NOCASE"
            )
            if _mpn_key(r["mpn"]) == key
        ]

    def facets(self) -> Facets:
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
        complete = self._conn.execute("SELECT COUNT(*) FROM parts WHERE is_complete = 1").fetchone()[0]
        incomplete = self._conn.execute("SELECT COUNT(*) FROM parts WHERE is_complete = 0").fetchone()[0]
        return Facets(by_category, by_manufacturer, complete, incomplete)

    def duplicates_by_mpn(self) -> dict[str, list[str]]:
        """MPN -> the part ids sharing it, for MPNs used by more than one part."""
        return self._group_duplicates("mpn")

    def duplicates_by_footprint(self) -> dict[str, list[str]]:
        return self._group_duplicates("footprint_name")

    def _group_duplicates(self, column: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for r in self._conn.execute(
            f"SELECT {column} AS key, GROUP_CONCAT(id) ids, COUNT(*) n "
            f"FROM parts WHERE {column} <> '' GROUP BY {column} HAVING n > 1"
        ):
            out[r["key"]] = sorted(r["ids"].split(","))
        return out

    def incomplete(self) -> list[IndexRow]:
        return [
            _to_row(r)
            for r in self._conn.execute(
                "SELECT * FROM parts WHERE is_complete = 0 ORDER BY display_name COLLATE NOCASE"
            )
        ]

    def close(self) -> None:
        self._conn.close()


def _mpn_key(text: str) -> str:
    """Case/separator-insensitive MPN token: alphanumerics only, lowercased."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _row_values(rec: PartRecord) -> tuple:
    missing = rec.missing_fields()
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
        rec.footprint.name if rec.footprint else "",
        rec.model.file if rec.model else "",
        rec.datasheet.file if rec.datasheet else "",
        purchase_url,
        0 if missing else 1,
        ",".join(missing),
        search_blob,
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
