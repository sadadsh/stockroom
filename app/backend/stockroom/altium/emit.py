"""CLI: regenerate the Altium DbLib + data source over the active profile's library.

Usage: python -m stockroom.altium.emit

Reuses the app's real context bootstrap (the same one the API server uses), so it runs
against the configured libraries_root + active profile."""
from __future__ import annotations

import sys


def main() -> int:
    from stockroom.api.serve import build_context

    ctx = build_context()
    result = ctx.ops.regenerate_altium_dblib()
    print(f"Emitted {result['emitted']} place-ready parts -> {result['dblib']}")
    if result["skipped"]:
        print(f"Skipped {len(result['skipped'])} not place-ready: {', '.join(result['skipped'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
