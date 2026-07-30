from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from packaging.visible_release_rehearsal import (
    RehearsalInputs,
    RehearsalLedger,
    StepEvidence,
    VisibleReleaseRehearsalError,
    _require_capture_port,
    _validate_roots,
    _write_convergence_status,
)


class _Capture:
    def capture(
        self,
        *,
        process_id: int,
        window_handle: int,
        destination: Path,
    ) -> None:
        del process_id, window_handle, destination


def _step(
    tmp_path: Path,
    *,
    phase: str,
    release_id: str,
    broker_pid: int = 41,
    native_pid: int | None = None,
    hwnd: int | None = None,
    profile_id: str | None = None,
    origin: str = "http://127.0.0.1:48123",
) -> StepEvidence:
    capture = (tmp_path / f"{phase}.png").resolve()
    ordinal = {
        "before_v1": 1,
        "during_v2": 2,
        "after_v1": 3,
    }.get(phase, 4)
    native_pid = 100 + ordinal if native_pid is None else native_pid
    hwnd = 200 + ordinal if hwnd is None else hwnd
    profile_id = (
        f"window-{ordinal:032x}" if profile_id is None else profile_id
    )
    executable = (tmp_path / release_id / "WindowHost" / "Stockroom.WindowHost.exe").resolve()
    return StepEvidence(
        phase=phase,
        expected_release_id=release_id,
        broker_pid=broker_pid,
        loopback_origin=origin,
        native_process_id=native_pid,
        native_parent_process_id=broker_pid,
        native_window_handle=hwnd,
        native_profile_id=profile_id,
        native_renderer="edgechromium",
        native_executable=str(executable),
        native_executable_sha256="b" * 64,
        native_health={
            "current_url": f"{origin}/",
            "hidden": False,
            "visible": True,
        },
        native_export={
            "snapshot": {"route": "settings"},
            "theme": "dark",
        },
        identity={"release_id": release_id},
        update={"current_release_id": release_id},
        settings_capture=str(capture),
        settings_sha256="a" * 64,
    )


def _complete_ledger(tmp_path: Path) -> RehearsalLedger:
    ledger = RehearsalLedger(v1_release_id="release-v1", v2_release_id="release-v2")
    ledger.add(_step(tmp_path, phase="before_v1", release_id="release-v1"))
    ledger.add(_step(tmp_path, phase="during_v2", release_id="release-v2"))
    ledger.add(_step(tmp_path, phase="after_v1", release_id="release-v1"))
    return ledger


def _shell() -> dict[str, object]:
    return {
        "file_icon_present": True,
        "process_image_matches": True,
        "taskbar_aumid": "Stockroom.Desktop.Unpackaged",
        "wm_geticon_big_present": True,
        "wm_geticon_small_present": True,
    }


def test_rehearsal_requires_an_explicit_exact_hwnd_capture_port() -> None:
    capture = _Capture()

    assert _require_capture_port(capture) is capture
    with pytest.raises(VisibleReleaseRehearsalError, match="exact-HWND"):
        _require_capture_port(None)


def test_ledger_accepts_stable_broker_and_three_native_window_children(
    tmp_path: Path,
) -> None:
    steps = _complete_ledger(tmp_path).finish(
        shell_identity=_shell(),
        remaining_worker_pids=(),
        x2_before=(991,),
        x2_after=(991,),
    )

    assert [step["expected_release_id"] for step in steps] == [
        "release-v1",
        "release-v2",
        "release-v1",
    ]
    assert {step["broker_pid"] for step in steps} == {41}
    assert len(
        {
            (step["native_process_id"], step["native_window_handle"])
            for step in steps
        }
    ) == 3


@pytest.mark.parametrize(
    ("phase", "change"),
    [
        ("during_v2", {"broker_pid": 42}),
        ("after_v1", {"origin": "http://127.0.0.1:48124"}),
    ],
)
def test_ledger_rejects_a_replaced_broker_or_origin(
    tmp_path: Path,
    phase: str,
    change: dict[str, Any],
) -> None:
    ledger = RehearsalLedger(v1_release_id="release-v1", v2_release_id="release-v2")
    for current, release in (
        ("before_v1", "release-v1"),
        ("during_v2", "release-v2"),
        ("after_v1", "release-v1"),
    ):
        kwargs = change if current == phase else {}
        ledger.add(_step(tmp_path, phase=current, release_id=release, **kwargs))

    with pytest.raises(VisibleReleaseRehearsalError, match="broker PID or loopback"):
        ledger.finish(
            shell_identity=_shell(),
            remaining_worker_pids=(),
            x2_before=(),
            x2_after=(),
        )


