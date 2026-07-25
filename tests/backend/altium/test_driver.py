"""The Altium driver's watchdog, exercised WITHOUT an Altium install or a real clock.

The owner's rule: an automation that can only be tested by letting it fire is a design defect.
So `Host` is one injectable seam and every branch the watchdog can take (marker appears, a modal
opens, Altium dies, the ceiling is hit, the seat is held, nothing is installed) is driven here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from stockroom.altium.driver import AltiumDriver, RunOutcome, find_x2


class FakeProcess:
    def __init__(self, exits_after: int | None = None) -> None:
        self.returncode: int | None = None
        self._exits_after = exits_after
        self._polls = 0

    def poll(self) -> int | None:
        self._polls += 1
        if self._exits_after is not None and self._polls >= self._exits_after:
            self.returncode = 1
            return 1
        return None


class FakeHost:
    """A scripted Windows. `steps` is what happens on each poll cycle, so a test states the
    world's behaviour over time instead of patching a clock."""

    def __init__(
        self,
        tmp: Path,
        *,
        processes: str = "",
        windows: str = "",
        marker_after: int | None = None,
        marker_path: Path | None = None,
        marker_text: str = "DONE added=1 removed=0",
        process: FakeProcess | None = None,
    ) -> None:
        self.tmp = tmp
        self._processes = processes
        self._windows = windows
        self.marker_after = marker_after
        self.marker_path = marker_path
        self.marker_text = marker_text
        self.clock = 0.0
        self.cycles = 0
        self.spawned: list[list[str]] = []
        self.ps_calls: list[str] = []
        self.process = process or FakeProcess()

    def powershell(self, script: str, timeout: int = 120) -> str:
        self.ps_calls.append(script)
        if "EnumWindows" in script:
            return self._windows
        if "CloseMainWindow" in script or "Kill" in script:
            self._processes = ""
            return ""
        return self._processes

    def spawn(self, argv):
        self.spawned.append(argv)
        return self.process

    def sleep(self, seconds: float) -> None:
        self.clock += seconds
        self.cycles += 1
        if self.marker_after is not None and self.cycles >= self.marker_after and self.marker_path:
            self.marker_path.write_text(self.marker_text, encoding="utf-8")

    def monotonic(self) -> float:
        return self.clock

    def to_windows_path(self, path: str) -> str:
        return "C:\\fake" + str(path).replace("/", "\\")

    def windows_temp(self) -> Path:
        return self.tmp


@pytest.fixture
def x2(tmp_path: Path) -> Path:
    exe = tmp_path / "AD99" / "X2.EXE"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return exe


def _driver(tmp_path: Path, x2: Path, **kw) -> tuple[AltiumDriver, FakeHost, Path]:
    marker = tmp_path / "marker.txt"
    host = FakeHost(tmp_path, marker_path=marker, **kw)
    return AltiumDriver(host=host, x2=x2, env={}), host, marker


def test_a_marker_file_ends_the_wait_immediately(tmp_path: Path, x2: Path):
    drv, host, marker = _driver(tmp_path, x2, marker_after=2)
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=999)
    assert out.ok and out.status == "ok"
    assert out.marker_text == "DONE added=1 removed=0"
    # It returned on the SUCCESS signal, nowhere near the ceiling.
    assert out.seconds < 10


def test_a_visible_dialog_fails_fast_instead_of_burning_the_timeout(tmp_path: Path, x2: Path):
    # The real failure this encodes: a blank "Select Item To Run" chooser is a CHILD window, so
    # the process reports an empty main title and every process-level check calls it headless.
    drv, host, marker = _driver(tmp_path, x2, windows="Select Item To Run\n")
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=999)
    assert out.status == "dialog"
    assert "waiting for a human" in out.detail
    assert out.seconds < 10  # not the 999s ceiling


def test_altium_dying_without_a_marker_is_reported_as_an_exit(tmp_path: Path, x2: Path):
    drv, host, marker = _driver(tmp_path, x2, process=FakeProcess(exits_after=1))
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=999)
    assert out.status == "exited"
    assert "did not run to completion" in out.detail


def test_a_marker_written_just_before_the_process_exits_still_counts_as_success(
    tmp_path: Path, x2: Path
):
    # Altium exits ITSELF at the end of a successful script, so the exit check must never win a
    # race against the marker. Marker lands on the same cycle the process is seen gone.
    marker = tmp_path / "marker.txt"
    host = FakeHost(tmp_path, marker_path=marker, marker_after=1, process=FakeProcess(exits_after=1))
    drv = AltiumDriver(host=host, x2=x2, env={})
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=999)
    assert out.status == "ok"


def test_the_timeout_is_a_backstop_and_says_so(tmp_path: Path, x2: Path):
    drv, host, marker = _driver(tmp_path, x2)
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=10)
    assert out.status == "timeout"
    assert "gap in the observation" in out.detail


def test_a_windowed_altium_is_refused_because_it_holds_the_license_seat(tmp_path: Path, x2: Path):
    drv, host, marker = _driver(tmp_path, x2, processes="4242\tAltium Designer\n")
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr")
    assert out.status == "busy"
    assert "license seat" in out.detail
    assert not host.spawned  # refused BEFORE spending an Altium boot


