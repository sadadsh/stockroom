"""Frozen entry point for Stockroom's stable managed Windows runtime.

Normal launch starts the signed broker, managed service authority, API, and
window host.  The same immutable executable is copied into each release set;
``--port`` dispatches that copy as a windowless candidate worker, while the
strict ``--window-host`` form starts a release-owned isolated WebView shell.
"""

from __future__ import annotations

import ctypes
import os
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


def _prepare_runtime(*, needs_window: bool) -> None:
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    mingit = bundle / "mingit"
    git = mingit / "cmd" / "git.exe"
    if git.is_file():
        os.environ["PATH"] = os.pathsep.join(
            (
                str(mingit / "cmd"),
                str(mingit / "bin"),
                str(mingit),
                os.environ.get("PATH", ""),
            )
        )
    if needs_window:
        from stockroom.launcher.launch import ensure_webview2

        ensure_webview2()


def _dispatch() -> None:
    arguments = sys.argv[1:]
    if any(argument.startswith("--window-host") for argument in arguments):
        from stockroom.host.window_process import (
            parse_window_host_arguments,
            run_window_host,
        )

        parsed = parse_window_host_arguments(arguments)
        _prepare_runtime(needs_window=True)
        run_window_host(parsed)
        return
    if "--port" in arguments:
        _prepare_runtime(needs_window=False)
        from stockroom.host.worker import main as worker_main

        worker_main()
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--managed-host-probe":
        _prepare_runtime(needs_window=False)
        from stockroom.host.package_probe import run_managed_host_probe

        run_managed_host_probe(Path(sys.argv[2]))
        return
    if any(argument.startswith("--managed-host-probe") for argument in sys.argv[1:]):
        raise SystemExit("--managed-host-probe requires exactly one absolute receipt path")
    _prepare_runtime(needs_window=True)
    from stockroom.host.run import main as host_main

    host_main()


def _main() -> None:
    # Both acceptance probes and immutable ``--port`` workers are unattended
    # subprocesses. A top-level worker failure must reach the broker through its
    # exit code/stderr, never block forever behind a user32 MessageBox.
    noninteractive = (
        "--managed-host-probe" in sys.argv[1:]
        or "--port" in sys.argv[1:]
        or any(argument.startswith("--window-host") for argument in sys.argv[1:])
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
