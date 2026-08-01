from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from stockroom.catalog import (
    CatalogArtifactRole,
    CatalogArtifacts,
    ProjectedArtifact,
    stage_catalog_projection,
)
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.kicad.cli import KiCadCli
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import Datasheet, PartRecord, Purchase
from stockroom.model.part_id import make_part_id
from stockroom.planning.production_composition import (
    ManufacturerDatasheetProviderAdapter,
    ProductionApplicationContext,
    build_production_workflow_registry_for_context,
)
from stockroom.planning.production_workflow import (
    PRODUCTION_SEMANTIC_STAGES,
    ExactEvidenceCadBundleAdapter,
    ProductionPublicationCandidate,
    ProductionPublicationRequest,
    ProductionSemanticAdapter,
    ProductionStageCompletion,
    ProductionStageRequest,
    ProductionStageStop,
    ProductionWorkflowError,
    ProductionWorkflowRegistry,
    build_production_workflow_handlers,
)
from stockroom.planning.provider_policy import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    ORDINARY_COMPONENT_OPERATIONS,
    AdapterOutcome,
    AdapterOutcomeStatus,
    AuthenticationState,
    ExactPartIdentity,
    LicenseDecision,
    ProviderDeclaration,
    ProviderHealth,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyInput,
    ProviderRegistration,
    TrustDecision,
)
from stockroom.planning.provider_runtime import ProviderExecutionRuntime
from stockroom.publish import (
    PreparedPublicationManifest,
    PreparedTarget,
    ScopedComponentPublisher,
)
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile
from stockroom.vcs import GitRepo
from stockroom.workflow import (
    BatchStatus,
    IntakeIdentity,
    PermanentFailureOutcome,
    StageName,
    StageStatus,
    WorkflowRuntime,
    WorkflowStore,
)
from stockroom.workflow.model import canonical_json

_MANUFACTURER = "ON Semiconductor"
_MPN = "S1M"
_PROVIDER = "reviewed_local"
_ADAPTER_VERSION = "1.0.0"
_ALTIUM_FIXTURES = Path(__file__).parents[1] / "altium" / "fixtures"
_STEP_FIXTURE = Path(__file__).parents[1] / "capture" / "fixtures" / "readable_geometry.step"


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _worktree_snapshot(root: Path) -> tuple[tuple[str, str, str], ...]:
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0].casefold() == ".git":
            continue
        if path.is_dir():
            entries.append((relative.as_posix(), "directory", ""))
        else:
            entries.append((relative.as_posix(), "file", _sha256(path.read_bytes())))
    return tuple(entries)


def _datasheet_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 50 700 Td (S1M ON Semiconductor) Tj 0 -20 Td (Package: SMA) Tj ET"
    objects = (
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
            b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>"
        ),
        b"<</Length " + str(len(stream)).encode("ascii") + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n").encode()
    )
    return bytes(output)


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> tuple[object, ...]:
    assert isinstance(value, (list, tuple))
    return tuple(cast(list[object] | tuple[object, ...], value))


