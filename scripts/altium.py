#!/usr/bin/env python3
"""Drive the real Altium Designer from WSL, safely and observably.

Why this exists
---------------
Stockroom's Altium 3D work (punch 16) has to run a DelphiScript inside Altium as a background job:
`Tools > Manage 3D Bodies for Library` has no file format we can write, so the only correct path is
to make Altium itself do it. Every experiment toward that costs an Altium boot (slow), takes the
ONE On-Demand license seat, and can leave a modal dialog sitting on the owner's desktop. Retyping
`powershell Get-Process X2` and hoping is not a workflow.

So this is the harness: one entry point that knows how to look, how to stop, and how to run a script
with a WATCHDOG instead of hanging forever.

The two facts that make it necessary, both measured 2026-07-25:

  1. **The license is a single On-Demand seat (1/1).** An Altium already open HOLDS it, so a headless
     run silently waits forever rather than failing. `status` reports that instead of leaving you to
     guess, and `stop` releases the seat gracefully (CloseMainWindow, not a kill, so the seat returns
     to Altium's pool cleanly).
  2. **A wrong ProcName does not error, it opens a "Select Item to Run" chooser** and waits for a
     human. Headless, that is indistinguishable from a slow boot. `run` watches for ANY window title
     appearing on a run that is supposed to be windowless, and reports it as a stuck dialog rather
     than burning the timeout.

Usage
-----
    uv run python scripts/altium.py status
    uv run python scripts/altium.py stop
    uv run python scripts/altium.py run --script /path/Probe.pas --proc Probe --marker /path/out.txt
    uv run python scripts/altium.py run --project /path/P.PrjScr --proc "Probe.pas>Probe" ...

Exit code is non-zero when the run did not do what it claimed, so this can gate.
No em dashes anywhere (standing owner rule).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

def _find_x2() -> Path | None:
    """The newest installed Altium `X2.EXE`, DISCOVERED rather than hardcoded.

    `AD26` is one version on one machine (owner's rule, 2026-07-25: build for the general case, not
    your machine). Every install root and both Program Files locations are globbed and the highest
    version wins; `ALTIUM_X2` overrides for an install somewhere unusual.
    """
    override = os.environ.get("ALTIUM_X2")
    if override:
        return Path(override)
    found: list[tuple[tuple[int, ...], Path]] = []
    for root in ("/mnt/c/Program Files/Altium", "/mnt/c/Program Files (x86)/Altium"):
        base = Path(root)
        if not base.is_dir():
            continue
        for child in base.iterdir():
            exe = child / "X2.EXE"
            if exe.exists():
                digits = "".join(ch for ch in child.name if ch.isdigit())
                found.append(((int(digits) if digits else 0,), exe))
    if not found:
        return None
    return sorted(found)[-1][1]


X2 = _find_x2() or Path("/mnt/c/Program Files/Altium/AD26/X2.EXE")


def _scratch_dir() -> Path:
    """A Windows-visible scratch dir for the generated .bat, taken from the real TEMP rather than a
    literal. Falls back only if TEMP cannot be read."""
    win_temp = _powershell("$env:TEMP").strip()
    if win_temp:
        out = subprocess.run(["wslpath", "-u", win_temp], capture_output=True, text=True)
        cand = Path(out.stdout.strip() or "")
        if cand and cand.is_dir():
            return cand
    return Path("/mnt/c/Windows/Temp")

_PS_LIST = (
    "Get-Process X2 -ErrorAction SilentlyContinue | "
    "ForEach-Object { \"$($_.Id)`t$($_.MainWindowTitle)\" }"
)

# Every VISIBLE top-level window title on the desktop. `MainWindowTitle` is not enough: measured
# 2026-07-25, Altium's "Select Item To Run" chooser is a child dialog, so the process reported an
# empty main title and the watchdog happily called a stuck modal "headless" and burned the full
# timeout. Enumerating windows is what actually sees a dialog.
_PS_WINDOWS = r"""
Add-Type @"
using System;using System.Text;using System.Runtime.InteropServices;
public class E {
 public delegate bool P(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(P f, IntPtr l);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
}
"@
$found = New-Object System.Collections.ArrayList
$cb = [E+P]{ param($h,$l)
  if ([E]::IsWindowVisible($h)) {
    $sb = New-Object System.Text.StringBuilder 512
    [void][E]::GetWindowText($h,$sb,512)
    if ($sb.Length -gt 0) { [void]$found.Add($sb.ToString()) }
  }
  return $true
}
[void][E]::EnumWindows($cb,[IntPtr]::Zero)
$found -join "`n"
"""


def window_titles() -> list[str]:
    return [w.strip() for w in _powershell(_PS_WINDOWS).splitlines() if w.strip()]


# Titles that mean Altium is WAITING FOR A HUMAN rather than working.
_DIALOG_HINTS = ("select item to run", "choose", "error", "license", "sign in", "confirm")


def _powershell(script: str, timeout: int = 120) -> str:
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.replace("\r", "")


def processes() -> list[tuple[int, str]]:
    """Every running Altium as (pid, main window title). An EMPTY title means it is headless, which
    is what a scripted run should look like the whole way through."""
    rows: list[tuple[int, str]] = []
    for line in _powershell(_PS_LIST).splitlines():
        if not line.strip():
            continue
        pid, _, title = line.partition("\t")
        try:
            rows.append((int(pid.strip()), title.strip()))
        except ValueError:
            continue
    return rows


def cmd_status(_args) -> int:
    print(f"Altium binary: {X2.as_posix()}" + ("" if X2.exists() else "   (NOT FOUND)"))
    procs = processes()
    if not procs:
        print("Altium: not running (the license seat is free)")
        return 0
    for pid, title in procs:
        where = title or "<no window: headless>"
        print(f"Altium: pid {pid}  {where}")
    # A single On-Demand seat means one visible Altium blocks every scripted run.
    if any(title for _pid, title in procs):
        print("NOTE: a windowed Altium holds the single On-Demand seat; a scripted run will WAIT "
              "for it forever. Run `altium.py stop` first.")
    return 0


def cmd_stop(args) -> int:
    """Close Altium gracefully so the On-Demand seat is released back to Altium's pool. Falls back to
    a kill only if it refuses, because a killed process can leave the seat checked out."""
    if not processes():
        print("Altium: already stopped")
        return 0
    _powershell(
        "Get-Process X2 -ErrorAction SilentlyContinue | ForEach-Object { "
        "  $_.CloseMainWindow() | Out-Null }"
    )
    for _ in range(args.timeout // 3):
        time.sleep(3)
        if not processes():
            print("Altium: stopped gracefully (seat released)")
            return 0
    print("Altium: did not close gracefully; forcing")
    _powershell("Get-Process X2 -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }")
    time.sleep(2)
    left = processes()
    print("Altium: stopped" if not left else f"Altium: STILL RUNNING {left}")
    return 0 if not left else 1


def _win_path(p: str) -> str:
    """A WSL path as Windows sees it; an already-Windows path passes through."""
    text = str(p)
    if len(text) > 1 and text[1] == ":":
        return text
    out = subprocess.run(["wslpath", "-w", text], capture_output=True, text=True)
    return out.stdout.strip() or text


_SHOT_PS = r"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.X, $b.Y, 0, 0, $bmp.Size)
$bmp.Save('__OUT__')
"SAVED $($b.Width)x$($b.Height)"
"""


def desktop_shot(out_win: str) -> str:
    """Capture the whole Windows desktop to `out_win` (a Windows path).

    Owner, 2026-07-25: "if its taking longer than u thought then take a look at the screen urself."
    A headless Altium that is secretly showing a modal is invisible to every process-level check that
    only reads window TITLES (a chooser owned by a hidden parent can report an empty title), so the
    honest fallback is to LOOK. This is the same .NET CopyFromScreen path that successfully captured
    the License Management window, so it works on this desktop.
    """
    return _powershell(_SHOT_PS.replace("__OUT__", out_win)).strip()


def cmd_shot(args) -> int:
    print(desktop_shot(_win_path(args.out)) or "capture failed")
    return 0


def cmd_run(args) -> int:
    if not X2.exists():
        print(f"Altium not found at {X2.as_posix()}", file=sys.stderr)
        return 2
    busy = [t for _p, t in processes() if t]
    if busy and not args.allow_busy:
        print(f"REFUSING: a windowed Altium is holding the single license seat ({busy[0]!r}). "
              "Run `altium.py stop` first, or pass --allow-busy.", file=sys.stderr)
        return 3

