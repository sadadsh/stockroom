"""A per-part enrichment cache so a part is never re-scraped needlessly (spec
section 6.1). One JSON file per key named <prefix>___<mpn>___<epoch>.json, with
the freshness stamp in the filename and the MPN normalized to a filesystem-safe
key (KiABOM pattern, verified in the research). The prefix separates SKU-keyed
from MPN-keyed entries so they cannot collide (KiCost mou_ vs mpn_)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from stockroom.enrich.schema import normalize_mpn

_SEP = "___"


class TtlCache:
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

    def _clear(self, key: str) -> None:
        for p in self._glob(key):
            p.unlink()

    def get(self, mpn: str) -> dict | None:
        key = normalize_mpn(mpn)
        now = self._clock()
        for path in self._glob(key):
            try:
                stamp = float(path.stem.rsplit(_SEP, 1)[1])
            except (IndexError, ValueError):
                path.unlink()
                continue
            if now - stamp >= self.ttl:
                path.unlink()
                continue
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def put(self, mpn: str, data: dict) -> None:
        key = normalize_mpn(mpn)
        self._clear(key)
        stamp = int(self._clock())
        path = self.root / f"{self.prefix}{_SEP}{key}{_SEP}{stamp}.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
