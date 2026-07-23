"""Re-bake the committed STM index seed (data/stm/index.sqlite.xz).

Run after any classifier/AF-schema/geometry rev bump, once the per-machine index
has been rebuilt with the new code:

    .venv/bin/python scripts/bake_stm_index.py

It refuses to bake an index the load gate would not accept (a stale or corrupt
file must never become the committed seed), compresses with xz (the multi-thread
CLI when available, stdlib lzma otherwise), and writes atomically. Commit the
refreshed artifact in the same change as the rev bump that invalidated it.
"""

from __future__ import annotations

import lzma
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.stm.db import StmIndex  # noqa: E402
from stockroom.stm.seed import default_seed_path  # noqa: E402
from stockroom.stm.source import default_index_path  # noqa: E402


def main() -> int:
    raw = default_index_path()
    idx = StmIndex.load(raw)
    if idx is None:
        print(
            f"REFUSED: no stamp-valid index at {raw.as_posix()} - rebuild it first "
            "(the seed must never carry stale or corrupt content).",
            file=sys.stderr,
        )
        return 1
    meta = idx.meta()
    idx.close()

    seed = default_seed_path()
    seed.parent.mkdir(parents=True, exist_ok=True)
    tmp = seed.with_name(seed.name + ".tmp-bake")
    xz = shutil.which("xz")
    if xz:
        with open(raw, "rb") as src, open(tmp, "wb") as dst:
            subprocess.run([xz, "-6", "-T0", "-c"], stdin=src, stdout=dst, check=True)
    else:
        with open(raw, "rb") as src, lzma.open(tmp, "wb", preset=6) as dst:
            shutil.copyfileobj(src, dst, 4 * 1024 * 1024)
    os.replace(tmp, seed)

    print(
        f"baked {seed.as_posix()} ({seed.stat().st_size / 1e6:.1f} MB from "
        f"{raw.stat().st_size / 1e6:.1f} MB) - classifier_rev {meta['classifier_rev']}, "
        f"af_schema_rev {meta['af_schema_rev']}, geometry_rev {meta['geometry_rev']}, "
        f"{meta['device_xml_count']} devices"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