def test_allow_busy_overrides_the_seat_check(tmp_path: Path, x2: Path):
    drv, host, marker = _driver(
        tmp_path, x2, processes="4242\tAltium Designer\n", marker_after=1
    )
    out = drv.run_script(
        proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", allow_busy=True, timeout=99
    )
    # It is no longer refused up front, and a plain windowed title is not mistaken for a modal, so
    # the run proceeds to its marker.
    assert host.spawned
    assert out.status == "ok"


def test_a_missing_altium_is_an_explained_refusal_not_a_crash(tmp_path: Path):
    host = FakeHost(tmp_path)
    drv = AltiumDriver(host=host, x2=tmp_path / "nope" / "X2.EXE", env={})
    out = drv.run_script(proc="P.pas>P", marker=tmp_path / "m.txt", project=tmp_path / "P.PrjScr")
    assert out.status == "not-installed"
    assert "ALTIUM_X2" in out.detail
    assert not host.spawned


def test_the_invocation_is_routed_through_a_bat_with_an_escaped_separator(tmp_path: Path, x2: Path):
    # WSL's argv translation escapes embedded quotes as \", so a direct spawn hands Altium
    # `\C:\path\` and it cannot find the script. cmd.exe re-parses the line correctly.
    drv, host, marker = _driver(tmp_path, x2, marker_after=1)
    drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=99)
    assert host.spawned[0][0] == "cmd.exe"
    bat = (tmp_path / "stockroom-altium-run.bat").read_text(encoding="utf-8")
    assert "-RScriptingSystem:RunScript(" in bat
    assert "^|ProcName=" in bat, "a bare | would be read by cmd as a pipe"
    assert 'ProcName="P.pas>P"' in bat
    # Read the BYTES: `read_text` decodes universal newlines, so it would report CRLF as LF and
    # this assertion would be testing nothing. cmd.exe needs the real CRLF.
    assert (tmp_path / "stockroom-altium-run.bat").read_bytes().endswith(b"\r\n")


def test_run_script_requires_a_target(tmp_path: Path, x2: Path):
    drv, _host, marker = _driver(tmp_path, x2)
    with pytest.raises(ValueError):
        drv.run_script(proc="P", marker=marker)


def test_a_stale_marker_from_a_previous_run_cannot_fake_success(tmp_path: Path, x2: Path):
    marker = tmp_path / "marker.txt"
    marker.write_text("DONE added=99 removed=0", encoding="utf-8")
    host = FakeHost(tmp_path, marker_path=marker)
    drv = AltiumDriver(host=host, x2=x2, env={})
    out = drv.run_script(proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=10)
    assert out.status == "timeout", "the old marker must be deleted before the run"


def test_find_x2_picks_the_newest_version_and_honours_the_override(tmp_path: Path, monkeypatch):
    roots = tmp_path / "Altium"
    for name in ("AD19", "AD26", "AD9"):
        (roots / name).mkdir(parents=True)
        (roots / name / "X2.EXE").write_bytes(b"MZ")
    monkeypatch.setattr("stockroom.altium.driver._INSTALL_ROOTS", (str(roots),))
    assert find_x2(env={}) == roots / "AD26" / "X2.EXE"
    assert find_x2(env={"ALTIUM_X2": "/custom/X2.EXE"}) == Path("/custom/X2.EXE")


def test_find_x2_returns_none_when_nothing_is_installed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "stockroom.altium.driver._INSTALL_ROOTS", (str(tmp_path / "absent"),)
    )
    assert find_x2(env={}) is None


def test_run_outcome_ok_is_only_true_for_ok():
    assert RunOutcome("ok", "").ok
    for status in ("busy", "dialog", "exited", "timeout", "not-installed"):
        assert not RunOutcome(status, "").ok


def test_altiums_own_main_window_during_a_run_is_not_a_stuck_dialog(tmp_path: Path, x2: Path):
    """A run that opens a document MAKES Altium show a window, so a title is not evidence of a
    modal.

    Measured 2026-07-25: this fired on `'Home Page - Altium Designer Professional (26.8.1)'` and
    killed a run whose script had already completed and written its marker. The old harness only
    escaped it by polling slowly enough to miss the window. Only a title matching a known
    waiting-for-a-human pattern counts, and the timeout stays as the backstop for a genuine hang.
    """
    drv, host, marker = _driver(
        tmp_path,
        x2,
        processes="4242\tHome Page - Altium Designer Professional (26.8.1)\n",
        windows="Home Page - Altium Designer Professional (26.8.1)\n",
        marker_after=2,
    )
    out = drv.run_script(
        proc="P.pas>P",
        marker=marker,
        project=tmp_path / "P.PrjScr",
        timeout=999,
        allow_busy=True,
    )
    assert out.status == "ok", out.detail


def test_a_document_window_does_not_mask_a_real_modal(tmp_path: Path, x2: Path):
    # The other half of the same rule: a genuine chooser must still be caught even while Altium
    # legitimately has its own window open.
    drv, host, marker = _driver(
        tmp_path,
        x2,
        processes="4242\tAltium Designer\n",
        windows="Altium Designer\nSelect Item To Run\n",
    )
    out = drv.run_script(
        proc="P.pas>P", marker=marker, project=tmp_path / "P.PrjScr", timeout=999, allow_busy=True
    )
    assert out.status == "dialog"
    assert "Select Item To Run" in out.titles[0]
