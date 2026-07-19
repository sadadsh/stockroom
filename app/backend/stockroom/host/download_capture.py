"""Tier 2 of the CAD-asset download capture (plan
docs/superpowers/plans/2026-07-18-digikey-asset-download.md, Task 3): a Downloads-folder
watch, used as the always-available fallback when pywebview's tier-1 download intercept
(host/window.py, Windows-only) is unavailable or produces nothing. This module is PURE
filesystem logic - it imports NO pywebview / WebView2 - so it imports and unit-tests on
Linux; host/window.py is the Windows-only integration point that arms a DownloadsWatch
alongside the tier-1 intercept when it opens a distributor CAD page.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path

NowFn = Callable[[], float]
ListDirFn = Callable[[Path], Iterable[Path]]


def _os_name() -> str:
    return os.name


def default_downloads_dir() -> Path:
    """The OS's per-user Downloads folder: %USERPROFILE%\\Downloads on Windows,
    ~/Downloads elsewhere. Mirrors the platform-base idiom already used for the KiCad
    config dir (kicad/config.py), the machine config dir (store/machine_config.py), and
    the launcher data dir (launcher/launch.py) - including testing the branch through an
    indirection (`_os_name()`, monkeypatched in tests) rather than the real `os.name`:
    pathlib.Path picks its concrete WindowsPath/PosixPath subclass from the REAL os.name
    at construction time, so faking os.name itself makes Path(...) raise
    NotImplementedError on a non-Windows test runner."""
    if _os_name() == "nt":
        base = os.environ.get("USERPROFILE") or str(Path.home())
    else:
        base = str(Path.home())
    return Path(base) / "Downloads"


def _default_listdir(directory: Path) -> Iterable[Path]:
    return Path(directory).iterdir()


class DownloadsWatch:
    """Watches a Downloads directory for a NEW *.zip that appears after the watch
    armed, so a distributor download saved through the browser's normal Save-As flow
    (or an unattended auto-save) can still be surfaced when pywebview's tier-1 intercept
    is unavailable or captures nothing.

    Pure filesystem logic: `now` and `listdir` are injected so poll() is deterministic
    and testable without a real clock or a real Downloads folder. poll() returns the
    newest qualifying *.zip file (case-insensitive suffix, regular files only - a
    directory that happens to be named "foo.zip" is never mistaken for a download),
    skipping:
      - anything whose mtime predates `started_at` (it was already there, not a new
        download this watch should claim),
      - anything not a *.zip,
      - anything already returned by an earlier poll() on this same instance (so a
        caller can poll in a loop without ever being handed the same file twice),
      - anything whose mtime somehow reads AFTER the current `now()` (clock skew on a
        mapped drive, a corrupted timestamp) - not trustworthy evidence the file just
        arrived, so it is skipped rather than surfaced as the definitive newest capture.
    Returns None when nothing qualifies.
    """

    def __init__(
        self,
        downloads_dir: Path,
        started_at: float,
        *,
        now: NowFn = time.time,
        listdir: ListDirFn | None = None,
    ):
        self._dir = Path(downloads_dir)
        self._started_at = started_at
        self._now = now
        self._listdir = listdir or _default_listdir
        self._seen: set[Path] = set()

    @classmethod
    def start(
        cls,
        downloads_dir: Path,
        *,
        now: NowFn = time.time,
        listdir: ListDirFn | None = None,
    ) -> "DownloadsWatch":
        """Arm a watch AS OF right now - the convenience constructor the real host
        (host/window.py's open_cad_download) uses, where "the watch started" simply
        means "the moment the distributor page opened"."""
        return cls(downloads_dir, now(), now=now, listdir=listdir)

    def poll(self) -> Path | None:
        try:
            entries = list(self._listdir(self._dir))
        except OSError:
            return None  # the Downloads dir is missing/unreadable: nothing found, not a crash
        current = self._now()
        candidates: list[tuple[float, Path]] = []
        for entry in entries:
            path = Path(entry)
            if path.suffix.lower() != ".zip":
                continue
            if path in self._seen:
                continue
            try:
                if not path.is_file():
                    continue  # a directory named "*.zip" is not a downloaded archive
                mtime = path.stat().st_mtime
            except OSError:
                continue  # vanished between listing and stat (a rename race): skip, not crash
            if mtime < self._started_at or mtime > current:
                continue
            candidates.append((mtime, path))
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0])
        newest = candidates[-1][1]
        self._seen.add(newest)
        return newest
