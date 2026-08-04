from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from stockroom.credentials import MemoryCredentialStore
from stockroom.host.window_geometry import (
    MonitorGeometry,
    PhysicalRect,
    WindowGeometry,
    WindowShowState,
)
from stockroom.host.window_runtime import (
    ProductionWindowReplacement,
    ReleaseWindowRuntimeError,
)
from stockroom.host.window_supervisor import (
    ProviderDownloadEvent,
    ProviderLeaseHandshake,
    WindowHostHealth,
    WindowHostIdentity,
    WindowHostLaunch,
)
from stockroom.store.machine_config import MachineConfig
from stockroom.store.ui_session import default_snapshot
from stockroom.update import AcceptedRelease

TOKEN = "A" * 43


def _geometry(left: int = 80) -> WindowGeometry:
    return WindowGeometry(
        normal_bounds=PhysicalRect(left, 60, left + 1_200, 860),
        show_state=WindowShowState.NORMAL,
        monitor=MonitorGeometry(
            device_name=r"\\.\DISPLAY1",
            work_area=PhysicalRect(0, 0, 1_920, 1_040),
            dpi=96,
        ),
    )


def _accepted(tmp_path: Path, release_id: str) -> AcceptedRelease:
    root = tmp_path / release_id
    root.mkdir()
    return AcceptedRelease(
        release_id=release_id,
        directory=root,
        manifest_path=root / "Release Manifest.json",
        manifest_sha256=release_id.removeprefix("release-").ljust(64, "0")[:64],
        manifest=cast(Any, SimpleNamespace(release_id=release_id)),
        members={},
    )


class _Client:
    def __init__(
        self,
        release_id: str,
        *,
        process_id: int,
        snapshot: dict,
        geometry: WindowGeometry,
    ) -> None:
        self.identity = WindowHostIdentity(
            release_id=release_id,
            process_id=process_id,
            parent_process_id=77,
            window_handle=process_id + 10_000,
            profile_id=f"window-{process_id:032x}",
            renderer="edgechromium",
        )
        self._snapshot = copy.deepcopy(snapshot)
        self._geometry = geometry
        self._hidden = True
        self._active = True
        self._exit: int | None = None
        self._close_requested = False
        self.commands: list[str] = []

    @property
    def active(self) -> bool:
        return self._active

    def prepare_hidden(self) -> None:
        self.commands.append("hide")
        self._hidden = True

    def show(self) -> None:
        self.commands.append("show")
        self._hidden = False

    def focus(self) -> None:
        self.commands.append("focus")

    def provider_endpoint(self) -> str:
        self.commands.append("provider-endpoint")
        return "http://127.0.0.1:43127"

    def begin_provider_lease(
        self,
        lease_id: str,
        *,
        staging_root: str = "",
        component_id: str = "",
        manufacturer: str = "",
        mpn: str = "",
        provider_id: str = "",
    ) -> ProviderLeaseHandshake:
        self.commands.append(
            f"provider-lease-begin:{lease_id}:{staging_root}:{component_id}:"
            f"{manufacturer}:{mpn}:{provider_id}"
        )
        return ProviderLeaseHandshake(
            lease_id,
            7,
            "http://127.0.0.1:43127",
            staging_root=staging_root,
            component_id=component_id,
            manufacturer=manufacturer,
            mpn=mpn,
            provider_id=provider_id,
        )

    def release_provider_lease(self, lease_id: str, generation: int) -> bool:
        self.commands.append(f"provider-lease-release:{lease_id}:{generation}")
        return True

    def provider_download_events(
        self,
        lease_id: str,
        generation: int,
        *,
        after_sequence: int = 0,
    ) -> tuple[ProviderDownloadEvent, ...]:
        self.commands.append(
            f"provider-download-events:{lease_id}:{generation}:{after_sequence}"
        )
        return (
            ProviderDownloadEvent(
                sequence=19,
                lease_id=lease_id,
                generation=generation,
                component_id="component-9",
                manufacturer="Exact Manufacturer",
                mpn="MPN-9",
                provider_id="digikey",
                operation_id="operation-1",
                phase="terminal",
                state="completed",
                uri="https://provider.example.test/model.zip",
                suggested_file_name="model.zip",
                result_file_path=r"C:\Capture\model.zip",
                mime_type="application/zip",
                interrupt_reason="",
                total_bytes=120,
                bytes_received=120,
            ),
        )

    def show_provider(self, lease_id: str, generation: int) -> None:
        self.commands.append(f"provider-show:{lease_id}:{generation}")

    def hide_provider(self, lease_id: str, generation: int) -> None:
        self.commands.append(f"provider-hide:{lease_id}:{generation}")

    def provider_current_url(self, lease_id: str, generation: int) -> str:
        self.commands.append(f"provider-current-url:{lease_id}:{generation}")
        return "https://provider.example.test/part"

    def navigate_provider(self, lease_id: str, generation: int, url: str) -> None:
        self.commands.append(f"provider-navigate:{lease_id}:{generation}:{url}")

    def provider_document_state(
        self,
        lease_id: str,
        generation: int,
        *,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
    ) -> dict[str, object]:
        self.commands.append(
            f"provider-document-state:{lease_id}:{generation}:"
            f"{','.join(ready_selectors)}:{','.join(ready_texts)}"
        )
        return {
            "ready": True,
            "challenge": False,
            "account_verification": False,
            "provider_error": False,
            "provider_ready": True,
        }

    def health(self) -> WindowHostHealth:
        return WindowHostHealth(
            window_handle=self.identity.window_handle,
            current_url="http://127.0.0.1:43110/",
            hidden=self._hidden,
            visible=not self._hidden,
            renderer="edgechromium",
            close_requested=self._close_requested,
        )

    def export_session(self) -> object:
        return {
            "ui_export": {"snapshot": copy.deepcopy(self._snapshot)},
            "theme": "dark",
            "api_healthy": True,
            "event_stream_healthy": True,
            "geometry": self._geometry.to_config(),
        }

    def shutdown(self) -> None:
        self.commands.append("shutdown")
        self._active = False
        self._exit = 0

    def close(self) -> None:
        self.commands.append("close")
        self._active = False
        self._exit = 0

    def wait_for_exit(self, timeout: float | None = None) -> int | None:
        del timeout
        return self._exit