def _write_kicad_pair(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    symbol = root / "S1M.kicad_sym"
    footprint = root / "D_SMA.kicad_mod"
    model = root / "D_SMA.step"
    symbol.write_text(
        """(kicad_symbol_lib
  (version 20240101)
  (generator stockroom-production-test)
  (symbol "S1M"
    (property "Reference" "D" (at 0 0 0))
    (property "Value" "S1M" (at 0 0 0))
    (property "Footprint" "Stockroom:D_SMA" (at 0 0 0))
    (property "Manufacturer" "ON Semiconductor" (at 0 0 0))
    (property "Manufacturer Part Number" "S1M" (at 0 0 0))
    (symbol "S1M_0_1"
      (pin passive line (at -5 0 0) (length 2.54)
        (name "K" (effects (font (size 1 1))))
        (number "1" (effects (font (size 1 1)))))
      (pin passive line (at 5 0 180) (length 2.54)
        (name "A" (effects (font (size 1 1))))
        (number "2" (effects (font (size 1 1))))))))
""",
        encoding="utf-8",
    )
    footprint.write_text(
        """(footprint "D_SMA"
  (version 20240108)
  (generator stockroom-production-test)
  (layer "F.Cu")
  (pad "1" smd rect (at -2.14 0) (size 2.33 1.56) (layers "F.Cu"))
  (pad "2" smd rect (at 2.14 0) (size 2.33 1.56) (layers "F.Cu"))
  (model "D_SMA.step"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))))
""",
        encoding="utf-8",
    )
    shutil.copyfile(_STEP_FIXTURE, model)
    return symbol, footprint, model


def _validation_report(
    identity: ExactPartIdentity,
    operation: ProviderOperation,
    roles: tuple[str, ...],
    *,
    source_manifests: tuple[str, ...] = (),
) -> bytes:
    return _canonical_bytes(
        {
            "identity": {
                "authoritative_manufacturer_key": (identity.authoritative_manufacturer_key),
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation.label,
            "provider": _PROVIDER,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": sorted(source_manifests),
            "valid": True,
        }
    )


def _provider_cad_report(
    identity: ExactPartIdentity,
    operation: ProviderOperation,
) -> bytes:
    return _canonical_bytes(
        {
            "identity": {
                "authoritative_manufacturer_key": (identity.authoritative_manufacturer_key),
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation.label,
            "provider": _PROVIDER,
            "schema": "stockroom.cad-validation/1",
            "valid": True,
        }
    )


def _seed_provider_evidence(
    evidence: EvidenceStore,
    cad_root: Path,
) -> dict[ProviderOperation, str]:
    identity = ExactPartIdentity(_MANUFACTURER, _MPN)
    symbol, footprint, model = _write_kicad_pair(cad_root)
    schlib = _ALTIUM_FIXTURES / "sample.SchLib"
    pcblib = _ALTIUM_FIXTURES / "sample.PcbLib"
    kicad_roles = (
        EvidenceArtifact(
            "symbol",
            symbol.read_bytes(),
            "application/vnd.kicad.symbol",
            symbol.name,
        ),
        EvidenceArtifact(
            "footprint",
            footprint.read_bytes(),
            "application/vnd.kicad.footprint",
            footprint.name,
        ),
        EvidenceArtifact("model", model.read_bytes(), "model/step", model.name),
    )
    altium_roles = (
        EvidenceArtifact(
            "altium_symbol",
            schlib.read_bytes(),
            "application/vnd.altium.schlib",
            "S1M.SchLib",
        ),
        EvidenceArtifact(
            "altium_footprint",
            pcblib.read_bytes(),
            "application/vnd.altium.pcblib",
            "S1M.PcbLib",
        ),
    )
    evidence.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        artifacts=(*kicad_roles, *altium_roles),
        validation_report=_validation_report(
            identity,
            KICAD_CAD_OPERATION,
            (
                "symbol",
                "footprint",
                "model",
                "altium_symbol",
                "altium_footprint",
            ),
        ),
    )

    metadata = evidence.record_provider_success(
        identity=identity,
        operation=METADATA_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        payload={
            "manufacturer": _MANUFACTURER,
            "mpn": _MPN,
            "package": "SMA (DO-214AC)",
            "value": "1 A 1000 V",
        },
        media_type="application/json",
    )
    datasheet = evidence.record_provider_success(
        identity=identity,
        operation=DATASHEET_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        payload={
            "manufacturer": _MANUFACTURER,
            "mpn": _MPN,
            "source": "https://www.onsemi.com/pdf/datasheet/s1m-d.pdf",
        },
        media_type="application/json",
    )
    kicad_provider = evidence.record_provider_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        artifacts=(
            *kicad_roles,
            EvidenceArtifact(
                "validation_report",
                _provider_cad_report(identity, KICAD_CAD_OPERATION),
                "application/json",
                "KiCad Validation.json",
            ),
        ),
    )
    altium_provider = evidence.record_provider_artifact_success(
        identity=identity,
        operation=ALTIUM_CAD_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        artifacts=(
            EvidenceArtifact(
                "symbol",
                schlib.read_bytes(),
                "application/vnd.altium.schlib",
                "S1M.SchLib",
            ),
            EvidenceArtifact(
                "footprint",
                pcblib.read_bytes(),
                "application/vnd.altium.pcblib",
                "S1M.PcbLib",
            ),
            EvidenceArtifact("model", model.read_bytes(), "model/step", model.name),
            EvidenceArtifact(
                "validation_report",
                _provider_cad_report(identity, ALTIUM_CAD_OPERATION),
                "application/json",
                "Altium Validation.json",
            ),
        ),
    )
    return {
        METADATA_OPERATION: metadata,
        DATASHEET_OPERATION: datasheet,
        KICAD_CAD_OPERATION: kicad_provider,
        ALTIUM_CAD_OPERATION: altium_provider,
    }


@dataclass(slots=True)
class _ReviewedProviderAdapter:
    evidence_by_operation: dict[ProviderOperation, str]
    provider_key: str = _PROVIDER
    executable_operations: frozenset[ProviderOperation] = frozenset(ORDINARY_COMPONENT_OPERATIONS)

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        assert identity == ExactPartIdentity(_MANUFACTURER, _MPN)
        return AdapterOutcome.success(
            identity,
            evidence_digests=(self.evidence_by_operation[operation],),
        )


def _selected_digest(request: ProductionStageRequest, stage: StageName) -> str:
    result = _mapping(request.context.prior_results[stage])
    operations = _sequence(result["operations"])
    selected = _mapping(_mapping(operations[0])["selected"])
    return str(_sequence(selected["evidence_digests"])[0])


@dataclass(frozen=True, slots=True)
class _SemanticAdapter:
    stage: StageName
    adapter_key: str
    adapter_version: str = "1.0.0"

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionStageCompletion:
        if request.context.stage.name is not self.stage:
            raise AssertionError("semantic adapter received a different stage")
        datasheet_digest = _selected_digest(request, StageName.DATASHEET)
        if self.stage is StageName.RECONCILE:
            return ProductionStageCompletion(
                {
                    "accepted": {
                        "manufacturer": request.record.manufacturer,
                        "mpn": request.record.mpn,
                        "package": "SMA (DO-214AC)",
                        "value": "1 A 1000 V",
                    },
                    "datasheet_evidence_digest": datasheet_digest,
                    "schema": "stockroom.production-reconciliation/1",
                },
                (datasheet_digest, request.record_digest),
            )
        bundle = _canonical_bundle(request, datasheet_digest)
        bundle_digest = request.evidence_store.install_bytes(bundle.canonical_bytes())
        if self.stage is StageName.CANONICAL_DEFINITION:
            return ProductionStageCompletion(
                {
                    "bundle_digest": bundle_digest,
                    "definition_digest": bundle.verification.definition_digest,
                    "schema": "stockroom.production-canonical-definition/1",
                },
                (bundle_digest, datasheet_digest),
            )
        return ProductionStageCompletion(
            {
                "artifact_set_digest": bundle.verification.artifact_set_digest,
                "bundle_digest": bundle_digest,
                "schema": "stockroom.production-template-plan/1",
                "templates": [
                    template.model_dump(mode="json")
                    for template in bundle.artifacts.shared_templates
                ],
                "tool_bindings": [
                    binding.model_dump(mode="json") for binding in bundle.artifacts.tool_bindings
                ],
            },
            (bundle_digest, datasheet_digest),
        )


def _canonical_bundle(
    request: ProductionStageRequest,
    datasheet_digest: str,
) -> CanonicalPassiveBundle:
    value_evidence = AuthoritativeEvidence(
        source_kind="manufacturer_datasheet",
        source_locator="https://www.onsemi.com/pdf/datasheet/s1m-d.pdf#ratings",
        content_digest=datasheet_digest,
    )
    package_evidence = AuthoritativeEvidence(
        source_kind="manufacturer_datasheet",
        source_locator="https://www.onsemi.com/pdf/datasheet/s1m-d.pdf#package",
        content_digest=datasheet_digest,
    )
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key=request.identity.authoritative_manufacturer_key,
        mpn_canonical=request.identity.mpn_canonical,
        functional_kind="diode",
        value="1 A 1000 V",
        package="SMA (DO-214AC)",
        value_evidence=value_evidence,
        package_evidence=package_evidence,
    )


