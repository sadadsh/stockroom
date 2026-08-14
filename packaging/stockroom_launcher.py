"""Frozen entry point for Stockroom's immutable packaged backend worker.

The native WPF host is the sole normal product entry. This module supports only
the manifest-bound ``--port`` worker and explicit packaging probes; it never
clones Git source, runs uv, provisions browsers, or opens a product window.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))


def _fatal(message: str, *, interactive: bool) -> None:
    if interactive:
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                message,
                "Stockroom could not start",
                0x10,
            )
            return
        except Exception:  # noqa: BLE001 - no user32: use the process error stream
            pass
    sys.stderr.write(message + "\n")


def _dispatch() -> None:
    arguments = sys.argv[1:]
    if "--port" in arguments:
        from stockroom.host.worker import main as worker_main

        worker_main()
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--managed-host-probe":
        from stockroom.host.package_probe import run_managed_host_probe

        run_managed_host_probe(Path(sys.argv[2]))
        return
    if any(argument.startswith("--managed-host-probe") for argument in sys.argv[1:]):
        raise SystemExit("--managed-host-probe requires exactly one absolute receipt path")
    raise SystemExit("the packaged worker has no interactive entry point")


def _main() -> None:
    # Both acceptance probes and immutable ``--port`` workers are unattended
    # subprocesses. A top-level worker failure must reach the broker through its
    # exit code/stderr, never block forever behind a user32 MessageBox.
    noninteractive = (
        "--managed-host-probe" in sys.argv[1:]
        or "--port" in sys.argv[1:]
    )
    try:
        _dispatch()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - native top-level failure boundary
        _fatal(
            "Stockroom's managed runtime could not start.\n\n" + str(exc),
            interactive=not noninteractive,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
