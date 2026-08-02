from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from stockroom.catalog import (
    ALTIUM_DBLIB_FILENAME,
    CATALOG_DIGEST_FILENAME,
    CATALOG_FILENAME,
    KICAD_DBL_FILENAME,
    CatalogArtifacts,
    ProjectedArtifact,
    stage_catalog_projection,
)
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)
from stockroom.publish import (
    ManifestValidationError,
    PreparedPublicationManifest,
    PreparedTarget,
    PublishCheckpoint,
    PublishConflict,
    ScopedComponentPublisher,
)
from stockroom.vcs import GitRepo, lfs
from stockroom.workflow import (
    IntakeIdentity,
    PublicationLease,
    PublicationState,
    StageName,
    StageRecord,
    WorkflowStore,
)


class _InjectedCrash(RuntimeError):
    pass


@dataclass(slots=True)
class _CrashOnce:
    target: PublishCheckpoint
    fired: bool = False

    def __call__(self, checkpoint: PublishCheckpoint) -> None:
        if checkpoint is self.target and not self.fired:
            self.fired = True
            raise _InjectedCrash(checkpoint.value)


@dataclass(frozen=True, slots=True)
class _PreparedCase:
    store: WorkflowStore
    repo: GitRepo
    base_commit: str
    manifest: PreparedPublicationManifest
    lease: PublicationLease
    live_catalog: Path
    machine_local_root: Path
    now: float


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _stage_lease(stage: StageRecord) -> dict[str, str | int]:
    assert stage.lease_token is not None
    return {
        "lease_token": stage.lease_token,
        "lease_generation": stage.lease_generation,
    }


def _publication_lease(lease: PublicationLease) -> dict[str, str | int]:
    return {
        "lease_token": lease.lease_token,
        "lease_generation": lease.lease_generation,
    }


def _evidence(label: str) -> AuthoritativeEvidence:
    return AuthoritativeEvidence(
        source_kind="manufacturer_datasheet",
        source_locator=f"https://onsemi.example/{label}.pdf",
        content_digest=_digest(f"evidence:{label}"),
    )


def _bundle(
    manufacturer: str = "ON Semiconductor",
    mpn: str = "S1M",
) -> CanonicalPassiveBundle:
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
        functional_kind="diode",
        value="1 kV, 1 A rectifier diode",
        package="SMA (DO-214AC)",
        value_evidence=_evidence(f"{manufacturer}-{mpn}-value"),
        package_evidence=_evidence(f"{manufacturer}-{mpn}-package"),
    )


def _artifacts(bundle: CanonicalPassiveBundle) -> CatalogArtifacts:
    templates = {
        template.kind: template.template_id for template in bundle.artifacts.shared_templates
    }
    return CatalogArtifacts(
        links=(
            ProjectedArtifact(
                tool="kicad",
                kind="symbol",
                template_id=templates["symbol"],
                reference="Device:D",
                path="templates/Device.kicad_sym",
                digest=_digest("kicad-symbol"),
            ),
            ProjectedArtifact(
                tool="kicad",
                kind="footprint",
                template_id=templates["footprint"],
                reference="Diode_SMD:D_SMA",
                path="templates/Diode_SMD.pretty/D_SMA.kicad_mod",
                digest=_digest("kicad-footprint"),
            ),
            ProjectedArtifact(
                tool="altium",
                kind="symbol",
                template_id=templates["symbol"],
                reference=mpn_for(bundle),
                path="fixtures/sample.SchLib",
                digest=_digest("altium-symbol"),
            ),
            ProjectedArtifact(
                tool="altium",
                kind="footprint",
                template_id=templates["footprint"],
                reference="DIOM5227X270N",
                path="fixtures/sample.PcbLib",
                digest=_digest("altium-footprint"),
            ),
        )
    )


def mpn_for(bundle: CanonicalPassiveBundle) -> str:
    return bundle.identity.mpn_canonical


def _advance_to_publish(
    store: WorkflowStore,
    *,
    manufacturer: str,
    mpn: str,
    start: float = 10,
) -> tuple[StageRecord, float]:
    batch = store.submit_batch([IntakeIdentity(manufacturer, mpn)], now=start)
    timestamp = start + 1
    while True:
        claims = store.claim_ready(
            "stage-worker",
            now=timestamp,
            lease_seconds=10_000,
            limit=100,
        )
        assert claims
        for claim in claims:
            assert claim.batch_id == batch.id
            if claim.name is StageName.PUBLISH:
                return claim, timestamp
            if claim.name is StageName.IDENTITY_DEDUPE:
                store.resolve_exact_identity(
                    claim.id,
                    "stage-worker",
                    authoritative_manufacturer_key=manufacturer,
                    mpn_canonical=mpn,
                    registry_revision="registry-v1",
                    rule_revision="identity-rules-v1",
                    evidence={"method": "exact-publisher-test"},
                    **_stage_lease(claim),
                    now=timestamp + 0.1,
                )
            else:
                store.complete_stage(
                    claim.id,
                    "stage-worker",
                    {"stage": claim.name.value},
                    **_stage_lease(claim),
                    now=timestamp + 0.1,
                )
        timestamp += 1


