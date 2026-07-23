"""Baked-snapshot seed for the derived STM index (Qt-free, stdlib-only).

The repo commits data/stm/index.sqlite.xz: an xz compression of a fully built,
stamp-valid index (owner decision 2026-07-23, amending the never-commit invariant -
the COMPRESSED seed is committed so a fresh machine boots without a CubeMX source
tree or a first build; the RAW sqlite stays per-machine and gitignored). Restoring
is transport only: StmIndex.load's rev-stamp gate stays the sole authority on
whether the decompressed file is trusted, so a seed baked before a classifier/AF/
geometry rev bump decompresses and is then refused exactly like any stale file,
falling back to the normal source build. scripts/bake_stm_index.py re-bakes after
a rev bump (it refuses to bake anything the load gate would not accept).
"""

from __future__ import annotations

import logging
import lzma
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK = 4 * 1024 * 1024


def default_seed_path() -> Path:
    """The committed seed artifact: repo-root data/stm/index.sqlite.xz.

    STOCKROOM_STM_SEED overrides for tests/portable installs (mirrors
    STOCKROOM_STM_INDEX). The default anchors on this package's location
    (app/backend/stockroom/stm/ -> four parents up = the repo root), the same
    resolution idiom api/app.py uses for the frontend-dist directory.
    """
    override = os.environ.get("STOCKROOM_STM_SEED")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "data" / "stm" / "index.sqlite.xz"


def restore_baked_index(target: Path) -> bool:
    """Decompress the baked seed to ``target`` (atomically), or return False.

    False when no seed artifact exists or the stream is corrupt/unreadable - never
    raises, never leaves a partial target or temp litter, and never touches an
    existing target unless the full decompression succeeded (write-to-temp then
    os.replace). The caller re-runs StmIndex.load afterwards; this function makes
    NO claim that the restored bytes are current, only that they arrived intact.
    """
    seed = default_seed_path()
    if not seed.is_file():
        return False
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp-seed")
    try:
        with lzma.open(seed, "rb") as src, open(tmp, "wb") as dst:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
        os.replace(tmp, target)
        logger.info("STM index restored from the baked seed at %s", seed.as_posix())
        return True
    except (lzma.LZMAError, OSError) as exc:
        logger.warning("STM baked-seed restore failed (%s); falling back to a build", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
