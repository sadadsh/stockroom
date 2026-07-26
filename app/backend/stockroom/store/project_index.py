"""The derived SQLite projects index.

The per-project JSON ProjectRecords are the git-synced source of truth; this builds a
SQLite database FROM them as the fast query layer (list, search), mirroring
store/index.py for parts. A rebuildable cache: never committed, rebuilt on load and
after every git pull.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from stockroom.model.project import ProjectRecord

_SCHEMA = """
DROP TABLE IF EXISTS projects;
CREATE TABLE projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    root          TEXT NOT NULL,
    pro_path      TEXT NOT NULL DEFAULT '',
    eda           TEXT NOT NULL DEFAULT 'kicad',
    board_count   INTEGER NOT NULL DEFAULT 0,
    sheet_count   INTEGER NOT NULL DEFAULT 0,
    has_git       INTEGER NOT NULL DEFAULT 0,
    registered_at TEXT NOT NULL DEFAULT '',
    search_blob   TEXT NOT NULL
);
CREATE INDEX idx_projects_name ON projects(name);
"""


@dataclass
class ProjectIndexRow:
    id: str
    name: str
    root: str
    pro_path: str
    eda: str
    board_count: int
    sheet_count: int
    has_git: bool
    registered_at: str


@dataclass
class ProjectFacets:
    total: int
    with_git: int


class ProjectIndex:
    """A derived SQLite index over the JSON ProjectRecords.

    Build with `ProjectIndex.build(projects_dir)` (in-memory by default). Rebuild
    whenever the source files change. Mirrors store/index.py LibraryIndex.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @classmethod
    def build(cls, projects_dir: Path, db_path: str | Path = ":memory:") -> "ProjectIndex":
        # check_same_thread=False so the warm index reads from the API threadpool
        # workers, exactly like LibraryIndex; every write still goes through the store.
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        projects_dir = Path(projects_dir)
        if projects_dir.exists():
            rows = []
            for json_path in sorted(projects_dir.glob("*.json")):
                rows.append(_row_values(ProjectRecord.loads(json_path.read_text(encoding="utf-8"))))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO projects (id, name, root, pro_path, eda, board_count, "
                    "sheet_count, has_git, registered_at, search_blob) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
        conn.commit()
        return cls(conn)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    def search(self, query: str = "") -> list[ProjectIndexRow]:
        """Case-insensitive substring search over name and root, sorted by name."""
        sql = "SELECT * FROM projects WHERE 1=1"
        args: list = []
        if query.strip():
            sql += " AND search_blob LIKE ?"
            args.append(f"%{query.strip().lower()}%")
        sql += " ORDER BY name COLLATE NOCASE"
        return [_to_row(r) for r in self._conn.execute(sql, args)]

    def all(self) -> list[ProjectIndexRow]:
        return self.search("")

    def get(self, project_id: str) -> ProjectIndexRow | None:
        r = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _to_row(r) if r else None

    def facets(self) -> ProjectFacets:
        total = self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        with_git = self._conn.execute("SELECT COUNT(*) FROM projects WHERE has_git = 1").fetchone()[0]
        return ProjectFacets(total=total, with_git=with_git)

    def close(self) -> None:
        self._conn.close()


def _row_values(rec: ProjectRecord) -> tuple:
    search_blob = " ".join(filter(None, [rec.name, rec.root])).lower()
    return (
        rec.id,
        rec.name,
        rec.root,
        rec.pro_path,
        rec.eda,
        len(rec.board_paths),
        len(rec.sheet_paths),
        1 if rec.git_root else 0,
        rec.registered_at,
        search_blob,
    )


def _to_row(r: sqlite3.Row) -> ProjectIndexRow:
    return ProjectIndexRow(
        id=r["id"],
        name=r["name"],
        root=r["root"],
        pro_path=r["pro_path"],
        eda=r["eda"],
        board_count=r["board_count"],
        sheet_count=r["sheet_count"],
        has_git=bool(r["has_git"]),
        registered_at=r["registered_at"],
    )
