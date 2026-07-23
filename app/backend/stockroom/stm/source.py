"""Locate the CubeMX MCU XML source tree + the derived index path (Qt-free, stdlib-only).

The CubeMX database (ST's own STM32CubeMX install, or a synced copy of it) is the
read-only ground truth every STM32 device XML is parsed from. It is NOT bundled with
this app and NOT committed: the user (or an env var, in tests/CI) points at it.

default_cubemx_source() prefers a real all-families tree over the WSL fixture: the
fixture at ~/git/STMP/src/cubemx_db/mcu is F0-F7 only (~427 XML) and is never the
right answer for "all families" - it is a last-resort, loudly-logged fallback so a
Linux dev/CI box without the Windows-side tree can still run something.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from stockroom.store.machine_config import config_dir

logger = logging.getLogger(__name__)

# The two confirmed Windows-side all-families candidates (verified 2026-07-23: each
# reports 2,136 device XML, spanning every STM32 family CubeMX ships). Order: the
# synced STMP copy first (stable, versioned), then the live CubeMX install.
_WINDOWS_CANDIDATES = (
    "/mnt/c/Users/Sadad Haidari/STMP/cubemx_db/mcu",
    "/mnt/c/Users/Sadad Haidari/AppData/Local/Programs/STM32CubeMX/db/mcu",
)
# The WSL-native fixture: F0-F7 only (~427 XML), a test/dev fallback, never
# presented as "all families" (DATA-01's whole point).
_FIXTURE_FALLBACK = Path.home() / "git" / "STMP" / "src" / "cubemx_db" / "mcu"


def default_cubemx_source() -> Path | None:
    """Locate the CubeMX MCU XML directory, or None if nothing is found.

    STM32_CUBEMX (or the legacy HWKIT_CUBEMX) wins outright when set and valid.
    Otherwise the confirmed Windows-side all-families candidates are tried first;
    only if neither exists does this fall back to the WSL F-only fixture, with a
    loud warning log line so the fallback is never silently mistaken for coverage
    of every family.
    """
    env = os.environ.get("STM32_CUBEMX") or os.environ.get("HWKIT_CUBEMX")
    if env and Path(env).is_dir():
        return Path(env)
    for candidate in _WINDOWS_CANDIDATES:
        c = Path(candidate)
        if c.is_dir() and any(c.glob("*.xml")):
            return c
    if _FIXTURE_FALLBACK.is_dir() and any(_FIXTURE_FALLBACK.glob("*.xml")):
        logger.warning(
            "STM32 CubeMX source: falling back to the WSL F-only fixture at %s "
            "(F0-F7 only, ~427 device XML). This is NOT an all-families source - "
            "point STM32_CUBEMX at the real CubeMX mcu/ tree for full coverage.",
            _FIXTURE_FALLBACK,
        )
        return _FIXTURE_FALLBACK
    return None


def default_index_path() -> Path:
    """Where the derived STM index lives (per-machine state, never committed).

    STOCKROOM_STM_INDEX overrides for tests/portable installs (mirrors
    STOCKROOM_CONFIG_DIR); otherwise config_dir()/stm/index.sqlite.
    """
    override = os.environ.get("STOCKROOM_STM_INDEX")
    if override:
        return Path(override)
    return config_dir() / "stm" / "index.sqlite"


def source_sha256(source_dir: Path) -> str:
    """Content identity of the CubeMX source: sha256 over sorted (name, bytes) of
    every device *.xml (families.xml excluded - it is an index file, not a device).

    Shared by StmIndex.build (skip-rebuild on an unchanged source) and
    check_availability, so both walk the exact same file set the same way.
    """
    source_dir = Path(source_dir)
    files = sorted(p for p in source_dir.glob("*.xml") if p.name != "families.xml")
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()
