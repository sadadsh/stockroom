"""Deterministic visible V1 -> V2 -> V1 packaged-release rehearsal.

This is an acceptance harness, not a release implementation.  One stable
source broker owns the loopback origin and production release boundary while
each accepted release supplies its exact manifest-bound backend executable and
native ``WindowHost/Stockroom.WindowHost.exe`` child.

Screenshots are delegated to a trusted exact-HWND capture port.  The harness
never enables WebView2 remote debugging and fails closed when no capture port
is supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from fastapi import FastAPI

from packaging.coordinator_availability_probe import (
    CoordinatorAvailabilityProbeError,
    probe_coordinator_availability,
)
from stockroom.api.serve import pick_free_port
from stockroom.host.proxy import SwitchableBackendProxy
from stockroom.host.release_runtime import HostManifestRehearsal, HostReleaseBoundary
from stockroom.host.run import _serve_in_thread
from stockroom.host.service_authority import ContextServiceAuthority
from stockroom.host.window_runtime import ProductionWindowReplacement
from stockroom.host.window_supervisor import WindowHostLaunch
from stockroom.service import ServiceMode
from stockroom.store.machine_config import MachineConfig
from stockroom.store.ui_session import load_snapshot, save_snapshot
from stockroom.update import AcceptedRelease, ReleaseHealthStage, verify_local_release_set

_MAX_API_BYTES = 1024 * 1024
_PHASES = ("before_v1", "during_v2", "after_v1")
_WM_GETICON = 0x007F
_ICON_SMALL = 0
_ICON_BIG = 1


class VisibleReleaseRehearsalError(RuntimeError):
    """The visible packaged-release rehearsal could not prove its contract."""


class WindowCapturePort(Protocol):
    """Trusted exact-HWND capture seam supplied by the acceptance environment."""

    def capture(
        self,
        *,
        process_id: int,
        window_handle: int,
        destination: Path,
    ) -> None: ...


def _require_capture_port(
    capture_port: WindowCapturePort | None,
) -> WindowCapturePort:
    if capture_port is None or not callable(getattr(capture_port, "capture", None)):
        raise VisibleReleaseRehearsalError(
            "a trusted exact-HWND Windows Graphics Capture port is required"
        )
    return capture_port


class _Lifecycle:
    def start(self, control, fence):
        del control
        return fence

    def stop(self, handle, *, timeout: float) -> None:
        del handle, timeout


@dataclass(frozen=True, slots=True)
class RehearsalInputs:
    v1_host_executable: Path
    v1_release_directory: Path
    v1_release_id: str
    v1_manifest_sha256: str
    v2_release_directory: Path
    v2_release_id: str
    v2_manifest_sha256: str
    config_root: Path
    local_app_data: Path
    roaming_app_data: Path
    evidence_root: Path


@dataclass(frozen=True, slots=True)
class StepEvidence:
    phase: str
    expected_release_id: str
    broker_pid: int
    loopback_origin: str
    native_process_id: int
    native_parent_process_id: int
    native_window_handle: int
    native_profile_id: str
    native_renderer: str
    native_executable: str
    native_executable_sha256: str
    native_health: dict[str, object]
    native_export: dict[str, object]
    identity: dict[str, object]
    update: dict[str, object]
    settings_capture: str
    settings_sha256: str

    def document(self) -> dict[str, object]:
        return {
            "broker_pid": self.broker_pid,
            "expected_release_id": self.expected_release_id,
            "identity": self.identity,
            "loopback_origin": self.loopback_origin,
            "native_executable": self.native_executable,
            "native_executable_sha256": self.native_executable_sha256,
            "native_export": self.native_export,
            "native_health": self.native_health,
            "native_parent_process_id": self.native_parent_process_id,
            "native_process_id": self.native_process_id,
            "native_profile_id": self.native_profile_id,
            "native_renderer": self.native_renderer,
            "native_window_handle": self.native_window_handle,
            "phase": self.phase,
            "settings_capture": self.settings_capture,
            "settings_sha256": self.settings_sha256,
            "update": self.update,
        }


class RehearsalLedger:
    """Strict receipt builder shared by the live driver and focused tests."""

    def __init__(self, *, v1_release_id: str, v2_release_id: str) -> None:
        self._expected = {
            "before_v1": v1_release_id,
            "during_v2": v2_release_id,
            "after_v1": v1_release_id,
        }
        self._steps: list[StepEvidence] = []

    def add(self, step: StepEvidence) -> None:
        index = len(self._steps)
        if index >= len(_PHASES) or step.phase != _PHASES[index]:
            raise VisibleReleaseRehearsalError("release observations are out of order")
        if step.expected_release_id != self._expected[step.phase]:
            raise VisibleReleaseRehearsalError("release observation expectation is incoherent")
        if step.identity.get("release_id") != step.expected_release_id:
            raise VisibleReleaseRehearsalError(
                f"{step.phase} identity does not name the expected release"
            )
        if step.update.get("current_release_id") != step.expected_release_id:
            raise VisibleReleaseRehearsalError(
                f"{step.phase} update status does not name the expected release"
            )
        if (
            step.broker_pid <= 0
            or step.native_process_id <= 0
            or step.native_parent_process_id != step.broker_pid
            or step.native_window_handle <= 0
        ):
            raise VisibleReleaseRehearsalError("visible window identity is invalid")
        if (
            not step.native_profile_id.startswith("window-")
            or step.native_renderer != "edgechromium"
        ):
            raise VisibleReleaseRehearsalError("native window contract is invalid")
        if step.native_health.get("current_url") is None:
            raise VisibleReleaseRehearsalError("native window health is incomplete")
        if (
            step.native_health.get("visible") is not True
            or step.native_health.get("hidden") is not False
        ):
            raise VisibleReleaseRehearsalError("native window is not visibly ready")
        if step.native_export.get("theme") not in {"dark", "light"}:
            raise VisibleReleaseRehearsalError("native window export is incomplete")
        snapshot = step.native_export.get("snapshot")
        if type(snapshot) is not dict or snapshot.get("route") != "settings":
            raise VisibleReleaseRehearsalError("Settings route was not restored")
        executable = Path(step.native_executable)
        if (
            not executable.is_absolute()
            or executable.name != "Stockroom.WindowHost.exe"
            or len(step.native_executable_sha256) != 64
        ):
            raise VisibleReleaseRehearsalError("native executable evidence is invalid")
        parsed = urlsplit(step.loopback_origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise VisibleReleaseRehearsalError("visible origin is not exact loopback HTTP")
        capture = Path(step.settings_capture)
        if not capture.is_absolute() or len(step.settings_sha256) != 64:
            raise VisibleReleaseRehearsalError("Settings evidence is incomplete")
        self._steps.append(step)

    def finish(
        self,
        *,
        shell_identity: dict[str, object],
        remaining_worker_pids: tuple[int, ...],
        x2_before: tuple[int, ...],
        x2_after: tuple[int, ...],
    ) -> list[dict[str, object]]:
        if len(self._steps) != len(_PHASES):
            raise VisibleReleaseRehearsalError("release rehearsal did not record every phase")
        stable = {(step.broker_pid, step.loopback_origin) for step in self._steps}
        if len(stable) != 1:
            raise VisibleReleaseRehearsalError(
                "broker PID or loopback origin changed during adoption"
            )
        if (
            len({step.native_process_id for step in self._steps}) != len(self._steps)
            or len({step.native_window_handle for step in self._steps})
            != len(self._steps)
        ):
            raise VisibleReleaseRehearsalError(
                "each principal phase must use a distinct native window child"
            )
        if len({step.native_profile_id for step in self._steps}) != len(self._steps):
            raise VisibleReleaseRehearsalError(
                "each principal phase must use a distinct native window profile"
            )
        if remaining_worker_pids:
            raise VisibleReleaseRehearsalError("release workers remained after cleanup")
        if set(x2_after) - set(x2_before):
            raise VisibleReleaseRehearsalError("the rehearsal launched an Altium process")
        required_shell_truth = {
            "file_icon_present": True,
            "process_image_matches": True,
            "wm_geticon_small_present": True,
            "wm_geticon_big_present": True,
        }
        for key, expected in required_shell_truth.items():
            if shell_identity.get(key) is not expected:
                raise VisibleReleaseRehearsalError(f"shell identity check failed: {key}")
        aumid = shell_identity.get("taskbar_aumid")
        if type(aumid) is not str or not aumid:
            raise VisibleReleaseRehearsalError("taskbar AppUserModelID is unavailable")
        return [step.document() for step in self._steps]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolved_directory(path: Path, label: str) -> Path:
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as exc:
        raise VisibleReleaseRehearsalError(f"{label} does not exist") from exc
    if not resolved.is_dir():
        raise VisibleReleaseRehearsalError(f"{label} is not a directory")
    return resolved


def _validate_roots(inputs: RehearsalInputs) -> RehearsalInputs:
    roots = {
        "config root": _resolved_directory(inputs.config_root, "config root"),
        "local app-data root": _resolved_directory(
            inputs.local_app_data, "local app-data root"
        ),
        "roaming app-data root": _resolved_directory(
            inputs.roaming_app_data, "roaming app-data root"
        ),
        "evidence root": _resolved_directory(inputs.evidence_root, "evidence root"),
    }
    values = tuple(roots.values())
    if len(set(values)) != len(values):
        raise VisibleReleaseRehearsalError("isolated roots must be distinct")
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            if left in right.parents or right in left.parents:
                raise VisibleReleaseRehearsalError("isolated roots must not contain each other")
    live = {
        Path(value).resolve()
        for value in (
            os.environ.get("STOCKROOM_CONFIG_DIR", ""),
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("APPDATA", ""),
        )
        if value
    }
    overlap = set(values) & live
    if overlap:
        raise VisibleReleaseRehearsalError(
            "rehearsal roots must not equal the current live environment roots"
        )
    return RehearsalInputs(
        v1_host_executable=Path(inputs.v1_host_executable).resolve(strict=True),
        v1_release_directory=Path(inputs.v1_release_directory).resolve(strict=True),
        v1_release_id=inputs.v1_release_id,
        v1_manifest_sha256=inputs.v1_manifest_sha256,
        v2_release_directory=Path(inputs.v2_release_directory).resolve(strict=True),
        v2_release_id=inputs.v2_release_id,
        v2_manifest_sha256=inputs.v2_manifest_sha256,
        config_root=roots["config root"],
        local_app_data=roots["local app-data root"],
        roaming_app_data=roots["roaming app-data root"],
        evidence_root=roots["evidence root"],
    )


def _manifest_backend(release) -> Path:
    paths = [
        release.members[member.path]
        for member in release.manifest.members
        if member.kind == "backend"
    ]
    if len(paths) != 1:
        raise VisibleReleaseRehearsalError(
            "verified release must bind exactly one backend executable"
        )
    path = Path(paths[0]).resolve(strict=True)
    if path.suffix.casefold() != ".exe":
        raise VisibleReleaseRehearsalError("release backend is not a Windows executable")
    return path


def _accepted_local_release(release) -> AcceptedRelease:
    """Promote one freshly re-hashed package-local set into the strict host shape."""

    return AcceptedRelease(
        release_id=release.release_id,
        directory=release.directory,
        manifest_path=release.manifest_path,
        manifest_sha256=release.manifest_sha256,
        manifest=release.manifest,
        members=release.members,
    )


def _manifest_window_host(release: AcceptedRelease) -> Path:
    launch = WindowHostLaunch.from_release(release)
    if len(launch.command_prefix) != 1:
        raise VisibleReleaseRehearsalError(
            "native window host launch is not one exact executable"
        )
    return Path(launch.command_prefix[0]).resolve(strict=True)


def _verify_inputs(inputs: RehearsalInputs):
    inputs = _validate_roots(inputs)
    if sys.platform != "win32":
        raise VisibleReleaseRehearsalError("visible release rehearsal requires Windows")
    if (
        not inputs.v1_release_id
        or not inputs.v2_release_id
        or inputs.v1_release_id == inputs.v2_release_id
    ):
        raise VisibleReleaseRehearsalError("V1 and V2 release IDs must be distinct")
    if (
        not inputs.v1_host_executable.is_file()
        or inputs.v1_host_executable.suffix.casefold() != ".exe"
    ):
        raise VisibleReleaseRehearsalError("V1 unpacked host must be an executable file")
    v1 = verify_local_release_set(
        inputs.v1_release_directory,
        expected_release_id=inputs.v1_release_id,
        expected_manifest_sha256=inputs.v1_manifest_sha256,
    )
    v2 = verify_local_release_set(
        inputs.v2_release_directory,
        expected_release_id=inputs.v2_release_id,
        expected_manifest_sha256=inputs.v2_manifest_sha256,
    )
    v1_worker = _manifest_backend(v1)
    v2_worker = _manifest_backend(v2)
    if _sha256(inputs.v1_host_executable) != _sha256(v1_worker):
        raise VisibleReleaseRehearsalError(
            "V1 unpacked host is not byte-identical to the V1 manifest backend"
        )
    if not v2.manifest.supports_direct_activation_from(v1.release_id):
        raise VisibleReleaseRehearsalError("V2 does not authorize direct adoption from V1")
    if v2.manifest.rollback_release_id != v1.release_id:
        raise VisibleReleaseRehearsalError("V2 does not bind V1 as its rollback release")
    HostManifestRehearsal().rehearse(
        cast(Any, v2),
        cast(Any, v1),
        generation=1,
    )
    accepted_v1 = _accepted_local_release(v1)
    accepted_v2 = _accepted_local_release(v2)
    v1_window_host = _manifest_window_host(accepted_v1)
    v2_window_host = _manifest_window_host(accepted_v2)
    return (
        inputs,
        accepted_v1,
        accepted_v2,
        v1_worker,
        v2_worker,
        v1_window_host,
        v2_window_host,
    )


def _validate_isolated_library(inputs: RehearsalInputs) -> Path:
    """Require the task-owned config to resolve to a task-owned initialized library."""

    from stockroom.store.library_location import (
        library_is_initialized,
        resolve_libraries_root,
    )
    from stockroom.store.machine_config import MachineConfig

    config = MachineConfig.load(migrate_credentials=False)
    library_root = resolve_libraries_root(config)
    if library_root is None:
        raise VisibleReleaseRehearsalError(
            "isolated config does not name a library root"
        )
    library_root = Path(library_root).resolve()
    owners = (
        inputs.config_root,
        inputs.local_app_data,
        inputs.roaming_app_data,
    )
    if not any(library_root == owner or owner in library_root.parents for owner in owners):
        raise VisibleReleaseRehearsalError(
            "isolated config points outside the task-owned roots"
        )
    if not library_is_initialized(library_root):
        raise VisibleReleaseRehearsalError(
            "isolated config does not name an initialized library"
        )
    return library_root


@contextmanager
def _isolated_environment(inputs: RehearsalInputs):
    replacements = {
        "APPDATA": str(inputs.roaming_app_data),
        "GIT_TERMINAL_PROMPT": "0",
        "LOCALAPPDATA": str(inputs.local_app_data),
        "STOCKROOM_CONFIG_DIR": str(inputs.config_root),
        "STOCKROOM_UPDATE_DATA_ROOT": str(inputs.local_app_data / "Stockroom"),
        "STOCKROOM_UPDATE_MODE": "production",
    }
    prior = {key: os.environ.get(key) for key in replacements}
    os.environ.update(replacements)
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _json_get(url: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"X-Stockroom-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            if response.status != 200:
                raise VisibleReleaseRehearsalError(f"{url} returned {response.status}")
            raw = response.read(_MAX_API_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise VisibleReleaseRehearsalError(
            f"{urlsplit(url).path} is unavailable ({exc.code})"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise VisibleReleaseRehearsalError(
            f"{urlsplit(url).path} could not be queried"
        ) from exc
    if len(raw) > _MAX_API_BYTES:
        raise VisibleReleaseRehearsalError("API evidence exceeded its bounded size")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise VisibleReleaseRehearsalError("API evidence is not valid JSON") from exc
    if type(document) is not dict:
        raise VisibleReleaseRehearsalError("API evidence is not a JSON object")
    return document


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise VisibleReleaseRehearsalError("window left the stable loopback origin")
    return f"http://127.0.0.1:{parsed.port}"


def _x2_process_ids() -> tuple[int, ...]:
    completed = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq X2.EXE", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise VisibleReleaseRehearsalError("Altium process inventory failed")
    rows = tuple(csv.reader(completed.stdout.splitlines()))
    found: list[int] = []
    for row in rows:
        if len(row) < 2 or row[0].casefold() != "x2.exe":
            continue
        try:
            found.append(int(row[1].replace(",", "")))
        except ValueError as exc:
            raise VisibleReleaseRehearsalError("Altium process inventory is invalid") from exc
    return tuple(sorted(found))


def _capture_native_settings(
    *,
    replacement: ProductionWindowReplacement,
    capture_port: WindowCapturePort,
    native_executable: Path,
    base_url: str,
    token: str,
    expected_release_id: str,
    phase: str,
    evidence_root: Path,
) -> StepEvidence:
    observation = replacement.observe_active()
    identity_record = observation.identity
    health = observation.health
    exported = observation.exported
    if identity_record.release_id != expected_release_id:
        raise VisibleReleaseRehearsalError(
            "active native window does not name the expected release"
        )
    if not health.visible or health.hidden:
        raise VisibleReleaseRehearsalError("active native window is not visible")
    if exported.snapshot.get("route") != "settings":
        raise VisibleReleaseRehearsalError("Settings route was not restored")
    identity = _json_get(f"{base_url}/api/system/identity", token)
    update = _json_get(f"{base_url}/api/update/check", token)
    path = (evidence_root / f"Settings {phase.replace('_', ' ').title()}.png").resolve()
    if path.parent != evidence_root or path.exists() or path.is_symlink():
        raise VisibleReleaseRehearsalError("Settings evidence path is unsafe")
    try:
        capture_port.capture(
            process_id=identity_record.process_id,
            window_handle=identity_record.window_handle,
            destination=path,
        )
        png = path.read_bytes()
    except BaseException as exc:
        raise VisibleReleaseRehearsalError(
            "trusted exact-HWND Settings capture failed"
        ) from exc
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VisibleReleaseRehearsalError("Settings screenshot is not a PNG")
    resolved_executable = Path(native_executable).resolve(strict=True)
    native_export = {
        "api_healthy": exported.api_healthy,
        "event_stream_healthy": exported.event_stream_healthy,
        "geometry": exported.geometry.to_config(),
        "snapshot": exported.snapshot,
        "theme": exported.theme,
    }
    native_health = {
        "close_requested": health.close_requested,
        "current_url": health.current_url,
        "hidden": health.hidden,
        "renderer": health.renderer,
        "visible": health.visible,
        "window_handle": health.window_handle,
    }
    return StepEvidence(
        phase=phase,
        expected_release_id=expected_release_id,
        broker_pid=os.getpid(),
        loopback_origin=_origin(health.current_url),
        native_process_id=identity_record.process_id,
        native_parent_process_id=identity_record.parent_process_id,
        native_window_handle=identity_record.window_handle,
        native_profile_id=identity_record.profile_id,
        native_renderer=identity_record.renderer,
        native_executable=str(resolved_executable),
        native_executable_sha256=_sha256(resolved_executable),
        native_health=native_health,
        native_export=native_export,
        identity=identity,
        update=update,
        settings_capture=str(path),
        settings_sha256=hashlib.sha256(png).hexdigest(),
    )


def _inspect_shell_identity(
    hwnd: int,
    executable: Path,
    *,
    process_id: int,
) -> dict[str, object]:
    if sys.platform != "win32":
        raise VisibleReleaseRehearsalError("shell inspection requires Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = wintypes.LPARAM
    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = wintypes.UINT
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetApplicationUserModelId.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.UINT),
        wintypes.LPWSTR,
    ]
    kernel32.GetApplicationUserModelId.restype = ctypes.c_long
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    large = wintypes.HICON()
    small = wintypes.HICON()
    count = int(
        shell32.ExtractIconExW(
            str(executable),
            0,
            ctypes.byref(large),
            ctypes.byref(small),
            1,
        )
    )
    process_handle = kernel32.OpenProcess(0x1000, False, process_id)
    if not process_handle:
        raise VisibleReleaseRehearsalError("native window process cannot be inspected")
    try:
        image_capacity = wintypes.DWORD(32768)
        image_buffer = ctypes.create_unicode_buffer(image_capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            process_handle,
            0,
            image_buffer,
            ctypes.byref(image_capacity),
        ):
            raise VisibleReleaseRehearsalError(
                "native window process image cannot be inspected"
            )
        aumid_capacity = wintypes.UINT(0)
        result = int(
            kernel32.GetApplicationUserModelId(
                process_handle,
                ctypes.byref(aumid_capacity),
                None,
            )
        )
        aumid = ""
        if result == 122 and aumid_capacity.value > 1:
            aumid_buffer = ctypes.create_unicode_buffer(aumid_capacity.value)
            result = int(
                kernel32.GetApplicationUserModelId(
                    process_handle,
                    ctypes.byref(aumid_capacity),
                    aumid_buffer,
                )
            )
            if result == 0:
                aumid = aumid_buffer.value
        return {
            "file_icon_present": count == 1 and bool(large.value or small.value),
            "process_image": str(Path(image_buffer.value).resolve()),
            "process_image_matches": (
                Path(image_buffer.value).resolve() == Path(executable).resolve()
            ),
            "taskbar_aumid": aumid or "",
            "wm_geticon_big_present": bool(
                user32.SendMessageW(hwnd, _WM_GETICON, _ICON_BIG, 0)
            ),
            "wm_geticon_small_present": bool(
                user32.SendMessageW(hwnd, _WM_GETICON, _ICON_SMALL, 0)
            ),
        }
    finally:
        kernel32.CloseHandle(process_handle)
        if large:
            user32.DestroyIcon(large)
        if small:
            user32.DestroyIcon(small)


def _atomic_receipt(path: Path, document: dict[str, object]) -> None:
    path = Path(path)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise VisibleReleaseRehearsalError("rehearsal receipt path is unsafe")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_convergence_status(path: Path, release_id: str, phase: str) -> None:
    """Publish the harness-owned signed-update projection consumed by both workers."""

    document = {
        "automatic_on_launch": True,
        "channel": "production",
        "check_interval_seconds": 60,
        "convergence_phase": phase,
        "current_release_id": release_id,
        "current_revision": release_id,
        "detail": "Visible release rehearsal is controlling the verified release set.",
        "next_attempt_at": None,
        "retry_attempt": 0,
        "state": "up_to_date",
        "target_release_id": release_id,
        "target_revision": release_id,
        "update_available": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_visible_release_rehearsal(
    *,
    inputs: RehearsalInputs,
    receipt_path: Path,
    capture_port: WindowCapturePort | None = None,
) -> None:
    """Run the bounded visible rehearsal and write one strict terminal receipt."""

    started = time.monotonic()
    (
        inputs,
        v1,
        v2,
        v1_worker,
        v2_worker,
        v1_window_host,
        v2_window_host,
    ) = _verify_inputs(inputs)
    receipt_path = Path(receipt_path).resolve()
    if receipt_path.parent != inputs.evidence_root:
        raise VisibleReleaseRehearsalError("receipt must be directly under the evidence root")
    capture_port = _require_capture_port(capture_port)
    probe_coordinator_availability()
    x2_before = _x2_process_ids()
    token = secrets.token_urlsafe(32)
    public_port = pick_free_port()
    base_url = f"http://127.0.0.1:{public_port}"
    ledger = RehearsalLedger(
        v1_release_id=inputs.v1_release_id,
        v2_release_id=inputs.v2_release_id,
    )
    shell_identity: dict[str, object] = {}
    rollback_fault: dict[str, object] | None = None

    with _isolated_environment(inputs):
        service_root = inputs.local_app_data / "Stockroom" / "Service State"
        service_root.mkdir(parents=True, exist_ok=True)
        workflow_database = service_root / "Workflow.sqlite"
        convergence_status_path = (
            inputs.local_app_data
            / "Stockroom"
            / "Update State"
            / "Visible Rehearsal Status.json"
        )
        context = SimpleNamespace()
        authority = ContextServiceAuthority(
            context,
            release_id="release-visible-rehearsal-bootstrap",
            control_database=(service_root / "Control.sqlite").resolve(),
            lifecycle=_Lifecycle(),
            start_as_coordinator=True,
        )
        bootstrap = SimpleNamespace(release_id="release-visible-rehearsal-bootstrap")
        local = FastAPI()

        @local.get("/api/health")
        def health() -> dict[str, object]:
            snapshot = authority.snapshot()
            return {
                "coordinator_status": snapshot.status.value,
                "release_id": bootstrap.release_id,
                "service_generation": snapshot.generation,
                "service_mode": snapshot.mode.value,
                "status": "ok",
            }

        proxy = SwitchableBackendProxy(local)
        server, server_thread = _serve_in_thread(proxy, public_port)
        boundary = HostReleaseBoundary(
            proxy,
            public_base_url=base_url,
            token=token,
            local_release_id=bootstrap.release_id,
            reload_window=lambda _url: None,
            local_service_authority=authority,
            workflow_database=workflow_database,
            convergence_status_path=convergence_status_path,
            startup_timeout_seconds=60.0,
            post_adoption_probes=2,
            probe_interval_seconds=0.1,
            drain_timeout_seconds=30.0,
            stop_timeout_seconds=15.0,
        )
        replacement: ProductionWindowReplacement | None = None
        fresh_replacement: ProductionWindowReplacement | None = None
        v1_handle = None
        v2_handle = None

        def adopt(candidate, current, handle):
            boundary.check(
                candidate,
                handle,
                stage=ReleaseHealthStage.PRE_ADOPTION,
                generation=1,
            )
            drained = boundary.drain(current, generation=1)
            adopted = boundary.adopt(
                candidate,
                current,
                handle,
                drained,
                generation=1,
            )
            boundary.check(
                candidate,
                handle,
                stage=ReleaseHealthStage.POST_ADOPTION,
                generation=1,
            )
            return adopted

        try:
            isolated_library_root = _validate_isolated_library(inputs)
            config = MachineConfig.load(migrate_credentials=False)
            settings_snapshot = load_snapshot(config)
            settings_snapshot["route"] = "settings"
            save_snapshot(settings_snapshot, config)
            v1_handle = boundary.launch_shadow(v1, generation=1)
            v1_command = cast(list[str], v1_handle.process.args)
            if Path(v1_command[0]).resolve() != v1_worker:
                raise VisibleReleaseRehearsalError("boundary launched the wrong V1 executable")
            adopt(v1, bootstrap, v1_handle)
            replacement = ProductionWindowReplacement(
                v1,
                public_base_url=base_url,
                api_credential=token,
                config=config,
            )
            boundary.attach_window_replacement(replacement)
            replacement.start_initial(v1)
            _write_convergence_status(
                convergence_status_path,
                v1.release_id,
                "before_v1",
            )
            before = _capture_native_settings(
                replacement=replacement,
                capture_port=capture_port,
                native_executable=v1_window_host,
                base_url=base_url,
                token=token,
                expected_release_id=v1.release_id,
                phase="before_v1",
                evidence_root=inputs.evidence_root,
            )
            ledger.add(before)
            shell_identity = _inspect_shell_identity(
                before.native_window_handle,
                v1_window_host,
                process_id=before.native_process_id,
            )

            v2_handle = boundary.launch_shadow(v2, generation=1)
            v2_command = cast(list[str], v2_handle.process.args)
            if Path(v2_command[0]).resolve() != v2_worker:
                raise VisibleReleaseRehearsalError(
                    "boundary launched the wrong V2 executable"
                )
            v2_adoption = adopt(v2, v1, v2_handle)
            _write_convergence_status(
                convergence_status_path,
                v2.release_id,
                "during_v2",
            )
            ledger.add(
                _capture_native_settings(
                    replacement=replacement,
                    capture_port=capture_port,
                    native_executable=v2_window_host,
                    base_url=base_url,
                    token=token,
                    expected_release_id=v2.release_id,
                    phase="during_v2",
                    evidence_root=inputs.evidence_root,
                )
            )

            boundary.rollback(v2, v1, v2_adoption, generation=1)
            _write_convergence_status(
                convergence_status_path,
                v1.release_id,
                "precommit_rollback_v1",
            )
            rollback_fault = _capture_native_settings(
                replacement=replacement,
                capture_port=capture_port,
                native_executable=v1_window_host,
                base_url=base_url,
                token=token,
                expected_release_id=v1.release_id,
                phase="precommit_rollback_v1",
                evidence_root=inputs.evidence_root,
            ).document()
            boundary.stop_shadow(v2_handle, generation=1)
            v2_handle = None

            replacement.close()
            fresh_replacement = ProductionWindowReplacement(
                v1,
                public_base_url=base_url,
                api_credential=token,
                config=MachineConfig.load(migrate_credentials=False),
            )
            fresh_replacement.start_initial(v1)
            _write_convergence_status(
                convergence_status_path,
                v1.release_id,
                "after_v1",
            )
            ledger.add(
                _capture_native_settings(
                    replacement=fresh_replacement,
                    capture_port=capture_port,
                    native_executable=v1_window_host,
                    base_url=base_url,
                    token=token,
                    expected_release_id=v1.release_id,
                    phase="after_v1",
                    evidence_root=inputs.evidence_root,
                )
            )
            fresh_replacement.close()
            fresh_replacement = None
            boundary.close()
            x2_after = _x2_process_ids()
            steps = ledger.finish(
                shell_identity=shell_identity,
                remaining_worker_pids=boundary.live_process_ids,
                x2_before=x2_before,
                x2_after=x2_after,
            )
            _atomic_receipt(
                receipt_path,
                {
                    "controller": {
                        "kind": "stable-source-broker-with-packaged-native-window-hosts",
                        "limitation": (
                            "The committed V2 to cached V1 pointer rollback is owned by "
                            "the production rollback activator; this harness records the "
                            "precommit fault rollback separately."
                        ),
                        "pid": os.getpid(),
                    },
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "exact_executables": {
                        "v1_host": str(inputs.v1_host_executable),
                        "v1_host_sha256": _sha256(inputs.v1_host_executable),
                        "v1_worker": str(v1_worker),
                        "v1_worker_sha256": _sha256(v1_worker),
                        "v1_window_host": str(v1_window_host),
                        "v1_window_host_sha256": _sha256(v1_window_host),
                        "v2_worker": str(v2_worker),
                        "v2_worker_sha256": _sha256(v2_worker),
                        "v2_window_host": str(v2_window_host),
                        "v2_window_host_sha256": _sha256(v2_window_host),
                    },
                    "native_eda": {
                        "new_x2_processes": sorted(set(x2_after) - set(x2_before)),
                        "x2_after": list(x2_after),
                        "x2_before": list(x2_before),
                    },
                    "passed": True,
                    "precommit_rollback_fault": rollback_fault,
                    "schema": "stockroom-visible-release-rehearsal/2",
                    "isolated_library_root": str(isolated_library_root),
                    "shell_identity": shell_identity,
                    "steps": steps,
                    "worker_cleanup": {
                        "remaining_process_ids": list(boundary.live_process_ids),
                    },
                },
            )
        finally:
            try:
                if fresh_replacement is not None:
                    fresh_replacement.close()
            finally:
                try:
                    boundary.close()
                finally:
                    server.should_exit = True
                    server_thread.join(timeout=15.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1-host-executable", required=True, type=Path)
    parser.add_argument("--v1-release-directory", required=True, type=Path)
    parser.add_argument("--v1-release-id", required=True)
    parser.add_argument("--v1-manifest-sha256", required=True)
    parser.add_argument("--v2-release-directory", required=True, type=Path)
    parser.add_argument("--v2-release-id", required=True)
    parser.add_argument("--v2-manifest-sha256", required=True)
    parser.add_argument("--config-root", required=True, type=Path)
    parser.add_argument("--local-app-data", required=True, type=Path)
    parser.add_argument("--roaming-app-data", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    inputs = RehearsalInputs(
        v1_host_executable=args.v1_host_executable,
        v1_release_directory=args.v1_release_directory,
        v1_release_id=args.v1_release_id,
        v1_manifest_sha256=args.v1_manifest_sha256,
        v2_release_directory=args.v2_release_directory,
        v2_release_id=args.v2_release_id,
        v2_manifest_sha256=args.v2_manifest_sha256,
        config_root=args.config_root,
        local_app_data=args.local_app_data,
        roaming_app_data=args.roaming_app_data,
        evidence_root=args.evidence_root,
    )
    try:
        run_visible_release_rehearsal(inputs=inputs, receipt_path=args.receipt)
    except (VisibleReleaseRehearsalError, CoordinatorAvailabilityProbeError) as exc:
        print(f"Visible release rehearsal failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