def _prior_document(request: ProductionStageRequest, stage: StageName) -> dict[str, object]:
    result = _mapping(request.context.prior_results[stage])
    digest = str(result["document_digest"])
    value = json.loads(request.evidence_store.object_bytes(digest))
    assert isinstance(value, dict)
    return value


def _native_digests(request: ProductionStageRequest) -> dict[str, str]:
    result = _mapping(request.context.prior_results[StageName.NATIVE_CONVERSION_ACQUISITION])
    artifacts = _sequence(result["artifacts"])
    return {
        str(_mapping(artifact)["role"]): str(_mapping(artifact)["object_digest"])
        for artifact in artifacts
    }


@dataclass(frozen=True, slots=True)
class _PublicationAdapter:
    live_catalog_path: Path
    adapter_key: str = "reviewed-publication"
    adapter_version: str = "1.0.0"

    def prepare_candidate(
        self,
        request: ProductionPublicationRequest,
        /,
    ) -> ProductionPublicationCandidate:
        stage_request = request.stage
        canonical = _prior_document(stage_request, StageName.CANONICAL_DEFINITION)
        bundle_digest = str(canonical["bundle_digest"])
        native = _native_digests(stage_request)
        cross = _mapping(stage_request.context.prior_results[StageName.CROSS_EDA_VERIFICATION])
        cross_digest = str(cross["report_digest"])
        return ProductionPublicationCandidate(
            {
                "bundle_digest": bundle_digest,
                "native_artifacts": native,
                "publication_scope": "one_exact_component",
                "schema": "stockroom.reviewed-publication-candidate/1",
            },
            (
                bundle_digest,
                cross_digest,
                *tuple(native.values()),
            ),
        )

    def prepare_manifest(
        self,
        request: ProductionPublicationRequest,
        /,
        *,
        candidate_document: Mapping[str, object],
        candidate_digest: str,
        publication_id: str,
    ) -> PreparedPublicationManifest:
        stage_request = request.stage
        root = stage_request.workspace / "Prepared Publication"
        root.mkdir(parents=True, exist_ok=True)
        canonical = _prior_document(stage_request, StageName.CANONICAL_DEFINITION)
        bundle_digest = str(canonical["bundle_digest"])
        bundle = CanonicalPassiveBundle.model_validate_json(
            stage_request.evidence_store.object_bytes(bundle_digest)
        )
        native = _native_digests(stage_request)
        component_root = (
            Path("libraries") / "Stockroom" / "Components" / bundle.identity.component_id
        )
        digest_root = component_root / "Native" / candidate_digest.removeprefix("sha256:")
        native_paths = {
            "kicad_symbol": digest_root / "KiCad" / "S1M.kicad_sym",
            "kicad_footprint": digest_root / "KiCad" / "S1M.pretty" / "S1M.kicad_mod",
            "step_model": digest_root / "Neutral" / "S1M.step",
            "altium_symbol": digest_root / "Altium" / "S1M.SchLib",
            "altium_footprint": digest_root / "Altium" / "S1M.PcbLib",
        }
        tracked: list[PreparedTarget] = []
        for role, relative in native_paths.items():
            data = stage_request.evidence_store.object_bytes(native[role])
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            tracked.append(PreparedTarget(relative.as_posix(), _sha256(data)))

        canonical_path = component_root / "Canonical Component.json"
        canonical_bytes = stage_request.evidence_store.object_bytes(bundle_digest)
        (root / canonical_path).parent.mkdir(parents=True, exist_ok=True)
        (root / canonical_path).write_bytes(canonical_bytes)
        tracked.append(PreparedTarget(canonical_path.as_posix(), _sha256(canonical_bytes)))

        candidate_path = component_root / "Publication Candidate.json"
        candidate_bytes = _canonical_bytes(dict(candidate_document))
        (root / candidate_path).write_bytes(candidate_bytes)
        tracked.append(PreparedTarget(candidate_path.as_posix(), _sha256(candidate_bytes)))

        selection_result = _mapping(
            stage_request.context.prior_results[StageName.NATIVE_CONVERSION_ACQUISITION]
        )
        selection = json.loads(
            stage_request.evidence_store.object_bytes(str(selection_result["selection_digest"]))
        )
        kicad_manifest = str(selection["kicad_manifest_digest"])
        altium_manifest = str(selection["altium_manifest_digest"])
        kicad_variant = stage_request.evidence_store.verified_role_artifacts(
            kicad_manifest,
            identity=stage_request.identity,
            roles=("symbol", "footprint", "model"),
        )
        altium_variant = stage_request.evidence_store.verified_role_artifacts(
            altium_manifest,
            identity=stage_request.identity,
            roles=("altium_symbol", "altium_footprint"),
        )
        from stockroom.cad_variants import resolve_cad_variant

        kicad_pointer = resolve_cad_variant(
            stage_request.evidence_store,
            identity=stage_request.identity,
            tool="kicad",
            manifest_digest=kicad_variant["symbol"].manifest_digest,
        ).pointer
        altium_pointer = resolve_cad_variant(
            stage_request.evidence_store,
            identity=stage_request.identity,
            tool="altium",
            manifest_digest=altium_variant["altium_symbol"].manifest_digest,
        ).pointer
        updated = PartRecord.loads(stage_request.record.dumps())
        nickname = f"Stockroom_{bundle.identity.component_id}"
        origin = AssetOrigin(
            vendor=_PROVIDER,
            extra={
                "altium_evidence_manifest": altium_manifest,
                "kicad_evidence_manifest": kicad_manifest,
            },
        )
        updated.assets_for("kicad").symbol = Asset(
            AssetRef(lib=nickname, name=_MPN),
            origin,
        )
        updated.assets_for("kicad").footprint = Asset(
            AssetRef(lib=nickname, name=_MPN),
            origin,
        )
        updated.assets_for("kicad").model = Asset(
            AssetRef(file=native_paths["step_model"].as_posix()),
            origin,
        )
        updated.assets_for("altium").symbol = Asset(
            AssetRef(lib=native_paths["altium_symbol"].as_posix(), name=_MPN),
            origin,
        )
        updated.assets_for("altium").footprint = Asset(
            AssetRef(lib=native_paths["altium_footprint"].as_posix(), name="DIOM5227X270N"),
            origin,
        )
        updated.assets_for("altium").model = Asset(
            AssetRef(file=native_paths["step_model"].as_posix()),
            origin,
        )
        updated.cad_variants.select("kicad", kicad_pointer)
        updated.cad_variants.select("altium", altium_pointer)
        record_path = Path("libraries") / "Stockroom" / "parts" / f"{updated.id}.json"
        record_bytes = updated.dumps().encode("utf-8")
        (root / record_path).parent.mkdir(parents=True, exist_ok=True)
        (root / record_path).write_bytes(record_bytes)
        tracked.append(PreparedTarget(record_path.as_posix(), _sha256(record_bytes)))

        templates = {
            template.kind: template.template_id for template in bundle.artifacts.shared_templates
        }
        artifacts = CatalogArtifacts(
            links=(
                ProjectedArtifact(
                    tool="kicad",
                    kind="symbol",
                    template_id=templates["symbol"],
                    reference=f"{nickname}:{_MPN}",
                    path=native_paths["kicad_symbol"].as_posix(),
                    digest=native["kicad_symbol"],
                ),
                ProjectedArtifact(
                    tool="kicad",
                    kind="footprint",
                    template_id=templates["footprint"],
                    reference=f"{nickname}:{_MPN}",
                    path=native_paths["kicad_footprint"].as_posix(),
                    digest=native["kicad_footprint"],
                ),
                ProjectedArtifact(
                    tool="altium",
                    kind="symbol",
                    template_id=templates["symbol"],
                    reference=_MPN,
                    path=native_paths["altium_symbol"].as_posix(),
                    digest=native["altium_symbol"],
                ),
                ProjectedArtifact(
                    tool="altium",
                    kind="footprint",
                    template_id=templates["footprint"],
                    reference="DIOM5227X270N",
                    path=native_paths["altium_footprint"].as_posix(),
                    digest=native["altium_footprint"],
                ),
            )
        )
        catalog = stage_catalog_projection(
            bundle,
            artifacts,
            root / "libraries" / "Stockroom" / "Catalog",
            fixture_mode=False,
            altium_catalog_path=self.live_catalog_path,
        )
        machine_local: list[PreparedTarget] = []
        digest_by_path = {
            catalog.catalog_path: catalog.catalog_sqlite_digest,
            catalog.kicad_dbl_path: catalog.kicad_dbl_digest,
            catalog.altium_dblib_path: catalog.altium_dblib_digest,
            catalog.catalog_digest_path: catalog.catalog_digest_document_digest,
        }
        for output in catalog.outputs:
            relative = output.path.relative_to(root).as_posix()
            target = PreparedTarget(relative, digest_by_path[output.path])
            if output.role is CatalogArtifactRole.TRACKED_PORTABLE:
                tracked.append(target)
            elif output.role is CatalogArtifactRole.MACHINE_LOCAL:
                machine_local.append(target)
        return PreparedPublicationManifest(
            publication_id=publication_id,
            component_id=bundle.identity.component_id,
            staging_root=root,
            tracked_files=tuple(sorted(tracked, key=lambda target: target.target_path.casefold())),
            machine_local_files=tuple(
                sorted(machine_local, key=lambda target: target.target_path.casefold())
            ),
            catalog_staged_path=catalog.catalog_path.relative_to(root).as_posix(),
            catalog_sha256=catalog.catalog_sqlite_digest,
            catalog_revision=catalog.revision,
            catalog_semantic_digest=catalog.semantic_digest,
            commit_message="Complete ON Semiconductor S1M",
        )


