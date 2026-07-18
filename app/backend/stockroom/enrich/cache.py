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


def _retry_transient(op: Callable[[], object], attempts: int = 8, base_delay: float = 0.002):
    """Run a filesystem op, retrying the TRANSIENT sharing violations that Windows raises when a
    concurrent read-lane job holds the same cache file open across an os.replace (WinError 5/32,
    surfaced as PermissionError - an OSError, not FileNotFoundError/ValueError). These clear in
    microseconds once the peer closes the handle, so a short bounded backoff resolves them; on
    POSIX the op just succeeds on the first try. FileNotFoundError is definitive (the file is
    gone), so it is never retried, and the final attempt's error propagates for the caller to
    decide how to degrade."""
    for i in range(attempts):
        try:
            return op()
        except FileNotFoundError:
            raise
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (i + 1))


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
        # Best-effort: a peer read-lane job may have removed it already (FileNotFoundError) or may
        # hold it open on Windows (PermissionError - you cannot unlink an open file there). Either
        # way there is nothing to do: a file we cannot delete now is stale/being-replaced and gets
        # pruned on a later pass. Retry the transient Windows sharing violation, then give up
        # silently - an unlink must never raise into the enrich job (it runs before put()'s try).
        try:
            _retry_transient(path.unlink)
        except OSError:
            pass

    def _clear(self, key: str) -> None:
        for p in self._glob(key):
            self._remove(p)

    def get(self, mpn: str) -> dict | None:
        key = normalize_mpn(mpn)
        now = self._clock()
        candidates: list[tuple[float, Path]] = []
        for path in self._glob(key):
            try:
                stamp = float(path.stem.rsplit(_SEP, 1)[1])
            except (IndexError, ValueError):
                self._remove(path)  # unparseable stamp: not a real entry, drop it
                continue
            candidates.append((stamp, path))
        # NEWEST first: a lingering un-removable older entry (a persistent Windows lock can defeat
        # _clear, whose failure is now swallowed) must never shadow the freshest write.
        for stamp, path in sorted(candidates, key=lambda c: c[0], reverse=True):
            if now - stamp >= self.ttl:
                self._remove(path)
                continue
            try:
                return json.loads(_retry_transient(lambda p=path: p.read_text(encoding="utf-8")))
            except FileNotFoundError:
                continue  # a peer (another read-lane job) removed it between the glob and the read
            except OSError:
                # A Windows sharing violation that outlasted the retries: a peer is mid-os.replace
                # of this file. It is a VALID entry being rewritten, not corrupt, so skip it WITHOUT
                # dropping it - a miss here just re-scrapes, never raises and never poisons.
                continue
            except ValueError:
                # A corrupt body: non-UTF-8 bytes (UnicodeDecodeError) or invalid JSON
                # (JSONDecodeError) - both are ValueError. Drop it so a fresh scrape repopulates.
                self._remove(path)
                continue
        return None

    def put(self, mpn: str, data: dict) -> None:
        key = normalize_mpn(mpn)
        self._clear(key)
        stamp = int(self._clock())
        path = self.root / f"{self.prefix}{_SEP}{key}{_SEP}{stamp}.json"
        # Atomic publish: write to a unique temp file in the same dir (so it never matches the
        # entry glob), then os.replace onto the final name. A reader never sees a half-written
        # file, and two concurrent writers each replace atomically (last wins with a COMPLETE
        # file), never a torn JSON. On Windows the replace can hit a transient sharing violation
        # when a reader holds the destination open, so it is retried. EVERY filesystem step - the
        # mkstemp create too (an unwritable/full dir), not just the replace - is inside the try, so
        # a persistent failure degrades to no-cache (the next lookup re-scrapes) rather than raising
        # into the enrich job; the cache is best-effort. A json.dumps TypeError (a non-serializable
        # value = a real caller bug) still propagates via the BaseException arm.
        tmp: Path | None = None
        try:
            body = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            fd, tmp_name = tempfile.mkstemp(
                dir=self.root, prefix=f".{self.prefix}{_SEP}{key}{_SEP}", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            _retry_transient(lambda: os.replace(tmp, path))
        except OSError:
            if tmp is not None:
                self._remove(tmp)  # best-effort cache: skip this entry rather than raise
        except BaseException:
            if tmp is not None:
                self._remove(tmp)
            raise
