"""Durable guided-assembly runs over format-neutral project placements.

An active run pins one clean Git commit and a snapshot of every placed component.
Each bench action is an immutable JSON event written atomically to machine-local
state. Reopening Stockroom reconstructs current placement state from those events,
so progress never depends on an in-memory cache or the native EDA application.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from stockroom.model.project import ProjectRecord
from stockroom.projects import binding, placements
from stockroom.vcs.repo import GitRepo

_EVENT_STATES = frozenset({"done", "skipped", "reworked", "issue"})
_WRITE_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid assembly record: {path}")
    return value


def _placement_id(component: dict, board_index: int, ordinal: int) -> str:
    native = str(component.get("uuid") or "").strip()
    identity = "|".join(
        (
            str(board_index),
            native,
            str(component.get("_sheet") or ""),
            str(component.get("ref") or ""),
            str(ordinal),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _snapshot_placements(
    components: list[dict],
    boards: int,
    library_parts: list[object] | tuple[object, ...] = (),
) -> list[dict]:
    library_by_id = {
        str(getattr(part, "id", "") or ""): part
        for part in library_parts
        if str(getattr(part, "id", "") or "")
    }
    placements: list[dict] = []
    for board_index in range(1, boards + 1):
        for ordinal, component in enumerate(components):
            props = dict(component.get("props") or {})
            part_id = binding.bound_part_id(component)
            part = library_by_id.get(part_id)
            placements.append(
                {
                    "placement_id": _placement_id(component, board_index, ordinal),
                    "board_index": board_index,
                    "native_id": str(component.get("uuid") or ""),
                    "reference": str(component.get("ref") or ""),
                    "sheet": str(component.get("_sheet") or ""),
                    "value": str(component.get("value") or props.get("Value") or ""),
                    "footprint": str(component.get("footprint") or props.get("Footprint") or ""),
                    "part_id": part_id,
                    "mpn": str(
                        getattr(part, "mpn", "")
                        if part is not None
                        else props.get("MPN") or ""
                    ),
                    "manufacturer": str(
                        getattr(part, "manufacturer", "")
                        if part is not None
                        else props.get("Manufacturer") or ""
                    ),
                }
            )
    return placements


class AssemblyRunStore:
    """Filesystem event store for active and completed guided assembly runs."""

    def __init__(
        self,
        root: Path,
        *,
        now: Callable[[], str] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root)
        self._now = now or _now_iso
        self._new_id = new_id or (lambda: uuid4().hex)

    def start(
        self,
        project: ProjectRecord,
        *,
        operator: str,
        boards: int = 1,
        library_parts: list[object] | tuple[object, ...] = (),
    ) -> dict:
        operator = operator.strip()
        if not operator:
            raise ValueError("an assembly operator is required")
        if boards < 1 or boards > 10_000:
            raise ValueError("boards must be between 1 and 10000")
        if not project.git_root:
            raise ValueError("link the project to a Git repository before starting assembly")

        repo = GitRepo(Path(project.git_root))
        if not repo.is_git_repo():
            raise ValueError("the linked project repository is unavailable")
        if not repo.is_clean():
            raise ValueError(
                "commit or preserve local project changes before pinning an assembly run"
            )
        components = placements.read_placements(project)
        if not components:
            raise ValueError("the project has no readable placed components")

        placement_snapshot = _snapshot_placements(components, boards, library_parts)
        started_at = self._now()
        run_id = self._new_id()
        run = {
            "schema_version": 1,
            "id": run_id,
            "project_id": project.id,
            "project_name": project.name,
            "eda": project.eda,
            "operator": operator,
            "boards": boards,
            "source_commit": repo.head(),
            "project_digest": _digest(
                {
                    "descriptor": project.pro_path,
                    "boards": project.board_paths,
                    "schematics": project.sheet_paths,
                    "placements": placement_snapshot,
                }
            ),
            "started_at": started_at,
            "completed_at": "",
            "status": "active",
            "placements": placement_snapshot,
        }
        with _WRITE_LOCK:
            active = self._active_path(project.id)
            if active.exists():
                current_id = str(_read_json(active).get("run_id") or "")
                if current_id and self._run_path(project.id, current_id).exists():
                    raise ValueError("this project already has an active assembly run")
            _atomic_json(self._run_path(project.id, run_id), run)
            _atomic_json(active, {"run_id": run_id})
        return self.get(project.id, run_id)

    def active(self, project_id: str) -> dict | None:
        active = self._active_path(project_id)
        if not active.exists():
            return None
        payload = _read_json(active)
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            return None
        return self.get(project_id, run_id)

    def complete(self, project_id: str, run_id: str) -> dict:
        with _WRITE_LOCK:
            current = self.get(project_id, run_id)
            if current.get("status") != "active":
                raise ValueError("this assembly run is already closed")
            counts = current["progress"]["counts"]
            if counts["pending"] or counts["issue"]:
                raise ValueError(
                    "resolve every pending placement and issue before completing the run"
                )
            completed_at = self._now()
            run = _read_json(self._run_path(project_id, run_id))
            receipt = {
                "schema_version": 1,
                "run_id": run_id,
                "project_id": project_id,
                "source_commit": run["source_commit"],
                "project_digest": run["project_digest"],
                "event_digest": _digest(current["events"]),
                "counts": counts,
                "completed_at": completed_at,
            }
            run["status"] = "completed"
            run["completed_at"] = completed_at
            run["receipt"] = dict(receipt, digest=_digest(receipt))
            _atomic_json(self._run_path(project_id, run_id), run)
            active = self._active_path(project_id)
            if active.exists():
                active_run = str(_read_json(active).get("run_id") or "")
                if active_run == run_id:
                    active.unlink()
        return self.get(project_id, run_id)

    def get(self, project_id: str, run_id: str) -> dict:
        run = _read_json(self._run_path(project_id, run_id))
        events = [
            _read_json(path) for path in sorted(self._events_dir(project_id, run_id).glob("*.json"))
        ]
        latest: dict[str, dict] = {}
        for event in events:
            latest[str(event["placement_id"])] = event
        placements = [
            dict(
                placement,
                state=latest.get(str(placement["placement_id"]), {}).get("state", "pending"),
                last_event=latest.get(str(placement["placement_id"])),
            )
            for placement in run["placements"]
        ]
        counts = {state: 0 for state in ("pending", "done", "skipped", "reworked", "issue")}
        for placement in placements:
            counts[str(placement["state"])] += 1
        resolved = counts["done"] + counts["skipped"] + counts["reworked"]
        return dict(
            run,
            placements=placements,
            events=events,
            progress={
                "total": len(placements),
                "complete": counts["done"],
                "resolved": resolved,
                "counts": counts,
                "percent": (
                    round((resolved / len(placements)) * 100, 1) if placements else 0.0
                ),
            },
        )

    def record_event(
        self,
        project_id: str,
        run_id: str,
        *,
        placement_id: str,
        state: str,
        scanned_mpn: str = "",
        note: str = "",
    ) -> dict:
        state = state.strip().lower()
        if state not in _EVENT_STATES:
            raise ValueError("assembly state must be done, skipped, reworked, or issue")
        run = self.get(project_id, run_id)
        placement = next(
            (item for item in run["placements"] if item["placement_id"] == placement_id),
            None,
        )
        if placement is None:
            raise FileNotFoundError(f"no such placement in assembly run: {placement_id}")
        scanned_mpn = scanned_mpn.strip()
        expected_mpn = str(placement.get("mpn") or "").strip()
        if state == "done" and scanned_mpn and expected_mpn:
            if scanned_mpn.casefold() != expected_mpn.casefold():
                raise ValueError(
                    f"scanned MPN {scanned_mpn} does not match expected MPN {expected_mpn}"
                )

        with _WRITE_LOCK:
            fresh = self.get(project_id, run_id)
            if fresh.get("status") != "active":
                raise ValueError("a completed assembly run cannot accept new events")
            sequence = len(list(self._events_dir(project_id, run_id).glob("*.json"))) + 1
            event = {
                "schema_version": 1,
                "id": self._new_id(),
                "sequence": sequence,
                "run_id": run_id,
                "placement_id": placement_id,
                "state": state,
                "scanned_mpn": scanned_mpn,
                "note": note.strip(),
                "recorded_at": self._now(),
            }
            event_path = self._events_dir(project_id, run_id) / (
                f"{sequence:08d}-{event['id']}.json"
            )
            _atomic_json(event_path, event)
        return self.get(project_id, run_id)

    def _project_dir(self, project_id: str) -> Path:
        if not project_id or any(
            char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in project_id
        ):
            raise ValueError("invalid project id")
        return self.root / project_id

    def _run_path(self, project_id: str, run_id: str) -> Path:
        if not run_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for char in run_id
        ):
            raise ValueError("invalid assembly run id")
        return self._project_dir(project_id) / run_id / "run.json"

    def _events_dir(self, project_id: str, run_id: str) -> Path:
        return self._run_path(project_id, run_id).parent / "events"

    def _active_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "active.json"