@dataclass(slots=True)
class _Environment:
    repository: GitRepo
    library_root: Path
    parts_dir: Path
    part_path: Path
    part_id: str
    store: WorkflowStore
    evidence: EvidenceStore
    planner: ProviderPlanner
    provider_runtime: ProviderExecutionRuntime
    policies: tuple[ProviderPolicyInput, ...]
    publisher: ScopedComponentPublisher
    staging_root: Path
    live_catalog_path: Path


def _environment(tmp_path: Path) -> _Environment:
    repo_root = tmp_path / "Repository"
    repository = GitRepo(repo_root)
    repository.init()
    library_root = repo_root / "libraries" / "Stockroom"
    parts_dir = library_root / "parts"
    parts_dir.mkdir(parents=True)
    part_id = make_part_id(_MPN)
    datasheet_path = library_root / "datasheets" / "S1M.pdf"
    datasheet_path.parent.mkdir(parents=True)
    datasheet_path.write_bytes(_datasheet_pdf())
    record = PartRecord(
        id=part_id,
        mpn=_MPN,
        manufacturer=_MANUFACTURER,
        display_name="S1M Rectifier",
        category="Diodes",
        description="1 A 1000 V surface-mount rectifier",
        value="1 A 1000 V",
        datasheet=Datasheet(
            file="datasheets/S1M.pdf",
            source_url="https://www.onsemi.com/pdf/datasheet/s1m-d.pdf",
        ),
        purchase=[
            Purchase(
                vendor="DigiKey",
                url="https://www.digikey.com/en/products/detail/onsemi/S1M/918034",
                part_number="S1MFSCT-ND",
            )
        ],
    )
    part_path = parts_dir / f"{part_id}.json"
    part_path.write_text(record.dumps(), encoding="utf-8")
    repository.commit("Seed exact PartRecord", [part_path, datasheet_path])

    evidence = EvidenceStore((tmp_path / "Evidence").absolute())
    evidence_by_operation = _seed_provider_evidence(
        evidence,
        tmp_path / "CAD",
    )
    adapter = _ReviewedProviderAdapter(evidence_by_operation)
    registration = ProviderRegistration(
        ProviderDeclaration(
            key=_PROVIDER,
            adapter_version=_ADAPTER_VERSION,
            operations=ORDINARY_COMPONENT_OPERATIONS,
            max_concurrency=1,
        ),
        adapter,
    )
    planner = ProviderPlanner((registration,))
    policies = tuple(
        ProviderPolicyInput(
            provider_key=_PROVIDER,
            operation=operation,
            trust=TrustDecision.PRIMARY,
            license=LicenseDecision.ALLOWED,
            authentication=AuthenticationState.NOT_REQUIRED,
            health=ProviderHealth.HEALTHY,
            priority=1,
        )
        for operation in ORDINARY_COMPONENT_OPERATIONS
    )
    provider_runtime = ProviderExecutionRuntime(
        planner,
        evidence_verifier=evidence,
    )
    store = WorkflowStore(tmp_path / "Workflow.sqlite")
    active = tmp_path / "Active"
    active.mkdir()
    machine = tmp_path / "Machine"
    machine.mkdir()
    live_catalog_path = active / "Catalog.sqlite"
    publisher = ScopedComponentPublisher(
        store,
        repository,
        live_catalog_path=live_catalog_path,
        machine_local_root=machine,
    )
    return _Environment(
        repository=repository,
        library_root=library_root,
        parts_dir=parts_dir,
        part_path=part_path,
        part_id=part_id,
        store=store,
        evidence=evidence,
        planner=planner,
        provider_runtime=provider_runtime,
        policies=policies,
        publisher=publisher,
        staging_root=(tmp_path / "Workflow Staging").absolute(),
        live_catalog_path=live_catalog_path,
    )