class _Supervisor:
    def __init__(self, clients: dict[str, _Client]) -> None:
        self.clients = clients
        self.launches: list[str] = []

    def launch(
        self,
        launch: WindowHostLaunch,
        *,
        handoff_id: str,
        base_url: str,
        api_credential: str,
    ) -> _Client:
        assert handoff_id
        assert base_url == "http://127.0.0.1:43110"
        assert api_credential == TOKEN
        self.launches.append(launch.release_id)
        return self.clients[launch.release_id]


def _runtime(
    tmp_path: Path,
    *,
    candidate_snapshot: dict | None = None,
) -> tuple[ProductionWindowReplacement, _Client, _Client, AcceptedRelease]:
    credentials = MemoryCredentialStore("window-runtime")
    path = tmp_path / "Config" / "config.json"
    config = MachineConfig(onboarded=True)
    config.save(path, credential_store=credentials)
    config = MachineConfig.load(path, credential_store=credentials)

    initial = _accepted(tmp_path, "release-1")
    candidate = _accepted(tmp_path, "release-2")
    snapshot = default_snapshot()
    snapshot["route"] = "settings"
    snapshot["event_sequence"] = 91
    snapshot["selected_ids"]["workflow_batch"] = "batch-91"
    old = _Client(
        initial.release_id,
        process_id=101,
        snapshot=snapshot,
        geometry=_geometry(),
    )
    new = _Client(
        candidate.release_id,
        process_id=202,
        snapshot=candidate_snapshot or snapshot,
        geometry=_geometry(),
    )
    supervisor = _Supervisor({initial.release_id: old, candidate.release_id: new})
    runtime = ProductionWindowReplacement(
        initial,
        public_base_url="http://127.0.0.1:43110",
        api_credential=TOKEN,
        config=config,
        supervisor=supervisor,
        launch_factory=lambda release: WindowHostLaunch(
            release_id=release.release_id,
            command_prefix=("fake-window-host.exe",),
            working_directory=release.directory,
        ),
        id_factory=lambda: "11111111-1111-4111-8111-111111111111",
    )
    return runtime, old, new, candidate


def test_initial_window_starts_hidden_persists_continuity_then_shows(
    tmp_path: Path,
) -> None:
    runtime, old, _new, _candidate = _runtime(tmp_path)

    continuity = runtime.start_initial()

    assert runtime.active_release_id == "release-1"
    assert old.commands == ["hide", "show", "focus"]
    assert continuity.route == "settings"
    assert continuity.workflow_batch == "batch-91"
    assert continuity.event_sequence == 91
    persisted = (tmp_path / "Config" / "ui-session.json").read_text(encoding="utf-8")
    assert '"route":"settings"' in persisted
    runtime.close()


def test_active_native_window_observation_is_exact_and_read_only(
    tmp_path: Path,
) -> None:
    runtime, old, _new, _candidate = _runtime(tmp_path)
    runtime.start_initial()
    session_path = tmp_path / "Config" / "ui-session.json"
    before = session_path.read_bytes()

    observation = runtime.observe_active()

    assert observation.identity == old.identity
    assert observation.health.window_handle == old.identity.window_handle
    assert observation.health.visible is True
    assert observation.exported.snapshot["route"] == "settings"
    assert observation.exported.theme == "dark"
    assert session_path.read_bytes() == before
    runtime.close()


