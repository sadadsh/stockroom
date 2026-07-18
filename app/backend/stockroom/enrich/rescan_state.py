"""Uncommitted, per-machine rescan progress + staleness marker.

`Purchase.fetched_at` means "when this vendor's data last CHANGED" (so a no-change refresh is a
true no-op / no commit). Staleness - "when was this part last CHECKED" - is a DIFFERENT question
and MUST NOT live in the committed record: stamping a last-checked time on every check would
reintroduce exactly the per-check commit churn the fetched_at design removed. So the marker lives
HERE, in a derived JSON file in the enrich cache dir (never committed, never synced). The same
file doubles as the resume checkpoint: a crashed/stopped/paused rescan re-runs and skips every
part it already recorded, so it never restarts the whole library."""
from __future__ import annotations

import json
from pathlib import Path


class RescanState:
    def __init__(self, path: Path):
        self._path = path
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # missing or corrupt -> empty (never raises)
        if isinstance(raw, dict) and isinstance(raw.get("parts"), dict):
            self._entries = {k: v for k, v in raw["parts"].items() if isinstance(v, dict)}

    def last_checked(self, part_id: str) -> str:
        entry = self._entries.get(part_id)
        return entry.get("checked_at", "") if isinstance(entry, dict) else ""

    def outcome(self, part_id: str) -> str:
        entry = self._entries.get(part_id)
        return entry.get("outcome", "") if isinstance(entry, dict) else ""

    def is_fresh(self, part_id: str, cutoff_iso: str) -> bool:
        """True iff this part was checked at/after cutoff_iso. Both are UTC ISO-8601, which sorts
        lexically, so a plain string compare is a valid chronological compare."""
        checked = self.last_checked(part_id)
        return bool(checked) and checked >= cutoff_iso

    def record(self, part_id: str, outcome: str, checked_at: str) -> None:
        self._entries[part_id] = {"checked_at": checked_at, "outcome": outcome}
        self._save()

    def clear(self) -> None:
        self._entries = {}
        try:
            self._path.unlink()
        except OSError:
            pass

    def entries(self) -> dict[str, dict]:
        """A copy of every recorded part -> {checked_at, outcome}, for a status surface."""
        return {k: dict(v) for k, v in self._entries.items()}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"parts": self._entries}), encoding="utf-8")
            tmp.replace(self._path)
        except OSError:
            pass  # advisory state: an unwritable dir degrades to no-resume, never raises
