"""Drive the installed Altium Designer from Stockroom, observably and with a watchdog.

Some things only Altium can do to its own formats. A 3D body lives INSIDE the footprint's
`.PcbLib` (an OLE2 binary nothing outside Altium can author safely), so the only correct way
to embed one is to make Altium do it. This module is that seam: discover the binary, run a
generated DelphiScript, and report what actually happened.

Qt-free and dependency-free, so the API layer may import it. It reaches Windows through
`powershell.exe` / `cmd.exe`, which works both natively and from WSL.

Three facts shape the design, all measured 2026-07-25 and each one a bug that cost real time:

1. **A timeout is a backstop, never a detector.** Every run names a SUCCESS signal (a marker
   file the script itself writes) and a FAILURE signal (the process exited, or a window
   appeared). Both are polled, so a run ends the moment it is decided instead of at the
   ceiling. Hitting the ceiling is treated as a defect in the observation.
2. **A wrong ProcName does not error, it opens a "Select Item To Run" chooser** and waits
   forever for a human. Worse, that chooser is a CHILD window, so the process reports an empty
   main-window title and looks headless. Only enumerating every visible window sees it.
3. **The license can be a single On-Demand seat.** An Altium already open HOLDS it, so a
   scripted run waits silently rather than failing. That is reported, not waited out.

Crossing the WSL boundary needs one specific workaround, scoped to that boundary: WSL's
argv translation escapes the embedded quotes in `RunScript(...)` as `\"`, so Altium receives
`\\C:\\path\\` and cannot find the script. Routing through a generated `.bat` makes cmd.exe
re-parse the line correctly. A native Windows caller does not have this problem.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Where an Altium install may live. Globbed and version-sorted rather than hardcoded: `AD26` is
# one version on one machine, and a peer running Stockroom will have a different one.
_INSTALL_ROOTS = (
    "/mnt/c/Program Files/Altium",
    "/mnt/c/Program Files (x86)/Altium",
    "C:/Program Files/Altium",
    "C:/Program Files (x86)/Altium",
)

_PS_PROCESSES = (
    "Get-Process X2 -ErrorAction SilentlyContinue | "
    'ForEach-Object { "$($_.Id)`t$($_.MainWindowTitle)" }'
)

# Every VISIBLE Altium-owned top-level window title, not just each process's main title. See fact 2
# above: a modal owned by a hidden parent is invisible to `MainWindowTitle`, and that is precisely
# the failure that made a doomed run look like a slow boot. The owner-PID filter is essential:
# unrelated applications can have titles such as "Please purchase WinRAR license", and classifying
# every desktop window as Altium would abort a healthy run.
_PS_WINDOWS = r"""
Add-Type @"
using System;using System.Text;using System.Collections.Generic;using System.Runtime.InteropServices;
public class E {
 public delegate bool P(IntPtr h, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(P f, IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, P f, IntPtr l);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
 static void AddText(List<string> found, IntPtr h) {
   StringBuilder s = new StringBuilder(2048);
   GetWindowText(h, s, s.Capacity);
   string text = s.ToString().Replace("\r", " ").Replace("\n", " ").Trim();
   if (text.Length > 0 && !found.Contains(text)) found.Add(text);
 }
 public static string WindowTextTree(IntPtr h) {
   List<string> found = new List<string>();
   AddText(found, h);
   P child = delegate(IntPtr c, IntPtr l) { AddText(found, c); return true; };
   EnumChildWindows(h, child, IntPtr.Zero);
   return String.Join(" | ", found.ToArray());
 }
}
"@
$x2Ids = @(Get-Process X2 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$found = New-Object System.Collections.ArrayList
$cb = [E+P]{ param($h,$l)
  [uint32]$ownerPid = 0
  [void][E]::GetWindowThreadProcessId($h,[ref]$ownerPid)
  if (($x2Ids -contains [int]$ownerPid) -and [E]::IsWindowVisible($h)) {
    $text = [E]::WindowTextTree($h)
    if ($text.Length -gt 0) { [void]$found.Add($text) }
  }
  return $true
}
[void][E]::EnumWindows($cb,[IntPtr]::Zero)
$found -join "`n"
"""

# How many extra polls to give the marker after Altium's process is seen gone. See `run_script`:
# the marker is written just before the exit, and this process observes it across a filesystem
# translation layer, so the two can be seen out of order.
_EXIT_GRACE_POLLS = 3

# Window titles that mean Altium is WAITING FOR A HUMAN rather than working.
DIALOG_HINTS = (
    "select item to run",
    "error",
    "license",
    "sign in",
    "confirm",
)


class Process(Protocol):
    """The part of a spawned process this module uses."""

    returncode: int | None

    def poll(self) -> int | None: ...


class Host(Protocol):
    """Everything the driver needs from the operating system, as ONE injectable seam.

    Tests substitute a fake so the whole watchdog (marker appears, process dies, a dialog
    opens, the ceiling is hit) is exercised without an Altium install or a real clock. Without
    this the watchdog could only be tested by letting it happen, which the owner's rule calls a
    design defect.
    """

    def powershell(self, script: str, timeout: int = 120) -> str: ...
    def spawn(self, argv: list[str]) -> Process: ...
    def sleep(self, seconds: float) -> None: ...
    def monotonic(self) -> float: ...
    def to_windows_path(self, path: str) -> str: ...
    def windows_temp(self) -> Path: ...


class RealHost:
    """The production Host: real PowerShell, real cmd.exe, real clock."""

    def powershell(self, script: str, timeout: int = 120) -> str:
        try:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out.stdout.replace("\r", "")

    def spawn(self, argv: list[str]) -> Process:
        return subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def monotonic(self) -> float:
        return time.monotonic()

    def to_windows_path(self, path: str) -> str:
        """A path as Windows sees it. An already-Windows path passes through untouched, so a
        caller may hand over either form."""
        text = str(path)
        if len(text) > 1 and text[1] == ":":
            return text
        try:
            out = subprocess.run(
                ["wslpath", "-w", text],
                capture_output=True,
                text=True,
                creationflags=_NO_WINDOW,
            )
        except OSError:
            return text
        return out.stdout.strip() or text

    def windows_temp(self) -> Path:
        """The real Windows TEMP as a path this process can write, read from the environment
        rather than assumed. One machine's `C:\\Users\\<name>\\AppData\\Local\\Temp` is not
        another's."""
        raw = self.powershell("$env:TEMP").strip()
        if raw:
            try:
                out = subprocess.run(
                    ["wslpath", "-u", raw],
                    capture_output=True,
                    text=True,
                    creationflags=_NO_WINDOW,
                )
                cand = Path(out.stdout.strip() or raw)
            except OSError:
                cand = Path(raw)
            if cand.is_dir():
                return cand
        for fallback in (Path("/mnt/c/Windows/Temp"), Path("C:/Windows/Temp")):
            if fallback.is_dir():
                return fallback
        return Path(os.environ.get("TMPDIR", "/tmp"))


@dataclass(frozen=True)
class RunOutcome:
    """What a scripted run actually did. `status` is a machine-readable verdict, never inferred
    from elapsed time."""

    status: str  # ok | not-installed | busy | dialog | exited | timeout
    detail: str
    marker_text: str = ""
    seconds: float = 0.0
    titles: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class AltiumDriver:
    """Run DelphiScripts inside the installed Altium.

    `x2` is normally DISCOVERED. Pass it explicitly (or set `ALTIUM_X2`) for an install
    somewhere unusual; that is the documented override rather than a literal in a function.
    """

    def __init__(
        self,
        host: Host | None = None,
        x2: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.host: Host = host or RealHost()
        environ = env if env is not None else dict(os.environ)
        self.x2 = x2 or find_x2(environ)

    @property
    def installed(self) -> bool:
        return self.x2 is not None and Path(self.x2).exists()

    def processes(self) -> list[tuple[int, str]]:
        """Every running Altium as (pid, main window title). An EMPTY title means headless,
        which is what a scripted run should look like the whole way through."""
        rows: list[tuple[int, str]] = []
        for line in self.host.powershell(_PS_PROCESSES).splitlines():
            if not line.strip():
                continue
            pid, _, title = line.partition("\t")
            try:
                rows.append((int(pid.strip()), title.strip()))
            except ValueError:
                continue
        return rows

    def window_titles(self) -> list[str]:
        return [w.strip() for w in self.host.powershell(_PS_WINDOWS).splitlines() if w.strip()]

    def busy_titles(self) -> list[str]:
        """Titles of any WINDOWED Altium. A windowed instance holds the license seat, so a
        scripted run would wait for it forever."""
        return [t for _pid, t in self.processes() if t]

    def stop(self, timeout: int = 60) -> bool:
        """Close Altium gracefully so the license seat returns to Altium's pool. Falls back to a
        kill only if it refuses, because a killed process can leave the seat checked out."""
        if not self.processes():
            return True
        self.host.powershell(
            "Get-Process X2 -ErrorAction SilentlyContinue | "
            "ForEach-Object { $_.CloseMainWindow() | Out-Null }"
        )
        for _ in range(max(1, timeout // 3)):
            self.host.sleep(3)
            if not self.processes():
                return True
        self.host.powershell(
            "Get-Process X2 -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }"
        )
        self.host.sleep(2)
        return not self.processes()

    def run_script(
        self,
        *,
        proc: str,
        marker: Path,
        project: Path | None = None,
        script: Path | None = None,
        timeout: int = 180,
        allow_busy: bool = False,
        stop_after: bool = True,
        poll_seconds: float = 2.0,
    ) -> RunOutcome:
        """Run `proc` inside Altium and wait for `marker` to appear.

        The script is responsible for writing `marker` on EVERY path, success or failure, so the
        caller never has to infer an outcome from how long it took.
        """
        if not (project or script):
            raise ValueError("run_script needs either a project or a script path")
        if not self.installed:
            return RunOutcome(
                "not-installed",
                "Altium Designer was not found on this machine. Install it, or set ALTIUM_X2 "
                "to the full path of X2.EXE.",
            )
        busy = self.busy_titles()
        if busy and not allow_busy:
            return RunOutcome(
                "busy",
                f"A windowed Altium is open ({busy[0]!r}) and holds the license seat, so a "
                "scripted run would wait for it forever. Close Altium and try again.",
                titles=tuple(busy),
            )

        marker = Path(marker)
        marker.unlink(missing_ok=True)
        proc_name = proc
        if script is not None:
            # AD26 currently opens a generic Error dialog for FileName= standalone-script
            # invocations even when the identical source runs through a PrjScr. Stage an isolated
            # one-document project so every public driver path uses the working invocation form.
            # The unique directory also prevents one worker from changing another worker's script.
            project_root = Path(
                tempfile.mkdtemp(
                    prefix="stockroom-altium-script-",
                    dir=str(self.host.windows_temp()),
                )
            )
            staged_script = project_root / "StockroomScript.pas"
            shutil.copy2(Path(script), staged_script)
            staged_project = project_root / "StockroomScript.PrjScr"
            staged_project.write_text(
                "[Design]\r\n"
                "Version=1.0\r\n"
                "HierarchyMode=0\r\n"
                "[Document1]\r\n"
                "DocumentPath=StockroomScript.pas\r\n",
                encoding="utf-8",
                newline="",
            )
            project = staged_project
            proc_name = f"{staged_script.name}>{proc.rsplit('>', 1)[-1]}"

        assert project is not None
        target = f'ProjectName="{self.host.to_windows_path(str(project))}"'
        invocation = f'-RScriptingSystem:RunScript({target}|ProcName="{proc_name}")'

        # Route through a generated .bat, never a direct spawn. See the module docstring: WSL's
        # argv translation corrupts every quoted value. `^|` is cmd's escape for the parameter
        # separator, since a bare `|` would be read as a pipe.
        # A fixed launcher name is a cross-run race. Two independent Stockroom workers can
        # legitimately need Altium at nearly the same time; if both rewrite one .bat, the first
        # cmd.exe can execute the second worker's script. Keep the launcher unique and immutable
        # for the lifetime of this run.
        descriptor, bat_name = tempfile.mkstemp(
            prefix="stockroom-altium-run-",
            suffix=".bat",
            dir=str(self.host.windows_temp()),
        )
        os.close(descriptor)
        bat = Path(bat_name)
        bat.write_text(
            "@echo off\r\n"
            f'"{self.host.to_windows_path(str(self.x2))}" {invocation.replace("|", "^|")}\r\n',
            encoding="utf-8",
        )
        started = self.host.monotonic()
        proc_handle = self.host.spawn(["cmd.exe", "/c", self.host.to_windows_path(str(bat))])

        try:
            while True:
                elapsed = self.host.monotonic() - started
                if marker.exists():
                    return RunOutcome(
                        "ok",
                        f"{marker.name} written after {elapsed:.0f}s",
                        marker.read_text(encoding="utf-8", errors="replace").strip(),
                        elapsed,
                    )
                # A dialog means Altium is ASKING a human something and will never finish.
                #
                # Only a title MATCHING a known waiting-for-a-human pattern counts. A windowed
                # Altium on its own is not evidence: a script that opens a document calls
                # ShowDocument, so a window is exactly what a healthy run looks like. Treating any
                # title as a modal killed a run on 2026-07-25 whose script had already completed
                # and written its marker, reporting 'Home Page - Altium Designer Professional' as
                # a stuck dialog. The pre-run seat check still refuses a PRE-EXISTING windowed
                # Altium, which is a different question, and the timeout remains the backstop for a
                # hang with nothing on screen.
                candidates = self.window_titles() + [t for _pid, t in self.processes() if t]
                titles = [w for w in candidates if any(h in w.lower() for h in DIALOG_HINTS)]
                if titles:
                    return RunOutcome(
                        "dialog",
                        f"Altium is waiting for a human: {titles[0]!r}. A blank 'Select Item To "
                        "Run' means the procedure name did not resolve.",
                        seconds=elapsed,
                        titles=tuple(titles),
                    )
                if proc_handle.poll() is not None:
                    # A successful script writes the marker and THEN asks Altium to exit, so the
                    # two events are milliseconds apart and can be observed out of order: the
                    # marker lives on a Windows path this process reaches over a translation
                    # layer, and that layer is not instantaneous. Losing that race would report a
                    # completed embed as a crash, so the exit gets a short grace window in which
                    # the marker may still appear. It is bounded, and it never masks a real
                    # failure: a script that truly did not write one still fails, just later.
                    for _ in range(_EXIT_GRACE_POLLS):
                        if marker.exists():
                            break
                        self.host.sleep(poll_seconds)
                    if marker.exists():
                        continue
                    return RunOutcome(
                        "exited",
                        f"Altium exited (code {proc_handle.returncode}) without writing "
                        f"{marker.name}, so the script did not run to completion.",
                        seconds=self.host.monotonic() - started,
                    )
                if elapsed >= timeout:
                    return RunOutcome(
                        "timeout",
                        f"No marker and no dialog after {timeout}s. This is a gap in the "
                        "observation, not a normal outcome.",
                        seconds=elapsed,
                    )
                self.host.sleep(poll_seconds)
        finally:
            if stop_after:
                self.stop(timeout=30)


def find_x2(env: dict[str, str] | None = None) -> Path | None:
    """The newest installed Altium `X2.EXE`, DISCOVERED rather than hardcoded.

    Every install root is globbed and the highest version wins, because `AD26` is one version
    on one machine. `ALTIUM_X2` overrides for an install somewhere unusual.
    """
    environ = env if env is not None else dict(os.environ)
    override = environ.get("ALTIUM_X2")
    if override:
        return Path(override)
    found: list[tuple[tuple[int, ...], Path]] = []
    for root in _INSTALL_ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            exe = child / "X2.EXE"
            if not exe.exists():
                continue
            digits = "".join(ch for ch in child.name if ch.isdigit())
            found.append(((int(digits) if digits else 0,), exe))
    if not found:
        return None
    return sorted(found)[-1][1]
