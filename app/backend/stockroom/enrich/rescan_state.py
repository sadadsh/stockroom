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
import os
import tempfile
from pathlib import Path

from stockroom.enrich.cache import _retry_transient


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
        """True iff this part was SUCCESSFULLY checked at/after cutoff_iso. A part recorded 'failed'
        is never fresh, so an incremental re-run retries it (rather than skipping a stale failure for
        a whole TTL); only force re-fetches successful parts. Timestamps are UTC ISO-8601, which
        sorts lexically, so the compare is a valid chronological compare."""
        checked = self.last_checked(part_id)
        return bool(checked) and self.outcome(part_id) != "failed" and checked >= cutoff_iso

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
        # Concurrency-safe like TtlCache.put: a unique temp file (never a fixed shared name) so
        # two concurrent writers (two rescan runs, or a GET /rescan/state read racing a write on
        # Windows) never tear each other's write, plus a retried os.replace for the transient
        # Windows sharing violation. Every filesystem step - mkdir, mkstemp, write, replace - is
        # inside this one degrading try, so any failure (including a persistent one) leaves the
        # prior on-disk file INTACT and just skips this save; this state is advisory (resume-only)
        # and must never raise into the enrich job.
        body = json.dumps({"parts": self._entries})
        tmp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=self._path.name + ".", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            _retry_transient(lambda: os.replace(tmp, str(self._path)))
        except OSError:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass  # best-effort cleanup: a peer or the OS may have already removed it
            # advisory state: an unwritable dir / persistent replace failure degrades to
            # no-persist, leaving the prior self._path (if any) untouched, never raises
