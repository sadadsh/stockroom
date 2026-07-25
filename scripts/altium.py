#!/usr/bin/env python3
"""Drive the real Altium Designer from the command line, safely and observably.

This is a thin CLI over `stockroom.altium.driver`, which holds the whole implementation:
version discovery, the license-seat check, the generated `.bat` that survives the WSL argv
boundary, and the watchdog that watches for a marker file and for a modal dialog instead of
waiting out a clock.

It is deliberately thin. The logic used to live here AND be needed by the backend, and two
copies of a hard-won workaround is how a workaround silently rots: the backend needs the same
invocation to embed a 3D body into a `.PcbLib`, so there is now exactly one implementation and
this file is its command line.

Usage
-----
    uv run python scripts/altium.py status
    uv run python scripts/altium.py stop
    uv run python scripts/altium.py run --script /path/Probe.pas --proc Probe --marker /path/out.txt
    uv run python scripts/altium.py run --project /path/P.PrjScr --proc "Probe.pas>Probe" --marker ...
    uv run python scripts/altium.py shot --out /tmp/desktop.png

Exit code is non-zero when the run did not do what it claimed, so this can gate.
No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

from stockroom.altium.driver import AltiumDriver  # noqa: E402

# Exit codes, one per outcome, so a caller can tell a held license seat from a stuck dialog.
_EXIT = {"ok": 0, "exited": 1, "not-installed": 2, "busy": 3, "dialog": 4, "timeout": 5}

_SHOT_PS = r"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
$bmp.Save('__OUT__')
"SAVED $($b.Width)x$($b.Height)"
"""


def cmd_status(drv: AltiumDriver, _args) -> int:
    where = drv.x2.as_posix() if drv.x2 else "NOT FOUND"
    print(f"Altium binary: {where}" + ("" if drv.installed else "   (NOT FOUND)"))
    procs = drv.processes()
    if not procs:
        print("Altium: not running (the license seat is free)")
        return 0
    for pid, title in procs:
        print(f"Altium: pid {pid}  {title or '<no window: headless>'}")
    if any(title for _pid, title in procs):
        print(
            "NOTE: a windowed Altium holds the license seat; a scripted run will WAIT for it "
            "forever. Run `altium.py stop` first."
        )
    return 0


def cmd_stop(drv: AltiumDriver, args) -> int:
    if not drv.processes():
        print("Altium: already stopped")
        return 0
    ok = drv.stop(timeout=args.timeout)
    print("Altium: stopped (seat released)" if ok else "Altium: STILL RUNNING")
    return 0 if ok else 1


def cmd_run(drv: AltiumDriver, args) -> int:
    outcome = drv.run_script(
        proc=args.proc,
        marker=Path(args.marker) if args.marker else Path("/dev/null"),
        project=Path(args.project) if args.project else None,
        script=Path(args.script) if args.script else None,
        timeout=args.timeout,
        allow_busy=args.allow_busy,
        stop_after=args.stop_after,
    )
    print(f"{outcome.status}: {outcome.detail}")
    if outcome.marker_text:
        print(outcome.marker_text)
    return _EXIT.get(outcome.status, 1)


def cmd_shot(drv: AltiumDriver, args) -> int:
    """Capture the whole Windows desktop.

    Owner, 2026-07-25: "if its taking longer than u thought then take a look at the screen
    urself." A headless Altium secretly showing a modal is invisible to any check that only reads
    window titles, so the honest fallback is to LOOK.
    """
    out = drv.host.to_windows_path(args.out)
    print(drv.host.powershell(_SHOT_PS.replace("__OUT__", out)).strip() or "capture failed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="is Altium running, and is it holding the license seat")

    stop = sub.add_parser("stop", help="close Altium gracefully so the license seat is released")
    stop.add_argument("--timeout", type=int, default=60)

    run = sub.add_parser("run", help="run a DelphiScript inside Altium, with a watchdog")
    run.add_argument("--script", help="path to the .pas to run (standalone form)")
    run.add_argument("--project", help="path to a .PrjScr instead of a bare script")
    run.add_argument("--proc", required=True, help='procedure, e.g. "Probe" or "Probe.pas>Probe"')
    run.add_argument("--marker", help="file the script writes on success; the proof it really ran")
    run.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="hard ceiling. A doomed run is ended sooner by the dialog check, so this is a "
        "backstop, not the normal wait",
    )
    run.add_argument("--stop-after", action="store_true", help="close Altium when done")
    run.add_argument(
        "--allow-busy",
        action="store_true",
        help="run even though another Altium holds the seat (it will wait)",
    )

    shot = sub.add_parser("shot", help="capture the Windows desktop right now")
    shot.add_argument("--out", default="/tmp/altium-desktop.png")

    args = ap.parse_args()
    if args.cmd == "run" and not (args.script or args.project):
        ap.error("run needs --script or --project")
    drv = AltiumDriver()
    return {"status": cmd_status, "stop": cmd_stop, "run": cmd_run, "shot": cmd_shot}[args.cmd](
        drv, args
    )


if __name__ == "__main__":
    raise SystemExit(main())