    marker = Path(args.marker) if args.marker else None
    if marker and marker.exists():
        marker.unlink()

    if args.project:
        target = f'ProjectName="{_win_path(args.project)}"'
    else:
        target = f'FileName="{_win_path(args.script)}"'
    invocation = f"-RScriptingSystem:RunScript({target}|ProcName=\"{args.proc}\")"
    print(f"running: {invocation}")
    # Route through a generated .bat, NEVER a direct spawn from WSL.
    #
    # Measured 2026-07-25, from Altium's own error dialog: a direct
    # `subprocess.Popen([X2, '-RScriptingSystem:RunScript(ProjectName="C:\srprobe\Probe.PrjScr"|...)'])`
    # arrives inside Altium as `Project name '\C:\srprobe\Probe.PrjScr\'` -- WSL's Windows-interop
    # argv translation escapes the embedded double quotes as \", so every quoted value gains stray
    # backslashes and Altium cannot find the script. cmd.exe re-parses the line and hands Altium the
    # value it was actually given, so the .bat is the fix, not a workaround. `^|` is cmd's escape for
    # the parameter separator; a bare `|` would be read as a pipe.
    #
    # A native-Windows caller does not have this problem (CreateProcess has no `|` and does not
    # re-escape quotes), so this is specifically about crossing the WSL boundary.
    bat_file = _scratch_dir() / "sr-altium-run.bat"
    bat_file.write_text(
        "@echo off\r\n"
        f'"{_win_path(str(X2))}" {invocation.replace("|", "^|")}\r\n',
        encoding="utf-8",
    )
    proc = subprocess.Popen(["cmd.exe", "/c", _win_path(str(bat_file))],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + args.timeout
    shot_taken = False
    while time.time() < deadline:
        if marker and marker.exists():
            print(f"OK: {marker.name} written after {int(args.timeout - (deadline - time.time()))}s")
            print(marker.read_text(encoding="utf-8", errors="replace").strip())
            if args.stop_after:
                cmd_stop(argparse.Namespace(timeout=60))
            return 0
        if proc.poll() is not None and not (marker and marker.exists()):
            print(f"Altium exited (code {proc.returncode}) without writing the marker")
            return 1
        # A window appearing on a run that should be headless means Altium is ASKING a human
        # something. The "Select Item to Run" chooser is what an unresolvable ProcName produces, and
        # it is silent: without this check the run just burns the whole timeout looking like a slow
        # boot.
        waited = int(args.timeout - (deadline - time.time()))
        if args.shot_after and waited >= args.shot_after and not shot_taken:
            shot_taken = True
            print(f"  slow ({waited}s): capturing the desktop to {args.shot_after_path}")
            print("  " + (desktop_shot(_win_path(args.shot_after_path)) or "capture failed"))
        titled = [t for _p, t in processes() if t]
        titled += [w for w in window_titles()
                   if any(h in w.lower() for h in _DIALOG_HINTS)]
        if titled:
            print(f"STUCK: Altium opened a dialog and is waiting for a human: {titled[0]!r}")
            print("       A blank 'Select Item to Run' means the ProcName did not resolve.")
            if args.stop_after:
                cmd_stop(argparse.Namespace(timeout=30))
            return 4
        time.sleep(5)

    print(f"TIMEOUT after {args.timeout}s with no marker and no dialog")
    if args.stop_after:
        cmd_stop(argparse.Namespace(timeout=30))
    return 5


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
    run.add_argument("--timeout", type=int, default=120,
                 help="hard ceiling. Altium boots in ~60-75s; a doomed run is ended sooner by the dialog check, so this is a backstop, not the normal wait")
    run.add_argument("--stop-after", action="store_true", help="close Altium when done")
    run.add_argument("--allow-busy", action="store_true",
                     help="run even though another Altium holds the seat (it will wait)")
    run.add_argument("--shot-after", type=int, default=60, metavar="SECONDS",
                     help="capture the desktop once the run has taken this long (0 disables)")
    run.add_argument("--shot-after-path", default="/tmp/altium-slow.png")

    shot = sub.add_parser("shot", help="capture the Windows desktop right now")
    shot.add_argument("--out", default="/tmp/altium-desktop.png")

    args = ap.parse_args()
    if args.cmd == "run" and not (args.script or args.project):
        ap.error("run needs --script or --project")
    return {"status": cmd_status, "stop": cmd_stop, "run": cmd_run,
            "shot": cmd_shot}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