def _registry(
    environment: _Environment,
    *,
    semantic_adapters: dict[StageName, ProductionSemanticAdapter] | None = None,
) -> ProductionWorkflowRegistry:
    adapters = (
        {
            stage: _SemanticAdapter(stage, f"reviewed-{stage.value}")
            for stage in PRODUCTION_SEMANTIC_STAGES
        }
        if semantic_adapters is None
        else semantic_adapters
    )
    return build_production_workflow_handlers(
        repository=environment.repository,
        library_root=environment.library_root,
        parts_dir=environment.parts_dir,
        staging_root=environment.staging_root,
        evidence_store=environment.evidence,
        planner=environment.planner,
        provider_runtime=environment.provider_runtime,
        policy_inputs=environment.policies,
        semantic_adapters=adapters,
        publication_adapter=_PublicationAdapter(environment.live_catalog_path),
        publisher=environment.publisher,
    )


def _submit(environment: _Environment):
    return environment.store.submit_batch(
        (
            IntakeIdentity(
                _MANUFACTURER,
                _MPN,
                {"part_id": environment.part_id},
            ),
        )
    )


@pytest.mark.serial_only
def test_production_registry_runs_one_exact_part_through_all_fourteen_stages(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    registry = _registry(environment)
    assert set(registry) == set(StageName)
    assert len(registry) == 14
    runtime = WorkflowRuntime(environment.store, registry)
    batch = _submit(environment)

    for _ in range(64):
        current = environment.store.get_batch(batch.id)
        if current.status is BatchStatus.COMPLETED:
            break
        dispatch = runtime.poll_once("production-stage-worker")
        if dispatch is not None:
            continue
        leases = environment.store.claim_publications(
            "production-publication-worker",
            limit=1,
        )
        assert leases, "unfinished production run had no ready stage or publication"
        registry.execute_publication(leases[0])
    else:
        raise AssertionError("production workflow did not reach a terminal state")

    completed = environment.store.get_batch(batch.id)
    assert completed.status is BatchStatus.COMPLETED
    item = environment.store.list_items(batch.id)[0]
    stages = environment.store.list_stages(item.id)
    assert [(stage.name, stage.status) for stage in stages] == [
        (stage, StageStatus.COMPLETED) for stage in StageName
    ]
    membership = environment.store.get_publication_membership(item.id)
    assert membership is not None
    receipt = environment.store.get_component_publication_receipt(membership.publication_id)
    assert receipt is not None
    assert receipt.git_commit_oid == environment.repository.head()
    assert environment.live_catalog_path.is_file()
    published = PartRecord.loads(environment.part_path.read_text(encoding="utf-8"))
    kicad_selection = published.cad_variants.selection_for("kicad")
    altium_selection = published.cad_variants.selection_for("altium")
    assert kicad_selection is not None
    assert altium_selection is not None
    assert kicad_selection.manifest_digest == altium_selection.manifest_digest
    kicad_symbol = published.assets_for("kicad").symbol
    altium_symbol = published.assets_for("altium").symbol
    assert kicad_symbol is not None
    assert altium_symbol is not None
    assert kicad_symbol.origin.vendor == _PROVIDER
    assert altium_symbol.origin.vendor == _PROVIDER


@pytest.mark.serial_only
def test_zero_config_public_composition_uses_lifecycle_store_and_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment(tmp_path)
    capture_root = tmp_path / "Capture"
    monkeypatch.setenv("STOCKROOM_CAPTURE_DIR", str(capture_root))
    production_evidence = EvidenceStore(capture_root / "Evidence")
    _seed_provider_evidence(production_evidence, tmp_path / "Production CAD")
    profile = Profile("Stockroom", environment.library_root)
    context = cast(
        ProductionApplicationContext,
        SimpleNamespace(
            repo=environment.repository,
            profile=profile,
            config=MachineConfig(),
            cli=KiCadCli(),
        ),
    )
    before_build = _worktree_snapshot(environment.repository.root)
    before_status = environment.repository.status_porcelain()

    registry = build_production_workflow_registry_for_context(
        context,
        environment.store,
    )

    assert set(registry) == set(StageName)
    assert registry.publisher.store is environment.store
    assert _worktree_snapshot(environment.repository.root) == before_build
    assert environment.repository.status_porcelain() == before_status
    assert not registry.publisher.live_catalog_path.is_relative_to(environment.repository.root)
    assert registry.publisher.machine_local_root is not None
    assert not registry.publisher.machine_local_root.is_relative_to(environment.repository.root)
    runtime = WorkflowRuntime(environment.store, registry)
    batch = _submit(environment)
    for _ in range(64):
        current = environment.store.get_batch(batch.id)
        if current.status is BatchStatus.COMPLETED:
            break
        dispatch = runtime.poll_once("packaged-production-stage")
        if dispatch is not None:
            continue
        leases = environment.store.claim_publications(
            "packaged-production-publication",
            limit=1,
        )
        assert leases, "packaged production had no runnable stage or publication"
        registry.execute_publication(leases[0])
    else:
        raise AssertionError("packaged production did not complete all fourteen stages")

    assert environment.store.get_batch(batch.id).status is BatchStatus.COMPLETED
    assert registry.publisher.live_catalog_path.is_file()
    assert registry.publisher.machine_local_root is not None
    dblib_path = registry.publisher.machine_local_root / "Stockroom.DbLib"
    assert dblib_path.is_file()
    dblib = dblib_path.read_text(encoding="utf-8")
    assert f"Database={registry.publisher.live_catalog_path.resolve()};" in dblib
    with sqlite3.connect(registry.publisher.live_catalog_path) as connection:
        altium_symbol_path, altium_footprint_path = connection.execute(
            'SELECT "Library Path", "Footprint Path" FROM "Parts"'
        ).fetchone()
    assert (registry.publisher.machine_local_root / str(altium_symbol_path)).is_file()
    assert (registry.publisher.machine_local_root / str(altium_footprint_path)).is_file()
    published = PartRecord.loads(environment.part_path.read_text(encoding="utf-8"))
    publication = _mapping(published.extra["production_publication"])
    assert publication["schema"] == "stockroom.production-publication/1"
    assert published.cad_variants.selection_for("kicad") is not None
    assert published.cad_variants.selection_for("altium") is not None
    model = published.assets_for("kicad").model
    assert model is not None
    assert (profile.root / model.file).is_file()


@pytest.mark.parametrize("record_path", ["S1M.pdf", "datasheets/S1M.pdf"])
def test_production_datasheet_resolves_canonical_and_legacy_relative_paths(
    tmp_path: Path,
    record_path: str,
) -> None:
    profile_root = tmp_path / "Stockroom"
    parts_dir = profile_root / "parts"
    parts_dir.mkdir(parents=True)
    datasheet = profile_root / "datasheets" / "S1M.pdf"
    datasheet.parent.mkdir()
    datasheet.write_bytes(_datasheet_pdf())
    record = PartRecord(
        id=make_part_id(_MPN),
        mpn=_MPN,
        manufacturer=_MANUFACTURER,
        display_name="S1M Rectifier",
        category="Diodes",
        description="1 A 1000 V surface-mount rectifier",
        datasheet=Datasheet(file=record_path),
        purchase=[Purchase(vendor="DigiKey", url="https://www.digikey.com/S1M")],
    )
    (parts_dir / f"{record.id}.json").write_text(record.dumps(), encoding="utf-8")
    evidence = EvidenceStore((tmp_path / "Evidence").absolute())
    adapter = ManufacturerDatasheetProviderAdapter(
        profile_root=profile_root,
        parts_dir=parts_dir,
        evidence_store=evidence,
        staging_root=tmp_path / "Staging",
    )

    outcome = adapter.execute(
        ExactPartIdentity(_MANUFACTURER, _MPN),
        DATASHEET_OPERATION,
    )

    assert outcome.status is AdapterOutcomeStatus.SUCCESS
    assert len(outcome.evidence_digests) == 1


def test_exact_adapter_rejects_same_provider_roles_from_separate_manifests(
    tmp_path: Path,
) -> None:
    evidence = EvidenceStore((tmp_path / "Evidence").absolute())
    identity = ExactPartIdentity(_MANUFACTURER, _MPN)
    symbol, footprint, model = _write_kicad_pair(tmp_path / "Split CAD")
    schlib = _ALTIUM_FIXTURES / "sample.SchLib"
    pcblib = _ALTIUM_FIXTURES / "sample.PcbLib"
    evidence.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        artifacts=(
            EvidenceArtifact(
                "symbol",
                symbol.read_bytes(),
                "application/vnd.kicad.symbol",
                symbol.name,
            ),
            EvidenceArtifact(
                "footprint",
                footprint.read_bytes(),
                "application/vnd.kicad.footprint",
                footprint.name,
            ),
            EvidenceArtifact("model", model.read_bytes(), "model/step", model.name),
        ),
        validation_report=_validation_report(
            identity,
            KICAD_CAD_OPERATION,
            ("symbol", "footprint", "model"),
        ),
    )
    evidence.record_role_artifact_success(
        identity=identity,
        operation=ALTIUM_CAD_OPERATION,
        provider_key=_PROVIDER,
        adapter_version=_ADAPTER_VERSION,
        artifacts=(
            EvidenceArtifact(
                "altium_symbol",
                schlib.read_bytes(),
                "application/vnd.altium.schlib",
                "S1M.SchLib",
            ),
            EvidenceArtifact(
                "altium_footprint",
                pcblib.read_bytes(),
                "application/vnd.altium.pcblib",
                "S1M.PcbLib",
            ),
        ),
        validation_report=_validation_report(
            identity,
            ALTIUM_CAD_OPERATION,
            ("altium_symbol", "altium_footprint"),
        ),
    )

    selected = ExactEvidenceCadBundleAdapter().select(
        evidence_store=evidence,
        identity=identity,
        workspace=tmp_path / "Selection",
    )

    assert isinstance(selected, ProductionStageStop)
    assert selected.code == "exact_dual_eda_evidence_unavailable"