def test_provider_browser_surface_is_one_scoped_in_app_lease(
    tmp_path: Path,
) -> None:
    runtime, old, _new, _candidate = _runtime(tmp_path)
    runtime.start_initial()

    staging_root = str(tmp_path / "Staging")
    with runtime.provider_browser_surface(
        staging_root=staging_root,
        component_id="component-9",
        manufacturer="Exact Manufacturer",
        mpn="MPN-9",
        provider_id="digikey",
    ) as lease:
        assert lease.endpoint == "http://127.0.0.1:43127"
        assert lease.lease_id == "11111111-1111-4111-8111-111111111111"
        assert lease.generation == 7
        assert lease.staging_root == staging_root
        assert lease.component_id == "component-9"
        assert lease.manufacturer == "Exact Manufacturer"
        assert lease.mpn == "MPN-9"
        assert lease.provider_id == "digikey"
        assert old.commands[-1:] == [
            "provider-lease-begin:11111111-1111-4111-8111-111111111111:"
            f"{staging_root}:component-9:Exact Manufacturer:MPN-9:digikey"
        ]
        lease.show()
        lease.show()
        assert old.commands[-2:] == [
            "provider-show:11111111-1111-4111-8111-111111111111:7",
            "provider-show:11111111-1111-4111-8111-111111111111:7",
        ]
        lease.hide()
        lease.hide()
        assert old.commands[-2:] == [
            "provider-hide:11111111-1111-4111-8111-111111111111:7",
            "provider-hide:11111111-1111-4111-8111-111111111111:7",
        ]
        lease.show()
        assert old.commands[-1] == (
            "provider-show:11111111-1111-4111-8111-111111111111:7"
        )
        assert lease.current_url() == "https://provider.example.test/part"
        lease.navigate("https://provider.example.test/next")
        state = lease.document_state(
            ready_selectors=("#download",),
            ready_texts=("download",),
        )
        assert state["provider_ready"] is True
        assert lease.security_state()["challenge"] is False
        downloads = lease.download_events(after_sequence=4)
        assert downloads[0].result_file_path == r"C:\Capture\model.zip"
        runtime.show_active_provider_browser()
        assert old.commands[-1] == (
            "provider-show:11111111-1111-4111-8111-111111111111:7"
        )

    assert old.commands[-1] == (
        "provider-lease-release:11111111-1111-4111-8111-111111111111:7"
    )
    runtime.close()


def test_incomplete_provider_surface_can_be_retained_then_closed_after_completion(
    tmp_path: Path,
) -> None:
    runtime, old, _new, _candidate = _runtime(tmp_path)
    runtime.start_initial()

    with runtime.provider_browser_surface() as lease:
        lease.retain()

    assert not any(command.startswith("provider-lease-release:") for command in old.commands)
    runtime.show_active_provider_browser()
    assert old.commands[-1] == (
        "provider-show:11111111-1111-4111-8111-111111111111:7"
    )

    runtime.close_active_provider_browser()

    assert old.commands[-1] == (
        "provider-lease-release:11111111-1111-4111-8111-111111111111:7"
    )
    with pytest.raises(ReleaseWindowRuntimeError, match="no active lease"):
        runtime.show_active_provider_browser()
    runtime.close()


def test_active_native_window_observation_fails_after_runtime_close(
    tmp_path: Path,
) -> None:
    runtime, _old, _new, _candidate = _runtime(tmp_path)
    runtime.start_initial()
    runtime.close()

    with pytest.raises(ReleaseWindowRuntimeError, match="unavailable"):
        runtime.observe_active()


def test_two_phase_replacement_swaps_only_on_commit_and_retires_old(
    tmp_path: Path,
) -> None:
    runtime, old, new, candidate = _runtime(tmp_path)
    runtime.start_initial()

    adoption = runtime.begin(candidate)

    assert runtime.active_release_id == "release-1"
    assert old.commands[-1] == "hide"
    assert new.commands == ["hide", "show", "focus"]

    receipt = runtime.commit(adoption)

    assert receipt.release_id == "release-2"
    assert runtime.active_release_id == "release-2"
    assert old.commands[-1] == "shutdown"
    runtime.close()


def test_mismatched_candidate_session_restores_old_and_stops_candidate(
    tmp_path: Path,
) -> None:
    mismatch = default_snapshot()
    mismatch["route"] = "components"
    runtime, old, new, candidate = _runtime(
        tmp_path,
        candidate_snapshot=mismatch,
    )
    runtime.start_initial()

    with pytest.raises(Exception, match="window handoff failed"):
        runtime.begin(candidate)

    assert runtime.active_release_id == "release-1"
    assert old.commands[-2:] == ["show", "focus"]
    assert new.commands[-2:] == ["hide", "shutdown"]
    runtime.close()


def test_active_window_exit_is_not_confused_with_update_retirement(
    tmp_path: Path,
) -> None:
    runtime, old, new, candidate = _runtime(tmp_path)
    runtime.start_initial()
    adoption = runtime.begin(candidate)
    runtime.commit(adoption)
    new._close_requested = True

    assert runtime.wait_until_closed() == 0
    assert old._exit == 0
    assert new.commands[-1] == "shutdown"
    runtime.close()


def test_unexpected_active_window_failure_is_explicit(tmp_path: Path) -> None:
    runtime, old, _new, _candidate = _runtime(tmp_path)
    runtime.start_initial()
    old._exit = 23
    old._active = False

    with pytest.raises(ReleaseWindowRuntimeError, match="without authenticated"):
        runtime.wait_until_closed()
    runtime.close()
