#!/usr/bin/env python3
"""Prove that the generated Altium `.DbLib` can actually reach its database.

Why this exists
---------------
On 2026-07-26 the `.DbLib` Stockroom had been emitting for months turned out not to work in real
Altium at all: it named its SQLite data source by a REPO-RELATIVE path, and the SQLite ODBC driver
resolves a relative `Database=` against the PROCESS working directory. Altium's working directory
is never the library folder, so Altium showed a red "Connection Failed" and the whole library was
unusable. Every test we had still passed, because they only checked the text we emitted.

The trap that let it survive: our earlier ADO probe happened to run with its working directory
INSIDE the library folder, where the relative path resolves fine. A verification that cannot
distinguish the failing case from the passing one is not a verification.

So this script opens the connection string EXACTLY as written in the `.DbLib`, from a working
directory deliberately chosen to be somewhere else - which is the only way to reproduce what
Altium does. It needs no Altium, no license seat, and no GUI: it takes about a second.

PRIOR ART evaluated, and why none of it answers this
----------------------------------------------------
- `stockroom/altium/odbc.py` (ours) probes whether the SQLite3 ODBC DRIVER is INSTALLED. Different
  question: it reported "Installed" throughout this entire bug. Complementary, not sufficient.
- `stockroom/altium/driver.py` + `scripts/altium.py` (ours) can launch real Altium and screenshot
  it, which is how the bug was FOUND. REJECTED as the gate: it takes a license seat, needs a
  desktop, costs ~20s per run, and the verdict would have to be read out of pixels.
- `pyodbc` / `sqlalchemy` REJECTED: they would reach the SQLite ODBC driver directly, bypassing the
  MSDASQL OLE DB bridge that Altium actually goes through, so they cannot reproduce Altium's chain.
- Python's stdlib `sqlite3` REJECTED for the same reason and worse: it resolves the path itself, so
  it is structurally incapable of observing an ODBC path-resolution failure. It would pass always.
- ADO (`ADODB.Connection`) over PowerShell COM is what is used here, because `Provider=MSDASQL.1`
  -> `DRIVER=SQLite3 ODBC Driver` is the exact provider chain named in the file Altium reads. The
  connection string is taken verbatim from the shipped `.DbLib`, never rebuilt from our emitter, or
  the probe would be testing our intent rather than the artifact.

Usage
-----
    py scripts\\altium_dblib_verify.py                      # the active profile's library
    py scripts\\altium_dblib_verify.py --dblib C:\\path\\X.DbLib
    py scripts\\altium_dblib_verify.py --json

Exit codes, one per outcome, so this can gate:
    0  connected, and the table answered
    1  the connection failed (the bug this exists to catch)
    2  the .DbLib could not be found or has no ConnectionString
    3  not runnable here (this is not Windows, so there is no ADO/ODBC to ask)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app" / "backend"))

# A directory that is certainly NOT the library folder. The whole point is to run from somewhere
# Altium might run from, so a path that only works "from next to the file" fails here as it should.
NEUTRAL_CWD = r"C:\Windows"

# The values are baked into a generated .ps1 as SINGLE-QUOTED here-strings rather than passed as
# arguments. A connection string contains embedded double quotes (`Extended Properties="..."`), and
# both WSL's argv translation and PowerShell's own parsing eat them - measured: passing it as an
# argument produced "Data source name not found", i.e. the DRIVER= clause never survived, and the
# probe then failed identically on a GOOD file and a BROKEN one. A check that cannot tell those
# apart is worse than no check, which is the same lesson this whole script exists to record.
_PROBE = """
$cs = @'
__CS__
'@
$cwd = @'
__CWD__
'@
$table = @'
__TABLE__
'@
Set-Location $cwd
# Set-Location moves PowerShell's location only. A native ODBC driver reads the PROCESS working
# directory, so without this line the probe silently tests a directory it was never pointed at.
[Environment]::CurrentDirectory = $cwd
$conn = New-Object -ComObject ADODB.Connection
try { $conn.Open($cs) } catch { "OPEN-FAIL`t" + $_.Exception.Message; exit }
try {
  $rs = $conn.Execute("SELECT COUNT(*) AS n FROM [$table]")
  "OK`t" + $rs.Fields.Item("n").Value
} catch { "QUERY-FAIL`t" + $_.Exception.Message }
$conn.Close()
"""


def connection_string(dblib: Path) -> str:
    """The ConnectionString exactly as Altium would read it, verbatim."""
    for raw in dblib.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("ConnectionString="):
            return raw.split("=", 1)[1].strip()
    return ""


def table_name(dblib: Path, default: str = "Parts") -> str:
    for raw in dblib.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("TableName="):
            return raw.split("=", 1)[1].strip() or default
    return default


def active_dblib() -> Path | None:
    """The active profile's .DbLib, through the app's own context bootstrap, so this script and
    the app can never disagree about which library is live."""
    try:
        from stockroom.api.serve import build_context

        ctx = build_context()
        return Path(ctx.profile.library.parts_dir).parent / "altium" / "Stockroom.DbLib"
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        print(f"could not resolve the active profile: {exc}", file=sys.stderr)
        return None


def probe(cs: str, table: str, cwd: str) -> tuple[str, str]:
    """Returns (verdict, detail) where verdict is OK / OPEN-FAIL / QUERY-FAIL / PROBE-ERROR."""
    # RealHost already knows how to find a Windows-visible temp directory and translate a path
    # across the WSL boundary; reused rather than re-derived, so there is one implementation of
    # that hard-won bit and this script works natively and from WSL alike.
    from stockroom.altium.driver import RealHost

    host = RealHost()
    script = (_PROBE.replace("__CS__", cs).replace("__CWD__", cwd).replace("__TABLE__", table))
    ps1 = host.windows_temp() / "stockroom-dblib-probe.ps1"
    ps1.write_text(script, encoding="utf-8", newline="\r\n")
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", host.to_windows_path(str(ps1))],
        capture_output=True, text=True, timeout=120,
    )
    line = next((ln for ln in out.stdout.splitlines() if "\t" in ln), "")
    if not line:
        return "PROBE-ERROR", (out.stderr or out.stdout).strip()[:400]
    verdict, _, detail = line.partition("\t")
    return verdict.strip(), detail.strip()


def on_windows() -> bool:
    """True when a Windows PowerShell is reachable - natively, or across the WSL boundary."""
    if os.name == "nt":
        return True
    try:
        return subprocess.run(["powershell.exe", "-NoProfile", "-Command", "exit 0"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dblib", help="the .DbLib to check (default: the active profile's)")
    ap.add_argument("--cwd", default=NEUTRAL_CWD,
                    help="working directory to open the connection from; the default is "
                         "deliberately NOT the library folder")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    path = Path(args.dblib) if args.dblib else active_dblib()
    if path is None or not path.exists():
        report = {"ok": False, "reason": "missing", "dblib": str(path) if path else None}
        print(json.dumps(report) if args.as_json
              else f"NOT FOUND: {path}\nRegenerate the Altium library, then run this again.")
        return 2

    cs = connection_string(path)
    if not cs:
        report = {"ok": False, "reason": "no-connection-string", "dblib": path.as_posix()}
        print(json.dumps(report) if args.as_json
              else f"NO ConnectionString in {path.as_posix()}")
        return 2

    if not on_windows():
        report = {"ok": None, "reason": "not-windows", "dblib": path.as_posix(),
                  "connection_string": cs}
        # Honest: this is NOT a pass. There is no ADO/ODBC here to ask, so nothing was proven.
        print(json.dumps(report) if args.as_json else
              "CANNOT VERIFY HERE: this needs Windows (ADO + the SQLite ODBC driver).\n"
              "Nothing was checked. Run it on the machine that runs Altium.\n"
              f"  connection string: {cs}")
        return 3

    table = table_name(path)
    verdict, detail = probe(cs, table, args.cwd)
    ok = verdict == "OK"
    report = {"ok": ok, "verdict": verdict, "detail": detail, "rows": detail if ok else None,
              "dblib": path.as_posix(), "table": table, "cwd": args.cwd}
    if args.as_json:
        print(json.dumps(report))
    elif ok:
        print(f"CONNECTED from {args.cwd}: {detail} row(s) in [{table}]  ({path.as_posix()})")
    else:
        print(f"FAILED from {args.cwd}: {verdict} {detail}\n"
              f"  dblib: {path.as_posix()}\n"
              f"  connection: {cs}\n"
              "This is what Altium sees. The usual cause is a RELATIVE Database= path: the SQLite\n"
              "ODBC driver resolves one against the process working directory, and Altium's is\n"
              "never the library folder. Regenerate the Altium library to rewrite it absolutely.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
