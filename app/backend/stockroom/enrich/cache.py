"""A per-part enrichment cache so a part is never re-scraped needlessly (spec
section 6.1). One JSON file per key named <prefix>___<mpn>___<epoch>.json, with
the freshness stamp in the filename and the MPN normalized to a filesystem-safe
key (KiABOM pattern, verified in the research). The prefix separates SKU-keyed
from MPN-keyed entries so they cannot collide (KiCost mou_ vs mpn_)."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

from stockroom.enrich.schema import normalize_mpn

_SEP = "___"


class TtlCache:
    """Concurrency-safe under the JobRunner's parallel read lane: two enrich jobs can hit the
    SAME normalized MPN at once (a bulk import overlapping an Add-A-Part lookup). So reads never
    raise on a file a peer removed mid-iteration or on a torn/corrupt body - they treat it as a
    miss and best-effort drop it - and writes are atomic (a unique temp file + os.replace), so a
    reader never observes a half-written entry and two writers for the same key never interleave
    into a torn JSON that would poison the key for a whole TTL (the engine never raises)."""

    def __init__(
        self,
        root: Path,
        ttl: float = 86400.0,
        prefix: str = "mpn",
        clock: Callable[[], float] = time.time,
    ):
        self.root = Path(root)
        self.ttl = ttl
        self.prefix = prefix
        self._clock = clock
        self.root.mkdir(parents=True, exist_ok=True)

    def _glob(self, key: str) -> list[Path]:
        return sorted(self.root.glob(f"{self.prefix}{_SEP}{key}{_SEP}*.json"))

    @staticmethod
    def _remove(path: Path) -> None:
        # Best-effort: a peer thread (another read-lane job) may have removed it already.
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _clear(self, key: str) -> None:
        for p in self._glob(key):
            self._remove(p)

    def get(self, mpn: str) -> dict | None:
        key = normalize_mpn(mpn)
        now = self._clock()
        for path in self._glob(key):
            try:
                stamp = float(path.stem.rsplit(_SEP, 1)[1])
            except (IndexError, ValueError):
                self._remove(path)
                continue
            if now - stamp >= self.ttl:
                self._remove(path)
                continue
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                # Removed by a peer between the glob and the read, or a torn/corrupt body:
                # treat as a miss and drop it so a fresh scrape can repopulate the key.
                self._remove(path)
                continue
        return None

    def put(self, mpn: str, data: dict) -> None:
        key = normalize_mpn(mpn)
        self._clear(key)
        stamp = int(self._clock())
        path = self.root / f"{self.prefix}{_SEP}{key}{_SEP}{stamp}.json"
        body = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
        # Atomic publish: write to a unique temp file in the same dir (so it never matches the
        # entry glob), then os.replace onto the final name. A reader never sees a half-written
        # file, and two concurrent writers each replace atomically (last wins with a COMPLETE
        # file), never a torn JSON. The temp is cleaned up if the write itself fails.
        fd, tmp = tempfile.mkstemp(
            dir=self.root, prefix=f".{self.prefix}{_SEP}{key}{_SEP}", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, path)
        except BaseException:
            self._remove(Path(tmp))
            raise
