#!/usr/bin/env python3
"""Drive a REAL Windows GUI from WSL: move a window, capture it even when covered, click it.

A thin CLI over `scripts/wingui.ps1`, which holds the implementation. This exists because
`windesk.py` drives Stockroom's own window through CDP dev-ids, and no third-party program has
those. Verifying that Altium actually lists a generated library needs a real pointer on a real
control, and nothing in the toolkit could do that.

    uv run python scripts/wingui.py list
    uv run python scripts/wingui.py move --title "Altium Designer" --monitor 2
    uv run python scripts/wingui.py shotwin --title "Altium Designer" --out /tmp/alt.png
    uv run python scripts/wingui.py click --x 2556 --y 988 --out /tmp/after.png

**Coordinates are SCREENSHOT pixels**, not screen coordinates. A multi-monitor desktop can have a
negative origin (measured on this machine: `VirtualScreen.X = -1920`), so passing a raw shot pixel
drove the pointer off every display and clicked nothing while reporting success. The PowerShell
converts; this CLI just passes them through.

**`click` moves the ONE shared pointer.** If somebody is using the machine, that yanks their cursor.
`shotwin` and `move` do not touch it, so prefer those when the desktop is in use.

No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PS1 = HERE / "wingui.ps1"

# Actions that need no target window, so `--title` is not required for them.
_DESKTOP_ACTIONS = {"desktopshot", "click", "movepointer", "type", "key"}


def to_windows_path(path: str) -> str:
    """`wslpath -w`, or the string unchanged when it is already a Windows path."""
    text = str(path)
    if len(text) > 1 and text[1] == ":":
        return text
    out = subprocess.run(["wslpath", "-w", text], capture_output=True, text=True)
    return out.stdout.strip() or text


def parse_screens(listing: str) -> list[dict[str, int]]:
    """The `SCREEN ... {X=..,Y=..,Width=..,Height=..}` lines as bounds dicts, in order.

    Parsed rather than assumed, because this machine's second display starts at x = -1920 and any
    code that hardcodes a monitor origin is wrong on the next machine.
    """
    out: list[dict[str, int]] = []
    for line in listing.splitlines():
        if not line.startswith("SCREEN") or "{" not in line or "}" not in line:
            continue
        body = line[line.index("{") + 1 : line.index("}")]
        try:
            out.append({k: int(v) for k, v in (part.split("=", 1) for part in body.split(","))})
        except ValueError:
            continue
    return out


def run(action: str, **kw) -> subprocess.CompletedProcess:
    """Invoke the PowerShell. Runs from a NON-UNC working directory: a Windows process started
    with a `\\\\wsl.localhost\\...` cwd prints "UNC paths are not supported" and silently falls back
    to the Windows directory, which has broken relative paths here before."""
    argv = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", to_windows_path(str(PS1)), "-Action", action,
    ]
    for key, value in kw.items():
        if value is None or value == "":
            continue
        argv += [f"-{key}", str(value)]
    return subprocess.run(argv, capture_output=True, text=True, cwd="/mnt/c")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "action",
        choices=sorted(
            {"list", "move", "probe", "shotwin", "mclick", "foreground"} | _DESKTOP_ACTIONS
        ),
    )
    ap.add_argument("--title", default="Altium Designer", help="window title substring")
    ap.add_argument("--x", type=int, default=0, help="SHOT pixel x (not a screen coordinate)")
    ap.add_argument("--y", type=int, default=0, help="SHOT pixel y")
    ap.add_argument("--w", type=int, default=1920)
    ap.add_argument("--h", type=int, default=1040)
    ap.add_argument("--monitor", type=int, default=0, help="move: 1-based display index")
    ap.add_argument("--out", default="", help="where to write a capture")
    ap.add_argument("--text", default="", help="type/key: what to send")
    a = ap.parse_args(argv)

    kw: dict = {"Title": a.title, "X": a.x, "Y": a.y, "W": a.w, "H": a.h, "Text": a.text}
    if a.out:
        kw["Shot"] = to_windows_path(a.out)
    if a.action == "move" and a.monitor:
        # Resolve the display index to its origin, so a caller never has to know that this
        # machine's second monitor starts at x = -1920.
        screens = parse_screens(run("list").stdout)
        if a.monitor > len(screens):
            print(f"FAILED: monitor {a.monitor} does not exist; found {len(screens)}")
            return 2
        b = screens[a.monitor - 1]
        kw["X"], kw["Y"] = b["X"], b["Y"]
        # Leave room for the taskbar rather than covering it.
        kw["W"], kw["H"] = b["Width"], b["Height"] - 40

    proc = run(a.action, **kw)
    sys.stdout.write(proc.stdout)
    if proc.returncode:
        sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
