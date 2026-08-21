"""Fast project descriptor discovery through the Windows Search index."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_QUERY = r"""
$connection = New-Object System.Data.OleDb.OleDbConnection 'Provider=Search.CollatorDSO;Extended Properties="Application=Windows";'
$connection.Open()
try {
  $command = $connection.CreateCommand()
  $command.CommandText = "SELECT TOP 500 System.ItemPathDisplay FROM SYSTEMINDEX WHERE SCOPE='file:' AND (System.FileExtension='.kicad_pro' OR System.FileExtension='.PrjPcb')"
  $reader = $command.ExecuteReader()
  $paths = @()
  while ($reader.Read()) { $paths += [string]$reader.GetValue(0) }
  ConvertTo-Json -InputObject @($paths) -Compress
} finally {
  $connection.Close()
}
""".strip()


@dataclass(frozen=True, slots=True)
class IndexedProjectSearch:
    status: str
    detail: str
    paths: tuple[Path, ...]


def search_project_descriptors(
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    platform: str = sys.platform,
) -> IndexedProjectSearch:
    if platform != "win32":
        return IndexedProjectSearch(
            "unavailable",
            "Windows Search project discovery is available only on Windows.",
            (),
        )
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        _QUERY,
    ]
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return IndexedProjectSearch(
            "unavailable",
            "Windows Search could not list projects. Use Add Location instead.",
            (),
        )
    if completed.returncode != 0:
        return IndexedProjectSearch(
            "unavailable",
            "Windows Search could not list projects. Use Add Location instead.",
            (),
        )
    try:
        value = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        value = []
    raw: Sequence[object] = value if isinstance(value, list) else [value]
    found: dict[str, Path] = {}
    for item in raw:
        if not isinstance(item, str):
            continue
        path = Path(item)
        if path.suffix.casefold() not in {".kicad_pro", ".prjpcb"}:
            continue
        parts = {part.casefold() for part in path.parts}
        if "$recycle.bin" in parts:
            continue
        found.setdefault(str(path).casefold(), path)
    paths = tuple(sorted(found.values(), key=lambda path: str(path).casefold()))
    return IndexedProjectSearch(
        "ready",
        f"Windows Search found {len(paths)} project descriptor(s).",
        paths,
    )


__all__ = ["IndexedProjectSearch", "search_project_descriptors"]