def test_source_part_byte_drift_after_identity_fails_closed(tmp_path: Path) -> None:
    environment = _environment(tmp_path)
    registry = _registry(environment)
    runtime = WorkflowRuntime(environment.store, registry)
    batch = _submit(environment)
    identity = runtime.poll_once("worker")
    assert identity is not None
    assert identity.stage_name is StageName.IDENTITY_DEDUPE
    environment.part_path.write_bytes(environment.part_path.read_bytes() + b"\n")

    drift = runtime.poll_once("worker")

    assert drift is not None
    assert isinstance(drift.outcome, PermanentFailureOutcome)
    error = cast(dict[str, object], drift.outcome.error)
    assert error["kind"] == "source_part_record_drift"
    item = environment.store.list_items(batch.id)[0]
    assert environment.store.get_stage(drift.stage_id).status is StageStatus.FAILED
    assert item.id == drift.item_id


@dataclass(frozen=True, slots=True)
class _MutatingAdapter:
    part_path: Path
    adapter_key: str = "mutation-probe"
    adapter_version: str = "1.0.0"

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionStageCompletion:
        record = PartRecord.loads(self.part_path.read_text(encoding="utf-8"))
        record.tags.append("illegal-pre-publish-write")
        self.part_path.write_text(record.dumps(), encoding="utf-8")
        return ProductionStageCompletion(
            {"schema": "stockroom.mutation-probe/1"},
            (request.record_digest,),
        )


