import json
import subprocess
from pathlib import Path

from stockroom.projects.windows_search import search_project_descriptors


def test_windows_search_returns_unique_indexed_descriptors_without_crawling():
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    r"C:\Designs\Amp\Amp.kicad_pro",
                    r"c:\designs\amp\Amp.kicad_pro",
                    r"D:\Boards\Power\Power.PrjPcb",
                    r"C:\$Recycle.Bin\old.kicad_pro",
                ]
            ),
            stderr="",
        )

    result = search_project_descriptors(runner=run, platform="win32")

    assert result.status == "ready"
    assert result.paths == (
        Path(r"C:\Designs\Amp\Amp.kicad_pro"),
        Path(r"D:\Boards\Power\Power.PrjPcb"),
    )
    command, options = calls[0]
    assert command[:4] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
    ]
    assert "Search.CollatorDSO" in command[-1]
    assert ".kicad_pro" in command[-1]
    assert ".PrjPcb" in command[-1]
    assert "Get-ChildItem" not in command[-1]
    assert options["timeout"] == 15


def test_windows_search_reports_unavailable_without_raising():
    result = search_project_descriptors(
        runner=lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 1, stdout="", stderr="service unavailable"
        ),
        platform="win32",
    )

    assert result.status == "unavailable"
    assert result.paths == ()
    assert "Windows Search" in result.detail


def test_windows_search_is_honest_off_windows():
    result = search_project_descriptors(platform="linux")

    assert result.status == "unavailable"
    assert result.paths == ()
