from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root

import packaging.stockroom_launcher as stockroom_launcher
from packaging.release_bundle import ReleaseBundleError, build_release_bundle
from packaging.release_feed import (
    ReleaseFeedError,
    _RepositoryFetcher,
    build_release_feed,
)
from stockroom import _packaged_build_identity
from stockroom.host.release_runtime import (
    HostManifestRehearsal,
    verified_packaged_release_identity,
)
from stockroom.service import MutexAcquireResult, ServiceControl, ServiceMode
from stockroom.update import (
    ImmutableReleaseStore,
    ReleaseActivationRole,
    ReleaseActivator,
    ReleaseHealthStage,
    verify_local_release_set,
)
from stockroom.update.manifest import ReleaseManifest
from stockroom.update.trusted_repository import TrustedReleaseRepository

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPOSITORY_ROOT / "packaging" / "stockroom_launcher.py"
SPEC = REPOSITORY_ROOT / "packaging" / "stockroom.spec"
BUILD_SCRIPT = REPOSITORY_ROOT / "packaging" / "Build-Windows-Package.ps1"
WORKER_PROBE = REPOSITORY_ROOT / "packaging" / "package_worker_probe.py"
_SID = "S-1-5-21-111111111-222222222-333333333-1001"


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _window_host_publish(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Stockroom.WindowHost.exe").write_bytes(b"MZwindow-host")
    (root / "Stockroom.WindowHost.dll").write_bytes(b"window-host-runtime")
    return root


def _cad_converter_publish(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Stockroom.CadConverter.exe").write_bytes(b"MZcad-converter")
    (root / "Stockroom.CadConverter.dll").write_bytes(b"cad-converter-runtime")
    return root


def _build_fixture(executable: Path, bundle: Path) -> dict[str, str]:
    return build_release_bundle(
        mode="Fixture",
        executable=executable,
        window_host_root=_window_host_publish(executable.parent / "Window Host Publish"),
        cad_converter_root=_cad_converter_publish(executable.parent / "CAD Converter Publish"),
        bundle_root=bundle,
        version="1.2.3.4",
        minimum_host_version="1.0.0.0",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=None,
    )


def test_fixture_release_bundle_is_complete_valid_and_reproducible(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZ" + bytes(range(256)))
    first = tmp_path / "First" / "Update"
    second = tmp_path / "Second" / "Update"

    first_evidence = _build_fixture(executable, first)
    second_evidence = _build_fixture(executable, second)

    assert first_evidence == second_evidence
    assert _files(first) == _files(second)
    assert verified_packaged_release_identity(first) == "release-1.2.3.4"
    manifest = ReleaseManifest.from_bytes(
        (
            first
            / "Initial Release"
            / "release-1.2.3.4"
            / "Release Manifest.json"
        ).read_bytes()
    )
    assert manifest.manifest_version == 2
    assert manifest.minimum_host_version == "1.0.0.0"
    assert first_evidence["minimum_host_version"] == "1.0.0.0"
    assert manifest.package_version == "1.2.3.4"
    assert manifest.protocol_version == 1
    assert manifest.supports_direct_activation_from("release-bootstrap")
    assert {member.kind for member in manifest.members} == {
        "backend",
        "cad-converter",
        "cad-converter-runtime",
        "license",
        "notice",
        "sbom",
    }
    assert not any(member.path.startswith("WindowHost/") for member in manifest.members)
    assert first_evidence["window_host_sha256"] == hashlib.sha256(
        b"MZwindow-host"
    ).hexdigest()
    assert next(member for member in manifest.members if member.kind == "backend").path == (
        "Backend/Stockroom Worker.exe"
    )
    assert next(
        member for member in manifest.members if member.kind == "cad-converter"
    ).path == "Tools/CadConverter/Stockroom.CadConverter.exe"
    assert first_evidence["cad_converter_sha256"] == hashlib.sha256(
        b"MZcad-converter"
    ).hexdigest()
    support = first / "Initial Release" / "release-1.2.3.4" / "Support"
    assert "OpenMcdf 3.1.4" in (support / "Third Party Notices.txt").read_text(
        encoding="utf-8"
    )
    assert (support / "Licenses" / "AltiumSharp Apache-2.0.txt").read_text(
        encoding="utf-8"
    ).startswith("Apache License")


def test_production_bundle_requires_a_valid_offline_root(tmp_path: Path) -> None:
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZfixture")
    with pytest.raises(
        ReleaseBundleError,
        match="offline-authored pinned TUF root",
    ):
        build_release_bundle(
            mode="Production",
            executable=executable,
            window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
            cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
            bundle_root=tmp_path / "Production",
            version="1.2.3.4",
            minimum_host_version="1.0.0.0",
            feed_base_uri="https://updates.stockroom.test/x64",
            source_revision="0123456789012345678901234567890123456789",
            source_date_epoch=1704067200,
            tuf_root_path=None,
        )


@pytest.mark.parametrize(
    ("minimum_host_version", "message"),
    [
        ("1.2", "canonical four-part numeric version"),
        ("1.2.3.5", "cannot exceed the packaged host version"),
    ],
)
def test_release_bundle_rejects_an_invalid_host_abi_floor(
    tmp_path: Path,
    minimum_host_version: str,
    message: str,
) -> None:
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZhost-floor")

    with pytest.raises(ReleaseBundleError, match=message):
        build_release_bundle(
            mode="Fixture",
            executable=executable,
            window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
            cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
            bundle_root=tmp_path / "Update",
            version="1.2.3.4",
            minimum_host_version=minimum_host_version,
            feed_base_uri="https://updates.example.invalid/stockroom/x64",
            source_revision="0123456789012345678901234567890123456789",
            source_date_epoch=1704067200,
            tuf_root_path=None,
        )


def test_fixture_release_bundle_authors_explicit_predecessor_chain(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZpredecessors")
    bundle = tmp_path / "Update"
    evidence = build_release_bundle(
        mode="Fixture",
        executable=executable,
        window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
        cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
        bundle_root=bundle,
        version="2.0.0.0",
        minimum_host_version="1.0.0.0",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=None,
        rollback_release_id="release-1.2.3.4",
        compatible_from_release_ids=(
            "release-bootstrap",
            "release-1.2.3.4",
            "release-1.5.0.0",
        ),
    )
    manifest = ReleaseManifest.from_bytes(
        (
            bundle
            / "Initial Release"
            / "release-2.0.0.0"
            / "Release Manifest.json"
        ).read_bytes()
    )
    assert manifest.rollback_release_id == "release-1.2.3.4"
    assert manifest.compatible_from_release_ids == (
        "release-bootstrap",
        "release-1.2.3.4",
        "release-1.5.0.0",
    )
    assert manifest.supports_direct_activation_from("release-1.2.3.4")
    assert evidence["rollback_release_id"] == "release-1.2.3.4"


def test_fixture_feed_is_a_complete_consistent_snapshot_repository(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZsigned-feed")
    bundle = tmp_path / "Update"
    bundle_evidence = _build_fixture(executable, bundle)
    release_directory = (
        bundle / "Initial Release" / bundle_evidence["release_id"]
    )
    repository = tmp_path / "Repository"
    archive = tmp_path / "Stockroom_TUF_Feed_1.2.3.4.zip"
    evidence_path = tmp_path / "Release Feed Evidence.json"

    evidence = build_release_feed(
        mode="Fixture",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        root_path=bundle / "Root.json",
        release_directory=release_directory,
        release_id=bundle_evidence["release_id"],
        expected_manifest_sha256=bundle_evidence["manifest_sha256"],
        metadata_version=9,
        repository_root=repository,
        archive_path=archive,
        evidence_path=evidence_path,
    )

    assert evidence["schema"] == "stockroom-release-feed/1"
    assert evidence["metadata_version"] == 9
    assert evidence["validation"] == {
        "consistent_snapshot_layout": True,
        "online_role_thresholds": True,
        "trusted_updater_round_trip": True,
    }
    inventory_paths = {
        item["path"] for item in evidence["repository_inventory"]
    }
    assert {
        "metadata/1.root.json",
        "metadata/9.snapshot.json",
        "metadata/9.targets.json",
        "metadata/timestamp.json",
    }.issubset(inventory_paths)
    authored_targets = Metadata.from_bytes(
        (repository / "metadata" / "9.targets.json").read_bytes()
    )
    assert (
        evidence["metadata"]["targets"]["expires"]
        == authored_targets.signed.expires.isoformat()
    )
    assert all(
        path.startswith(("metadata/", "targets/")) for path in inventory_paths
    )
    with zipfile.ZipFile(archive) as feed_archive:
        assert set(feed_archive.namelist()) == inventory_paths

    staged = TrustedReleaseRepository(
        bootstrap_root=(bundle / "Root.json").read_bytes(),
        metadata_base_url="https://metadata.stockroom-feed.invalid/",
        target_base_url="https://targets.stockroom-feed.invalid/",
        state_directory=tmp_path / "Independent State",
        staging_directory=tmp_path / "Independent Staging",
        fetcher=_RepositoryFetcher(repository),
    ).stage_release()
    assert staged.release_id == bundle_evidence["release_id"]
    assert staged.manifest_sha256 == bundle_evidence["manifest_sha256"]


def test_production_feed_requires_and_uses_root_authorized_online_keys(
    tmp_path: Path,
) -> None:
    private_keys = {
        role: Ed25519PrivateKey.generate()
        for role in ("root", "targets", "snapshot", "timestamp")
    }
    signers = {
        role: CryptoSigner(private_key)
        for role, private_key in private_keys.items()
    }
    root = Root(
        version=4,
        expires=datetime.now(timezone.utc) + timedelta(days=365),
        consistent_snapshot=True,
    )
    for role, signer in signers.items():
        root.add_key(signer.public_key, role)
    root_metadata = Metadata(root)
    root_metadata.sign(signers["root"])
    root_path = tmp_path / "Root.json"
    root_path.write_bytes(root_metadata.to_bytes())
    key_paths: dict[str, Path] = {}
    for role in ("targets", "snapshot", "timestamp"):
        key_path = tmp_path / f"{role}.pem"
        key_path.write_bytes(
            private_keys[role].private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        key_paths[role] = key_path

    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZproduction-signed-feed")
    bundle = tmp_path / "Update"
    bundle_evidence = build_release_bundle(
        mode="Production",
        executable=executable,
        window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
        cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
        bundle_root=bundle,
        version="7.8.9.10",
        minimum_host_version="7.0.0.0",
        feed_base_uri="https://updates.stockroom.test/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=root_path,
        rollback_release_id="release-7.8.9.9",
        compatible_from_release_ids=("release-7.8.9.9",),
    )
    unauthorized_key = Ed25519PrivateKey.generate()
    unauthorized_path = tmp_path / "unauthorized-targets.pem"
    unauthorized_path.write_bytes(
        unauthorized_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    with pytest.raises(
        ReleaseFeedError,
        match="targets TUF signing key is not authorized",
    ):
        build_release_feed(
            mode="Production",
            feed_base_uri="https://updates.stockroom.test/x64",
            root_path=root_path,
            release_directory=(
                bundle / "Initial Release" / bundle_evidence["release_id"]
            ),
            release_id=bundle_evidence["release_id"],
            expected_manifest_sha256=bundle_evidence["manifest_sha256"],
            metadata_version=14,
            repository_root=tmp_path / "Rejected Repository",
            archive_path=tmp_path / "Rejected Feed.zip",
            evidence_path=tmp_path / "Rejected Evidence.json",
            targets_key_paths=(unauthorized_path,),
            snapshot_key_paths=(key_paths["snapshot"],),
            timestamp_key_paths=(key_paths["timestamp"],),
        )

    evidence = build_release_feed(
        mode="Production",
        feed_base_uri="https://updates.stockroom.test/x64",
        root_path=root_path,
        release_directory=(
            bundle / "Initial Release" / bundle_evidence["release_id"]
        ),
        release_id=bundle_evidence["release_id"],
        expected_manifest_sha256=bundle_evidence["manifest_sha256"],
        metadata_version=14,
        repository_root=tmp_path / "Production Repository",
        archive_path=tmp_path / "Production Feed.zip",
        evidence_path=tmp_path / "Production Feed Evidence.json",
        targets_key_paths=(key_paths["targets"],),
        snapshot_key_paths=(key_paths["snapshot"],),
        timestamp_key_paths=(key_paths["timestamp"],),
    )

    assert evidence["mode"] == "production"
    assert evidence["root"]["version"] == 4
    assert evidence["deployment"] == {
        "external_action_required": True,
        "feed_base_uri": "https://updates.stockroom.test/x64",
        "metadata_base_url": "https://updates.stockroom.test/x64/metadata/",
        "metadata_subdirectory": "metadata/",
        "state": "staged-not-deployed",
        "target_base_url": "https://updates.stockroom.test/x64/targets/",
        "targets_subdirectory": "targets/",
    }
    assert {
        role: evidence["roles"][role]["signing_keyids"]
        for role in ("targets", "snapshot", "timestamp")
    } == {
        role: [signers[role].public_key.keyid]
        for role in ("targets", "snapshot", "timestamp")
    }


class _Identity:
    def current_sid(self) -> str:
        return _SID


class _Storage:
    def validate(self, database: Path) -> Path:
        return database.resolve(strict=False)


class _Mutex:
    held = False

    def try_acquire(self) -> MutexAcquireResult:
        if self.held:
            return MutexAcquireResult.BUSY
        self.held = True
        return MutexAcquireResult.CREATED

    def release(self) -> None:
        self.held = False


class _MutexFactory:
    def __init__(self) -> None:
        self.mutex = _Mutex()

    def open_current_user(self, *, name: str, sid: str) -> _Mutex:
        del name, sid
        return self.mutex


class _ActivationBoundary:
    def __init__(self, current_release_id: str) -> None:
        self.live_release_id = current_release_id

    def rehearse(self, candidate, current, *, generation: int) -> None:
        HostManifestRehearsal().rehearse(
            candidate,
            current,
            generation=generation,
        )

    def rehearse_rollback(self, candidate, current, *, generation: int) -> None:
        HostManifestRehearsal().rehearse_rollback(
            candidate,
            current,
            generation=generation,
        )

    def launch_shadow(self, candidate, *, generation: int):
        return (candidate.release_id, generation)

    def stop_shadow(self, launch_handle, *, generation: int) -> None:
        del launch_handle, generation

    def check(
        self,
        candidate,
        launch_handle,
        *,
        stage: ReleaseHealthStage,
        generation: int,
    ) -> None:
        del candidate, launch_handle, stage, generation

    def drain(self, current, *, generation: int):
        assert self.live_release_id == current.release_id
        return (current.release_id, generation)

    def resume(self, current, drain_receipt, *, generation: int) -> None:
        del drain_receipt, generation
        assert self.live_release_id == current.release_id

    def adopt(
        self,
        candidate,
        current,
        launch_handle,
        drain_receipt,
        *,
        generation: int,
    ):
        del launch_handle, drain_receipt, generation
        assert self.live_release_id == current.release_id
        self.live_release_id = candidate.release_id
        return (current.release_id, candidate.release_id)

    def rollback(self, candidate, current, adoption_receipt, *, generation: int) -> None:
        del adoption_receipt, generation
        assert self.live_release_id == candidate.release_id
        self.live_release_id = current.release_id

    def commit(self, candidate, current, adoption_receipt, *, generation: int) -> None:
        del current, adoption_receipt, generation
        assert self.live_release_id == candidate.release_id


def test_persisted_v1_release_activates_packaged_v2_in_shared_data_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import stockroom.host.release_runtime as release_runtime

    monkeypatch.setattr(release_runtime, "__version__", "2.0.0.0")
    executable = tmp_path / "Stockroom.exe"
    executable.write_bytes(b"MZv1-v2-shared-root")
    v1_bundle = tmp_path / "V1 Bundle"
    v2_bundle = tmp_path / "V2 Bundle"
    build_release_bundle(
        mode="Fixture",
        executable=executable,
        window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
        cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
        bundle_root=v1_bundle,
        version="1.0.0.0",
        minimum_host_version="1.0.0.0",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=None,
    )
    build_release_bundle(
        mode="Fixture",
        executable=executable,
        window_host_root=_window_host_publish(tmp_path / "Window Host Publish"),
        cad_converter_root=_cad_converter_publish(tmp_path / "CAD Converter Publish"),
        bundle_root=v2_bundle,
        version="2.0.0.0",
        minimum_host_version="1.0.0.0",
        feed_base_uri="https://updates.example.invalid/stockroom/x64",
        source_revision="0123456789012345678901234567890123456789",
        source_date_epoch=1704067200,
        tuf_root_path=None,
        rollback_release_id="release-1.0.0.0",
        compatible_from_release_ids=(
            "release-bootstrap",
            "release-1.0.0.0",
        ),
    )

    releases = (tmp_path / "Shared Data Root" / "Releases").resolve()
    v1_directory = releases / "release-1.0.0.0"
    v2_directory = releases / "release-2.0.0.0"
    shutil.copytree(
        v1_bundle / "Initial Release" / v1_directory.name,
        v1_directory,
    )
    shutil.copytree(
        v2_bundle / "Initial Release" / v2_directory.name,
        v2_directory,
    )
    # Persisted installations authored before the predecessor-list feature carry
    # manifest v1. Re-author only its manifest envelope; immutable members remain
    # byte-for-byte the packaged v1 payload.
    v1_manifest_path = v1_directory / "Release Manifest.json"
    v1_document = json.loads(v1_manifest_path.read_text(encoding="ascii"))
    v1_document["manifest_version"] = 1
    v1_document.pop("compatible_from_release_ids")
    v1_bytes = (
        json.dumps(v1_document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")
    v1_manifest_path.write_bytes(v1_bytes)
    v1 = verify_local_release_set(
        v1_directory,
        expected_release_id=v1_directory.name,
        expected_manifest_sha256=hashlib.sha256(v1_bytes).hexdigest(),
    )
    v2_manifest_bytes = (v2_directory / "Release Manifest.json").read_bytes()
    v2 = verify_local_release_set(
        v2_directory,
        expected_release_id=v2_directory.name,
        expected_manifest_sha256=hashlib.sha256(v2_manifest_bytes).hexdigest(),
    )

    control = ServiceControl(
        (tmp_path / "Shared Data Root" / "Update State" / "Control.sqlite").resolve(),
        mode=ServiceMode.COORDINATOR,
        identity=_Identity(),
        mutex_factory=_MutexFactory(),
        storage_policy=_Storage(),
    )
    fence = control.acquire()
    store = ImmutableReleaseStore(
        releases_directory=releases,
        state_directory=(tmp_path / "Shared Data Root" / "Release State").resolve(),
    )
    store.initialize_active(v1, control=control, fence=fence)
    boundary = _ActivationBoundary(v1.release_id)
    activator = ReleaseActivator(
        control,
        store,
        role=ReleaseActivationRole.COORDINATOR,
        fence=fence,
        rehearsal=boundary,
        launcher=boundary,
        health=boundary,
        drain=boundary,
        adoption=boundary,
    )
    try:
        activated = activator.activate(v2)
        assert activated.current.release_id == "release-2.0.0.0"
        assert activated.previous is not None
        assert activated.previous.release_id == "release-1.0.0.0"
        assert store.verify_startup(control).current.release_id == "release-2.0.0.0"
        assert boundary.live_release_id == "release-2.0.0.0"
    finally:
        control.release(fence)
        control.close()


def test_frozen_worker_and_native_host_are_the_managed_runtime_contract() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    build = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "stockroom.launcher.launch import main as continuous_main" not in launcher
    assert "raise SystemExit(continuous_main())" not in launcher
    assert "stockroom.host.worker import main as worker_main" in launcher
    assert "--managed-host-probe" in launcher
    assert 'collect_submodules("stockroom")' in spec
    assert "COLLECT(" in spec
    assert 'name="Stockroom Worker"' in spec
    assert '"app/frontend-dist"' in spec
    assert '"fastapi"' not in spec.partition("excludes=[")[2]
    assert '"verified-offline-fixture"' in build
    assert '"stable-managed-release-runtime"' in build
    assert '"stockroom-native-host-launch/1"' in build
    assert '$probeStart.FileName = Join-Path $UnpackedRoot "WindowHost\\Stockroom.WindowHost.exe"' in build
    assert "immutable_release_bundle_round_trip = $true" in build
    assert "managed_service_authority = $true" in build
    assert "workflow_coordinator_running = $true" in build
    assert "packaged_worker_handoff = $true" in build
    assert "package_worker_probe.py" in build
    assert "signed_tuf_release_feed = $true" in build
    assert '"packaging.release_feed"' in build
    assert '"stockroom-release-feed/1"' in build
    assert "trusted_updater_round_trip" in build
    assert ".ArgumentList" not in build
    assert "$probeStart.Arguments" in build
    assert '$probeStart.EnvironmentVariables["STOCKROOM_CONFIG_DIR"]' in build
    assert "STOCKROOM_BUILD_IDENTITY" in spec
    assert "STOCKROOM_UV_EXECUTABLE" not in spec
    assert "stockroom-build-identity.json" in build
    assert '"--minimum-host-version", $MinimumHostVersion' in build
    assert "minimum_host_version = $MinimumHostVersion" in build
    assert "update_check_interval_seconds" in build
    assert '"--native-host-probe"' not in launcher


def test_frozen_port_worker_failure_is_noninteractive(
    monkeypatch,
) -> None:
    observed: list[tuple[str, bool]] = []

    def fail_dispatch() -> None:
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(stockroom_launcher, "_dispatch", fail_dispatch)
    monkeypatch.setattr(
        stockroom_launcher,
        "_fatal",
        lambda message, *, interactive: observed.append((message, interactive)),
    )
    monkeypatch.setattr(sys, "argv", ["Stockroom.exe", "--port", "39123"])
    with pytest.raises(SystemExit) as stopped:
        stockroom_launcher._main()
    assert stopped.value.code == 1
    assert observed == [
        (
            "Stockroom's managed runtime could not start.\n\nworker exploded",
            False,
        )
    ]


def test_packaged_python_identity_uses_the_exact_package_build_input(
    tmp_path: Path,
) -> None:
    (tmp_path / "stockroom-build-identity.json").write_text(
        json.dumps(
            {
                "package_version": "2.3.4.5",
                "protocol_version": 7,
                "release_id": "release-2.3.4.5",
                "schema": "stockroom-build-identity/1",
                "source_revision": "a" * 40,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    identity = _packaged_build_identity(tmp_path)
    assert identity.package_version == "2.3.4.5"
    assert identity.protocol_version == 7
    assert identity.release_id == "release-2.3.4.5"
    assert identity.source_revision == "a" * 40


def test_packaged_worker_probe_uses_the_real_health_route_contract() -> None:
    probe = WORKER_PROBE.read_text(encoding="utf-8")

    assert 'f"{public_base_url}/api/health"' in probe
    assert 'f"{public_base_url}/version"' not in probe
    assert '"coordinator_status": "active"' in probe
    assert '"service_mode": "coordinator"' in probe
    assert "adopted.candidate_service_generation" in probe
    assert "restored.generation" in probe