@pytest.mark.parametrize(
    ("phase", "change"),
    [
        ("during_v2", {"native_pid": 101}),
        ("after_v1", {"hwnd": 201}),
        ("after_v1", {"profile_id": f"window-{1:032x}"}),
    ],
)
def test_ledger_rejects_reused_native_child_identity(
    tmp_path: Path,
    phase: str,
    change: dict[str, Any],
) -> None:
    ledger = RehearsalLedger(v1_release_id="release-v1", v2_release_id="release-v2")
    for current, release in (
        ("before_v1", "release-v1"),
        ("during_v2", "release-v2"),
        ("after_v1", "release-v1"),
    ):
        kwargs = change if current == phase else {}
        ledger.add(_step(tmp_path, phase=current, release_id=release, **kwargs))

    with pytest.raises(
        VisibleReleaseRehearsalError,
        match="distinct native window",
    ):
        ledger.finish(
            shell_identity=_shell(),
            remaining_worker_pids=(),
            x2_before=(),
            x2_after=(),
        )


def test_ledger_fails_on_orphan_worker_new_altium_or_missing_shell_identity(
    tmp_path: Path,
) -> None:
    with pytest.raises(VisibleReleaseRehearsalError, match="workers remained"):
        _complete_ledger(tmp_path).finish(
            shell_identity=_shell(),
            remaining_worker_pids=(88,),
            x2_before=(),
            x2_after=(),
        )
    with pytest.raises(VisibleReleaseRehearsalError, match="Altium"):
        _complete_ledger(tmp_path).finish(
            shell_identity=_shell(),
            remaining_worker_pids=(),
            x2_before=(),
            x2_after=(99,),
        )
    shell = _shell()
    shell["wm_geticon_big_present"] = False
    with pytest.raises(VisibleReleaseRehearsalError, match="wm_geticon_big"):
        _complete_ledger(tmp_path).finish(
            shell_identity=shell,
            remaining_worker_pids=(),
            x2_before=(),
            x2_after=(),
        )


def test_ledger_rejects_missing_identity_or_update_release(tmp_path: Path) -> None:
    ledger = RehearsalLedger(v1_release_id="release-v1", v2_release_id="release-v2")
    wrong = _step(tmp_path, phase="before_v1", release_id="release-v1")
    wrong = replace(wrong, identity={"release_id": "release-other"})
    with pytest.raises(VisibleReleaseRehearsalError, match="identity"):
        ledger.add(wrong)


def test_isolated_roots_cannot_alias_or_contain_each_other(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("Config", "Local", "Roaming", "Evidence", "V1", "V2"):
        (tmp_path / name).mkdir()
    host = tmp_path / "Stockroom.exe"
    host.write_bytes(b"MZ")
    monkeypatch.delenv("STOCKROOM_CONFIG_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Live Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Live Roaming"))
    inputs = RehearsalInputs(
        v1_host_executable=host,
        v1_release_directory=tmp_path / "V1",
        v1_release_id="release-v1",
        v1_manifest_sha256="1" * 64,
        v2_release_directory=tmp_path / "V2",
        v2_release_id="release-v2",
        v2_manifest_sha256="2" * 64,
        config_root=tmp_path / "Config",
        local_app_data=tmp_path / "Local",
        roaming_app_data=tmp_path / "Roaming",
        evidence_root=tmp_path / "Evidence",
    )
    assert _validate_roots(inputs).evidence_root == (tmp_path / "Evidence").resolve()

    nested = tmp_path / "Local" / "Evidence"
    nested.mkdir()
    with pytest.raises(VisibleReleaseRehearsalError, match="contain"):
        _validate_roots(replace(inputs, evidence_root=nested))


def test_rehearsal_update_projection_names_the_exact_visible_release(
    tmp_path: Path,
) -> None:
    import json

    path = tmp_path / "Update Status.json"
    _write_convergence_status(path, "release-v2", "during_v2")

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "automatic_on_launch": True,
        "channel": "production",
        "check_interval_seconds": 60,
        "convergence_phase": "during_v2",
        "current_release_id": "release-v2",
        "current_revision": "release-v2",
        "detail": "Visible release rehearsal is controlling the verified release set.",
        "next_attempt_at": None,
        "retry_attempt": 0,
        "state": "up_to_date",
        "target_release_id": "release-v2",
        "target_revision": "release-v2",
        "update_available": False,
    }
