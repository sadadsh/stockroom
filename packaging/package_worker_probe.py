"""Exercise the exact frozen release worker through a managed handoff round trip."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from stockroom.altium.converter import convert_pcad_ascii
from stockroom.api.serve import pick_free_port
from stockroom.host.proxy import SwitchableBackendProxy
from stockroom.host.release_runtime import HostReleaseBoundary
from stockroom.host.run import _serve_in_thread
from stockroom.host.service_authority import ContextServiceAuthority
from stockroom.service import ServiceMode
from stockroom.update import ReleaseHealthStage, verify_local_release_set


class PackagedWorkerProbeError(RuntimeError):
    """The immutable ``--port`` worker failed its real authority handoff."""


class _Lifecycle:
    def start(self, control, fence):
        del control
        return fence

    def stop(self, handle, *, timeout: float) -> None:
        del handle, timeout


def _atomic_receipt(path: Path, document: dict[str, object]) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise PackagedWorkerProbeError("worker probe receipt path is unsafe")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run_packaged_worker_probe(
    *,
    worker_executable: Path,
    release_directory: Path,
    release_id: str,
    manifest_sha256: str,
    receipt_path: Path,
    config_root: Path,
    local_app_data: Path,
    roaming_app_data: Path,
) -> None:
    if sys.platform != "win32":
        raise PackagedWorkerProbeError("packaged worker proof requires Windows")
    worker_executable = Path(worker_executable).resolve(strict=True)
    release_directory = Path(release_directory).resolve(strict=True)
    expected_worker = (
        release_directory / "Backend" / "Stockroom Worker.exe"
    ).resolve(strict=True)
    if worker_executable != expected_worker:
        raise PackagedWorkerProbeError(
            "worker probe must launch the release manifest's exact backend"
        )
    candidate = verify_local_release_set(
        release_directory,
        expected_release_id=release_id,
        expected_manifest_sha256=manifest_sha256,
    )
    backend_members = [
        candidate.members[member.path]
        for member in candidate.manifest.members
        if member.kind == "backend"
    ]
    if backend_members != [worker_executable]:
        raise PackagedWorkerProbeError(
            "release manifest does not bind the probed worker executable"
        )
    converter_members = [
        candidate.members[member.path]
        for member in candidate.manifest.members
        if member.kind == "cad-converter"
    ]
    if len(converter_members) != 1:
        raise PackagedWorkerProbeError(
            "release manifest does not bind exactly one native CAD converter"
        )
    converter_executable = converter_members[0]
    expected_converter = (
        release_directory / "Tools" / "CadConverter" / "Stockroom.CadConverter.exe"
    ).resolve(strict=True)
    if converter_executable != expected_converter:
        raise PackagedWorkerProbeError(
            "release manifest binds the native CAD converter at an unexpected path"
        )
    probe_lia = Path(__file__).with_name("Cad Converter Probe.lia").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="Stockroom Packaged CAD Probe ") as temporary:
        converted = convert_pcad_ascii(
            probe_lia,
            Path(temporary) / "Native Altium",
            converter_executable=converter_executable,
        )
        if (
            converted.symbol_entries != ("STOCKROOM-CAD-PROBE",)
            or converted.footprint_entries != ("STOCKROOM_PROBE",)
        ):
            raise PackagedWorkerProbeError(
                "packaged native CAD converter failed its deterministic conversion canary"
            )
        converter_sha256 = hashlib.sha256(converter_executable.read_bytes()).hexdigest()

    os.environ["STOCKROOM_CONFIG_DIR"] = str(Path(config_root).resolve(strict=True))
    os.environ["LOCALAPPDATA"] = str(Path(local_app_data).resolve(strict=True))
    os.environ["APPDATA"] = str(Path(roaming_app_data).resolve(strict=True))
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    service_root = Path(local_app_data).resolve() / "Stockroom" / "Service State"
    workflow_database = service_root / "Workflow.sqlite"
    prior_release_id = "release-package-probe-prior"
    context = SimpleNamespace()
    authority = ContextServiceAuthority(
        context,
        release_id=prior_release_id,
        control_database=(service_root / "Control.sqlite").resolve(),
        lifecycle=_Lifecycle(),
        start_as_coordinator=True,
    )
    initial_generation = authority.snapshot().generation

    local = FastAPI()

    @local.get("/api/health")
    def health() -> dict[str, object]:
        snapshot = authority.snapshot()
        return {
            "coordinator_status": snapshot.status.value,
            "release_id": prior_release_id,
            "service_generation": snapshot.generation,
            "service_mode": snapshot.mode.value,
            "status": "ok",
        }

    proxy = SwitchableBackendProxy(local)
    port = pick_free_port()
    public_base_url = f"http://127.0.0.1:{port}"
    server, server_thread = _serve_in_thread(proxy, port)
    boundary = HostReleaseBoundary(
        proxy,
        public_base_url=public_base_url,
        token="packaged-worker-probe-token",
        local_release_id=prior_release_id,
        reload_window=lambda _url: None,
        local_service_authority=authority,
        workflow_database=workflow_database,
        startup_timeout_seconds=60.0,
        post_adoption_probes=1,
        probe_interval_seconds=0.05,
        drain_timeout_seconds=30.0,
        stop_timeout_seconds=10.0,
    )
    current = SimpleNamespace(release_id=prior_release_id)
    worker = None
    try:
        worker = boundary.launch_shadow(candidate, generation=1)
        if Path(worker.process.args[0]).resolve() != worker_executable:
            raise PackagedWorkerProbeError(
                "managed boundary launched a different worker executable"
            )
        boundary.check(
            candidate,
            worker,
            stage=ReleaseHealthStage.PRE_ADOPTION,
            generation=1,
        )
        drained = boundary.drain(current, generation=1)
        adopted = boundary.adopt(
            candidate,
            current,
            worker,
            drained,
            generation=1,
        )
        boundary.check(
            candidate,
            worker,
            stage=ReleaseHealthStage.POST_ADOPTION,
            generation=1,
        )
        candidate_health = httpx.get(
            f"{public_base_url}/api/health",
            timeout=15.0,
        ).json()
        if candidate_health != {
            "coordinator_status": "active",
            "release_id": release_id,
            "service_generation": adopted.candidate_service_generation,
            "service_mode": "coordinator",
            "status": "ok",
        }:
            raise PackagedWorkerProbeError(
                "stable route did not adopt the packaged worker: "
                f"{candidate_health!r}"
            )
        boundary.rollback(
            candidate,
            current,
            adopted,
            generation=1,
        )
        restored = authority.snapshot()
        prior_health = httpx.get(
            f"{public_base_url}/api/health",
            timeout=15.0,
        ).json()
        if (
            prior_health
            != {
                "coordinator_status": "active",
                "release_id": prior_release_id,
                "service_generation": restored.generation,
                "service_mode": "coordinator",
                "status": "ok",
            }
            or restored.mode is not ServiceMode.COORDINATOR
            or restored.generation != initial_generation + 2
        ):
            raise PackagedWorkerProbeError(
                "packaged worker rollback did not restore the prior authority and route: "
                f"{prior_health!r}"
            )
        boundary.stop_shadow(worker, generation=1)
        worker = None
        _atomic_receipt(
            Path(receipt_path),
            {
                "adopted": True,
                "candidate_generation": adopted.candidate_service_generation,
                "candidate_release_id": release_id,
                "exact_cad_converter_sha256": converter_sha256,
                "exact_worker_sha256": hashlib.sha256(
                    worker_executable.read_bytes()
                ).hexdigest(),
                "initial_generation": initial_generation,
                "prior_release_id": prior_release_id,
                "restored_generation": restored.generation,
                "rolled_back": True,
                "schema": "stockroom-packaged-worker-handoff/1",
            },
        )
    finally:
        try:
            boundary.close()
        finally:
            server.should_exit = True
            server_thread.join(timeout=10.0)
    if worker is not None:
        raise PackagedWorkerProbeError(
            "packaged worker remained owned after probe shutdown"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-executable", required=True, type=Path)
    parser.add_argument("--release-directory", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--config-root", required=True, type=Path)
    parser.add_argument("--local-app-data", required=True, type=Path)
    parser.add_argument("--roaming-app-data", required=True, type=Path)
    args = parser.parse_args()
    run_packaged_worker_probe(
        worker_executable=args.worker_executable,
        release_directory=args.release_directory,
        release_id=args.release_id,
        manifest_sha256=args.manifest_sha256,
        receipt_path=args.receipt,
        config_root=args.config_root,
        local_app_data=args.local_app_data,
        roaming_app_data=args.roaming_app_data,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
