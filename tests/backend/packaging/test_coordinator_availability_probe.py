from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import packaging.coordinator_availability_probe as probe
from stockroom.service import MutexAcquireResult, current_user_mutex_name

SID = "S-1-5-21-111111111-222222222-333333333-1001"


@dataclass
class _Identity:
    sid: str = SID

    def current_sid(self) -> str:
        return self.sid


@dataclass
class _Handle:
    result: MutexAcquireResult
    release_calls: int = 0
    close_calls: int = 0

    def try_acquire(self) -> MutexAcquireResult:
        return self.result

    def release(self) -> None:
        self.release_calls += 1

    def close(self) -> None:
        self.close_calls += 1


@dataclass
class _Factory:
    handle: _Handle
    opened: list[tuple[str, str]]

    def open_current_user(self, *, name: str, sid: str) -> _Handle:
        self.opened.append((name, sid))
        return self.handle


@pytest.mark.parametrize(
    "result",
    [
        MutexAcquireResult.CREATED,
        MutexAcquireResult.ACQUIRED,
        MutexAcquireResult.ABANDONED,
    ],
)
def test_available_coordinator_claim_is_released_and_closed(
    result: MutexAcquireResult,
) -> None:
    handle = _Handle(result)
    opened: list[tuple[str, str]] = []

    observed = probe.probe_coordinator_availability(
        identity=_Identity(),
        mutex_factory=_Factory(handle, opened),
    )

    assert observed is result
    assert opened == [(current_user_mutex_name(SID), SID)]
    assert handle.release_calls == 1
    assert handle.close_calls == 1


def test_busy_coordinator_fails_without_waiting_and_closes_handle() -> None:
    handle = _Handle(MutexAcquireResult.BUSY)

    with pytest.raises(
        probe.CoordinatorUnavailable,
        match="Another Stockroom instance owns coordinator authority",
    ):
        probe.probe_coordinator_availability(
            identity=_Identity(),
            mutex_factory=_Factory(handle, []),
        )

    assert handle.release_calls == 0
    assert handle.close_calls == 1


def test_command_reports_busy_coordinator_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def unavailable() -> MutexAcquireResult:
        raise probe.CoordinatorUnavailable("coordinator is busy")

    monkeypatch.setattr(probe, "probe_coordinator_availability", unavailable)

    assert probe.main() == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ("Stockroom coordinator preflight failed: coordinator is busy\n")


def test_windows_build_runs_advisory_probe_before_resetting_outputs() -> None:
    build_script = (
        Path(__file__).resolve().parents[3] / "packaging" / "Build-Windows-Package.ps1"
    ).read_text(encoding="utf-8")

    invocation = '"run", "--frozen", "python", $CoordinatorProbeTool'
    output_reset = '$WorkRoot = Initialize-OutputDirectory -Path (Join-Path $OutputRoot "Work")'

    assert "$CoordinatorProbeTool = Join-Path $PackagingRoot " in build_script
    assert build_script.index(invocation) < build_script.index(output_reset)
    assert "Advisory fail-fast check only." in build_script
    assert "runtime still performs the authoritative acquisition" in build_script