def test_semantic_adapter_live_library_write_is_detected_not_completed(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    adapters: dict[StageName, ProductionSemanticAdapter] = {
        stage: _SemanticAdapter(stage, f"reviewed-{stage.value}")
        for stage in PRODUCTION_SEMANTIC_STAGES
    }
    adapters[StageName.RECONCILE] = _MutatingAdapter(environment.part_path)
    registry = _registry(environment, semantic_adapters=adapters)
    runtime = WorkflowRuntime(environment.store, registry)
    batch = _submit(environment)

    for _ in range(16):
        dispatch = runtime.poll_once("worker")
        assert dispatch is not None
        if dispatch.stage_name is StageName.RECONCILE:
            assert isinstance(dispatch.outcome, PermanentFailureOutcome)
            error = cast(dict[str, object], dispatch.outcome.error)
            assert error["kind"] == "live_library_mutation_before_publish"
            break
    else:
        raise AssertionError("reconciliation was not dispatched")

    item = environment.store.list_items(batch.id)[0]
    reconcile = next(
        stage
        for stage in environment.store.list_stages(item.id)
        if stage.name is StageName.RECONCILE
    )
    assert reconcile.status is StageStatus.FAILED


def test_construction_rejects_incomplete_semantic_adapter_coverage(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    adapters: dict[StageName, ProductionSemanticAdapter] = {
        stage: _SemanticAdapter(stage, f"reviewed-{stage.value}")
        for stage in PRODUCTION_SEMANTIC_STAGES
        if stage is not StageName.TEMPLATE_GENERATION
    }

    with pytest.raises(ProductionWorkflowError, match="coverage is incomplete"):
        _registry(environment, semantic_adapters=adapters)


def test_capture_then_api_import_order_has_no_planning_cycle() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import stockroom.capture.cross_eda; "
                "from stockroom.api.app import create_app; "
                "assert callable(create_app)"
            ),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