def _git(
    repo: GitRepo,
    *args: str,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        [repo.git, "-C", str(repo.root), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


def _prepare_case(
    tmp_path: Path,
    *,
    publication_lease_seconds: float = 100,
    lfs_binary: bool = False,
) -> _PreparedCase:
    repo = GitRepo(tmp_path / "Repository")
    repo.init()
    readme = repo.root / "README.md"
    readme.write_text("Stockroom publication test\n", encoding="utf-8")
    initial_paths = [readme]
    if lfs_binary:
        lfs.enable(repo)
        attributes = repo.root / ".gitattributes"
        attributes.write_text(
            "*.PcbLib filter=lfs binary\n*.kicad_sym text eol=lf\n",
            encoding="utf-8",
        )
        initial_paths.append(attributes)
    base_commit = repo.commit("Initial", initial_paths)

    live_catalog = (tmp_path / "Live" / CATALOG_FILENAME).resolve()
    live_catalog.parent.mkdir()
    machine_local_root = (tmp_path / "Machine").resolve()
    machine_local_root.mkdir()
    staging = (tmp_path / "Staging").resolve()
    bundle = _bundle()
    projection = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        staging,
        fixture_mode=True,
        altium_catalog_path=live_catalog,
    )
    canonical_path = f"Canonical/{bundle.identity.component_id}.json"
    canonical_source = staging.joinpath(*canonical_path.split("/"))
    canonical_source.parent.mkdir(parents=True)
    canonical_source.write_bytes(
        (
            '{"component_id":"' + bundle.identity.component_id + '","format":"publisher-test-v1"}\n'
        ).encode()
    )
    binary_path = "Canonical/Native.PcbLib"
    binary_source = staging.joinpath(*binary_path.split("/"))
    normalized_text_path = "Canonical/Native.kicad_sym"
    normalized_text_source = staging.joinpath(*normalized_text_path.split("/"))
    if lfs_binary:
        binary_source.write_bytes(b"native-pcblib\x00" * 32)
        normalized_text_source.write_bytes(b"(kicad_symbol_lib\r\n  (version 20240101)\r\n)\r\n")

    store = WorkflowStore(tmp_path / "Workflow.sqlite3")
    publish_stage, timestamp = _advance_to_publish(
        store,
        manufacturer=bundle.manufacturer.authoritative_key,
        mpn=bundle.identity.mpn_canonical,
    )
    membership = store.join_publication(
        publish_stage.id,
        "stage-worker",
        candidate_digest=_digest("candidate"),
        manifest_digest=_digest("placeholder-manifest"),
        expected_base_commit=base_commit,
        lease_token=publish_stage.lease_token or "",
        lease_generation=publish_stage.lease_generation,
        now=timestamp + 0.1,
    )
    claim_time = timestamp + 0.2
    lease = store.claim_publications(
        "publisher",
        now=claim_time,
        lease_seconds=publication_lease_seconds,
        limit=1,
    )[0]
    assert lease.component_id == bundle.identity.component_id

    manifest = PreparedPublicationManifest(
        publication_id=membership.publication_id,
        component_id=bundle.identity.component_id,
        staging_root=staging,
        tracked_files=(
            PreparedTarget(canonical_path, _file_digest(canonical_source)),
            *(
                (
                    PreparedTarget(binary_path, _file_digest(binary_source)),
                    PreparedTarget(
                        normalized_text_path,
                        _file_digest(normalized_text_source),
                    ),
                )
                if lfs_binary
                else ()
            ),
            PreparedTarget(
                CATALOG_DIGEST_FILENAME,
                projection.catalog_digest_document_digest,
            ),
            PreparedTarget(KICAD_DBL_FILENAME, projection.kicad_dbl_digest),
        ),
        machine_local_files=(
            PreparedTarget(
                ALTIUM_DBLIB_FILENAME,
                projection.altium_dblib_digest,
            ),
        ),
        catalog_staged_path=CATALOG_FILENAME,
        catalog_sha256=projection.catalog_sqlite_digest,
        catalog_revision=projection.revision,
        catalog_semantic_digest=projection.semantic_digest,
        commit_message=f"Publish {bundle.identity.mpn_canonical}",
    )
    store.replan_publication(
        membership.publication_id,
        lease.worker_id,
        manifest_digest=manifest.digest,
        expected_base_commit=base_commit,
        expected_head_publication_id=None,
        **_publication_lease(lease),
        now=claim_time + 0.1,
    )
    return _PreparedCase(
        store=store,
        repo=repo,
        base_commit=base_commit,
        manifest=manifest,
        lease=lease,
        live_catalog=live_catalog,
        machine_local_root=machine_local_root,
        now=claim_time + 0.2,
    )


def _publisher(
    case: _PreparedCase,
    *,
    crash_hook: _CrashOnce | None = None,
) -> ScopedComponentPublisher:
    return ScopedComponentPublisher(
        case.store,
        case.repo,
        live_catalog_path=case.live_catalog,
        machine_local_root=case.machine_local_root,
        crash_hook=crash_hook,
    )


def _commit_paths(case: _PreparedCase, oid: str) -> set[str]:
    output = _git(
        case.repo,
        "-c",
        "core.quotepath=false",
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "-r",
        oid,
    )
    return {line for line in output.splitlines() if line}


def _catalog_metadata(path: Path) -> dict[str, str]:
    with sqlite3.connect(path) as connection:
        return dict(connection.execute("SELECT key, value FROM catalog_metadata ORDER BY key"))


def test_one_part_publication_preserves_foreign_staged_and_unstaged_work(
    tmp_path: Path,
) -> None:
    case = _prepare_case(tmp_path)
    staged = case.repo.root / "Foreign Staged.txt"
    staged.write_text("keep staged\n", encoding="utf-8")
    _git(case.repo, "add", "--", staged.name)
    unstaged = case.repo.root / "Foreign Unstaged.txt"
    unstaged.write_text("keep unstaged\n", encoding="utf-8")

    receipt = _publisher(case).publish(case.manifest, case.lease, now=case.now)

    assert receipt.publication_id == case.manifest.publication_id
    assert case.store.get_publication_operation(receipt.publication_id).state is (
        PublicationState.COMPLETED
    )
    assert case.repo.count_commits(case.base_commit, case.repo.head()) == 1
    assert _commit_paths(case, receipt.git_commit_oid) == {
        target.target_path for target in case.manifest.tracked_files
    }
    message = _git(case.repo, "show", "-s", "--format=%B", receipt.git_commit_oid)
    assert message.count(f"Stockroom-Publish-ID: {case.manifest.publication_id}") == 1
    assert message.count(f"Stockroom-Component-ID: {case.manifest.component_id}") == 1
    assert _git(case.repo, "diff", "--cached", "--name-only").splitlines() == [staged.name]
    assert staged.read_text(encoding="utf-8") == "keep staged\n"
    assert unstaged.read_text(encoding="utf-8") == "keep unstaged\n"
    assert _catalog_metadata(case.live_catalog)["catalog_revision"] == (
        case.manifest.catalog_revision
    )
    installed_dblib = case.machine_local_root / ALTIUM_DBLIB_FILENAME
    assert _file_digest(installed_dblib) == (case.manifest.machine_local_files[0].sha256)


@pytest.mark.skipif(not lfs.available()[0], reason="git-lfs not installed")
def test_publication_verifies_the_exact_payload_behind_a_git_lfs_pointer(
    tmp_path: Path,
) -> None:
    case = _prepare_case(tmp_path, lfs_binary=True)

    receipt = _publisher(case).publish(case.manifest, case.lease, now=case.now)

    binary = next(
        target for target in case.manifest.tracked_files if target.target_path.endswith(".PcbLib")
    )
    committed = _git(case.repo, "show", f"{receipt.git_commit_oid}:{binary.target_path}")
    assert committed == (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid {binary.sha256}\n"
        f"size {case.manifest.staging_root.joinpath(*binary.target_path.split('/')).stat().st_size}\n"
    )
    normalized_text = next(
        target
        for target in case.manifest.tracked_files
        if target.target_path.endswith(".kicad_sym")
    )
    assert _git(
        case.repo,
        "show",
        f"{receipt.git_commit_oid}:{normalized_text.target_path}",
    ) == "(kicad_symbol_lib\n  (version 20240101)\n)\n"
    assert case.store.get_publication_operation(receipt.publication_id).state is (
        PublicationState.COMPLETED
    )


@pytest.mark.parametrize(
    "checkpoint",
    [
        PublishCheckpoint.COMMIT_FENCED,
        PublishCheckpoint.MATERIALIZATION_PROGRESS,
        PublishCheckpoint.GIT_COMMIT_CREATED,
        PublishCheckpoint.GIT_COMMIT_RECORDED,
        PublishCheckpoint.CATALOG_ACTIVATED,
        PublishCheckpoint.CATALOG_RECORDED,
    ],
)
def test_reconciles_each_durable_crash_boundary_exactly_once(
    tmp_path: Path,
    checkpoint: PublishCheckpoint,
) -> None:
    case = _prepare_case(tmp_path, publication_lease_seconds=1)
    crash = _CrashOnce(checkpoint)
    with pytest.raises(_InjectedCrash, match=checkpoint.value):
        _publisher(case, crash_hook=crash).publish(
            case.manifest,
            case.lease,
            now=case.now,
        )
    assert crash.fired

    reconcile_time = case.now + 2
    lease = case.store.claim_publications(
        "reconciler",
        now=reconcile_time,
        lease_seconds=100,
        limit=1,
    )[0]
    receipt = _publisher(case).reconcile(
        case.manifest,
        lease,
        now=reconcile_time + 0.1,
    )

    assert case.store.get_publication_operation(receipt.publication_id).state is (
        PublicationState.COMPLETED
    )
    assert case.repo.count_commits(case.base_commit, case.repo.head()) == 1
    assert _commit_paths(case, receipt.git_commit_oid) == {
        target.target_path for target in case.manifest.tracked_files
    }


@pytest.mark.parametrize("staged", [False, True], ids=["unstaged", "staged"])
def test_refuses_dirty_publication_target_before_commit_fence(
    tmp_path: Path,
    staged: bool,
) -> None:
    case = _prepare_case(tmp_path)
    target = case.repo.root.joinpath(*case.manifest.tracked_files[0].target_path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"foreign target bytes")
    if staged:
        _git(
            case.repo,
            "add",
            "--",
            case.manifest.tracked_files[0].target_path,
        )

    with pytest.raises(PublishConflict, match="target paths are dirty"):
        _publisher(case).publish(case.manifest, case.lease, now=case.now)

    operation = case.store.get_publication_operation(case.manifest.publication_id)
    assert operation.state is PublicationState.PREPARING
    assert case.repo.head() == case.base_commit
    assert target.read_bytes() == b"foreign target bytes"


def test_existing_wal_catalog_is_updated_in_place_with_open_reader(
    tmp_path: Path,
) -> None:
    case = _prepare_case(tmp_path)
    old_staging = tmp_path / "Old Catalog"
    old_bundle = _bundle("Vishay", "OLD1")
    old_projection = stage_catalog_projection(
        old_bundle,
        _artifacts(old_bundle),
        old_staging,
        fixture_mode=True,
        altium_catalog_path=case.live_catalog,
    )
    shutil.copyfile(old_projection.catalog_path, case.live_catalog)
    with sqlite3.connect(case.live_catalog) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"

    reader = sqlite3.connect(case.live_catalog, isolation_level=None)
    try:
        reader.execute("BEGIN")
        old_revision = dict(reader.execute("SELECT key, value FROM catalog_metadata"))[
            "catalog_revision"
        ]
        assert old_revision != case.manifest.catalog_revision
        file_identity = case.live_catalog.stat().st_ino

        receipt = _publisher(case).publish(
            case.manifest,
            case.lease,
            now=case.now,
        )

        assert (
            reader.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'catalog_revision'"
            ).fetchone()[0]
            == old_revision
        )
        assert _catalog_metadata(case.live_catalog)["catalog_revision"] == (
            case.manifest.catalog_revision
        )
        assert case.live_catalog.stat().st_ino == file_identity
        assert receipt.catalog_revision == case.manifest.catalog_revision
    finally:
        reader.close()


def test_staged_digest_drift_is_rejected_before_fence(tmp_path: Path) -> None:
    case = _prepare_case(tmp_path)
    source = case.manifest.staging_root.joinpath(
        *case.manifest.tracked_files[0].target_path.split("/")
    )
    source.write_bytes(b"tampered staged bytes")

    with pytest.raises(ManifestValidationError, match="digest does not match"):
        _publisher(case).publish(case.manifest, case.lease, now=case.now)

    assert (
        case.store.get_publication_operation(case.manifest.publication_id).state
        is PublicationState.PREPARING
    )
    assert case.repo.head() == case.base_commit
