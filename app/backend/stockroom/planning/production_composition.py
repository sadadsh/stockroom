"""Zero-config production composition for the durable component workflow.

This module binds the generic 14-stage production registry to the ordinary
Windows application context and to the *same* :class:`WorkflowStore` owned by
the service lifecycle.  It deliberately accepts no alternate store and never
constructs a hidden workflow database.

The provider ladder is executable in a normal packaged install:

* the exact canonical ``PartRecord`` supplies already accepted metadata;
* an exact local or public-HTTPS manufacturer datasheet is retained only after
  PDF readback proves the requested MPN and manufacturer;
* immutable verified CAD evidence is always tried first;
* on a cache miss, Stockroom's existing direct, deterministic, and reviewed
  guided-commercial capture ladder runs in an isolated copy-on-write library,
  so acquisition can add evidence without touching the live Git library.

Only the scoped publisher mutates the live library.  The semantic adapters and
the cumulative catalog projection below operate entirely in workflow staging.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Protocol, cast

from stockroom.altium.dblib import render_dblib
from stockroom.cad_variants import resolve_cad_variant, same_cad_evidence_set
from stockroom.capture.evidence import record_installed_kicad_role_evidence
from stockroom.capture.runner import (
    capture_state_root,
    run_guided_capture,
    write_durable_capture_report,
)
from stockroom.catalog import (
    CATALOG_APPLICATION_ID,
    CATALOG_FILENAME,
    CATALOG_SCHEMA_VERSION,
    PART_COLUMNS,
    render_kicad_dbl,
)
from stockroom.catalog.projection import CATALOG_TABLE
from stockroom.enrich.datasheet import (
    extract_datasheet_specs,
    fetch_datasheet,
    looks_like_pdf,
)
from stockroom.enrich.image_proxy import allowed_image_url
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.lib_table import LibTable
from stockroom.model.asset import Asset, AssetOrigin, AssetRef
from stockroom.model.part import PartRecord
from stockroom.model.part_id import make_part_id, part_id_matches
from stockroom.mutation.library_ops import LibraryOps
from stockroom.planning.distributor_provider import (
    build_configured_distributor_metadata_registrations,
)
from stockroom.publish import (
    PreparedPublicationManifest,
    PreparedTarget,
    ScopedComponentPublisher,
)
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile
from stockroom.vcs import GitRepo
from stockroom.workflow import StageContext, StageName, WorkflowStore
from stockroom.workflow.identifiers import (
    authoritative_text,
    derive_component_identity,
    digest_id,
    digest_text,
)
from stockroom.workflow.model import canonical_json

from .production_workflow import (
    PRODUCTION_SEMANTIC_STAGES,
    ExactEvidenceCadBundleAdapter,
    NativeCadRole,
    ProductionCadBundle,
    ProductionPublicationCandidate,
    ProductionPublicationRequest,
    ProductionSemanticAdapter,
    ProductionStageCompletion,
    ProductionStageRequest,
    ProductionStageStop,
    ProductionStopKind,
    ProductionWorkflowError,
    ProductionWorkflowRegistry,
    build_production_workflow_handlers,
)
from .provider_policy import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    AdapterOutcome,
    AuthenticationState,
    ExactPartIdentity,
    ExecutableProviderAdapter,
    FailureClassification,
    LicenseDecision,
    ProviderDeclaration,
    ProviderHealth,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyInput,
    ProviderRegistration,
    TrustDecision,
)
from .provider_runtime import ProviderExecutionRuntime

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_SCHEMA_VERSION = 1
_RECORD_PROVIDER = "canonical_record"
_DATASHEET_PROVIDER = "manufacturer_datasheet"
_ACQUISITION_PROVIDER = "stockroom_acquisition"
_RECORD_ADAPTER_VERSION = "part-record-v4"
_DATASHEET_ADAPTER_VERSION = "exact-pdf-v1"
_ACQUISITION_ADAPTER_VERSION = "verified-cow-capture-v2"
_PRODUCTION_METADATA_KEY = "production_publication"
_PORTABLE_TABLE_DIRECTORY = "Stockroom-Portable-KiCad-Tables"
_PORTABLE_SYMBOL_TABLE = "Stockroom-Portable-Symbol-Libraries.kicad-table"
_PORTABLE_FOOTPRINT_TABLE = "Stockroom-Portable-Footprint-Libraries.kicad-table"
_WINDOWS_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class ProductionApplicationContext(Protocol):
    """Narrow application surface required by the production composition."""

    repo: GitRepo
    profile: Profile
    config: MachineConfig
    cli: KiCadCli


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ProductionWorkflowError(f"{label} is not a JSON object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
        raise ProductionWorkflowError(f"{label} is not a JSON array")
    return tuple(cast(list[object] | tuple[object, ...], value))


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ProductionWorkflowError(f"{label} is not a non-empty string")
    return value


def _prior_result(
    request: ProductionStageRequest,
    stage: StageName,
) -> Mapping[str, object]:
    return _mapping(request.context.prior_results.get(stage), f"{stage.value} result")


def _prior_document(
    request: ProductionStageRequest,
    stage: StageName,
) -> Mapping[str, object]:
    result = _prior_result(request, stage)
    digest = _string(result.get("document_digest"), f"{stage.value} document digest")
    if _SHA256.fullmatch(digest) is None:
        raise ProductionWorkflowError(f"{stage.value} document digest is not canonical")
    try:
        document = json.loads(request.evidence_store.object_bytes(digest))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionWorkflowError(f"{stage.value} document is invalid") from exc
    return _mapping(document, f"{stage.value} document")


def _selected_provider_manifest(
    request: ProductionStageRequest,
    stage: StageName,
    operation: ProviderOperation,
) -> str:
    result = _prior_result(request, stage)
    for raw_operation in _sequence(result.get("operations"), f"{stage.value} operations"):
        operation_result = _mapping(raw_operation, "provider operation")
        if operation_result.get("operation") != operation.label:
            continue
        selected = _mapping(operation_result.get("selected"), "selected provider")
        digests = _sequence(selected.get("evidence_digests"), "provider evidence digests")
        if not digests:
            break
        return _string(digests[0], "provider evidence digest")
    raise ProductionWorkflowError(f"{operation.label} has no selected provider evidence")


def _provider_payload(
    request: ProductionStageRequest,
    stage: StageName,
    operation: ProviderOperation,
) -> tuple[Mapping[str, object], str]:
    manifest_digest = _selected_provider_manifest(request, stage, operation)
    try:
        manifest = json.loads(request.evidence_store.object_bytes(manifest_digest))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionWorkflowError("provider evidence manifest is invalid") from exc
    envelope = _mapping(manifest, "provider evidence manifest")
    payload_ref = _mapping(envelope.get("payload"), "provider payload reference")
    payload_digest = _string(payload_ref.get("digest"), "provider payload digest")
    try:
        payload = json.loads(request.evidence_store.object_bytes(payload_digest))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionWorkflowError("provider payload is invalid") from exc
    return _mapping(payload, "provider payload"), manifest_digest


def _load_exact_record(parts_dir: Path, identity: ExactPartIdentity) -> tuple[PartRecord, bytes]:
    part_id = make_part_id(identity.mpn_canonical)
    path = parts_dir / f"{part_id}.json"
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(part_id)
    data = path.read_bytes()
    record = PartRecord.loads(data.decode("utf-8"))
    canonical_lf = record.dumps().encode("utf-8")
    if data not in (canonical_lf, canonical_lf.replace(b"\n", b"\r\n")):
        raise ValueError("PartRecord is not canonical")
    if (
        record.id != part_id
        or not part_id_matches(record.id, record.mpn)
        or record.manufacturer != identity.authoritative_manufacturer_key
        or record.mpn != identity.mpn_canonical
        or record.is_future_schema()
    ):
        raise ValueError("PartRecord exact identity differs")
    return record, data


@dataclass(slots=True)
class CanonicalRecordProviderAdapter:
    """Expose exact current record facts as immutable metadata evidence."""

    parts_dir: Path
    evidence_store: EvidenceStore
    provider_key: str = _RECORD_PROVIDER
    executable_operations: frozenset[ProviderOperation] = frozenset({METADATA_OPERATION})

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        if operation not in self.executable_operations:
            return AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)
        try:
            record, data = _load_exact_record(self.parts_dir, identity)
        except FileNotFoundError:
            return AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)
        except (UnicodeDecodeError, ValueError, TypeError):
            return AdapterOutcome.failure(FailureClassification.NEAR_MATCH_REJECTED)
        payload = {
            "category": record.category,
            "description": record.description,
            "display_name": record.display_name,
            "manufacturer": record.manufacturer,
            "mpn": record.mpn,
            "part_class": record.part_class.value,
            "record_digest": _digest(data),
            "record_schema_version": record.schema_version,
            "schema": "stockroom.canonical-record-metadata/1",
            "specs": record.specs,
            "value": record.value,
        }
        digest = self.evidence_store.record_provider_success(
            identity=identity,
            operation=operation,
            provider_key=self.provider_key,
            adapter_version=_RECORD_ADAPTER_VERSION,
            payload=payload,
            media_type="application/json",
        )
        return AdapterOutcome.success(identity, evidence_digests=(digest,))


@dataclass(slots=True)
class ManufacturerDatasheetProviderAdapter:
    """Fetch/read one datasheet and accept it only after exact PDF identity proof."""

    profile_root: Path
    parts_dir: Path
    evidence_store: EvidenceStore
    staging_root: Path
    provider_key: str = _DATASHEET_PROVIDER
    executable_operations: frozenset[ProviderOperation] = frozenset({DATASHEET_OPERATION})

    def _local_path(self, record: PartRecord) -> Path | None:
        if record.datasheet is None or not record.datasheet.file:
            return None
        raw = PurePosixPath(record.datasheet.file)
        if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
            raise ValueError("datasheet path is not portable")
        # PartRecord stores the canonical filename relative to ``datasheets/``.
        # Accept the older profile-relative spelling too so an existing record
        # does not become unreadable after adopting the canonical contract.
        relative = (
            raw if raw.parts[0].casefold() == "datasheets" else PurePosixPath("datasheets") / raw
        )
        candidate = self.profile_root.joinpath(*relative.parts)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(self.profile_root.resolve(strict=True))
        if not resolved.is_file() or resolved.is_symlink():
            raise ValueError("datasheet is not a regular file")
        return resolved

    def _bytes(self, record: PartRecord) -> bytes:
        local = self._local_path(record)
        if local is not None:
            data = local.read_bytes()
            if not looks_like_pdf(data):
                raise ValueError("stored datasheet is not a PDF")
            return data
        if record.datasheet is None or not allowed_image_url(record.datasheet.source_url):
            raise FileNotFoundError("no safe exact datasheet source")
        self.staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".Datasheet-",
            dir=self.staging_root,
        ) as temporary:
            target = Path(temporary) / "Datasheet.pdf"
            fetch_datasheet(record.datasheet.source_url, target)
            return target.read_bytes()

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        if operation not in self.executable_operations:
            return AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)
        try:
            record, _record_bytes = _load_exact_record(self.parts_dir, identity)
            data = self._bytes(record)
        except FileNotFoundError:
            return AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)
        except Exception:
            return AdapterOutcome.failure(FailureClassification.UNAVAILABLE)

        self.staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".Datasheet-Readback-",
            dir=self.staging_root,
        ) as temporary:
            path = Path(temporary) / "Datasheet.pdf"
            path.write_bytes(data)
            extracted = extract_datasheet_specs(
                path,
                known_mpn=identity.mpn_canonical,
                page_limit=None,
            )
        observed_mpn = None if extracted.mpn is None else extracted.mpn.value
        observed_manufacturer = (
            None if extracted.manufacturer is None else extracted.manufacturer.value
        )
        if (
            observed_mpn != identity.mpn_canonical
            or observed_manufacturer != identity.authoritative_manufacturer_key
        ):
            return AdapterOutcome.failure(FailureClassification.NEAR_MATCH_REJECTED)
        pdf_digest = self.evidence_store.install_bytes(data)
        package = None if extracted.package is None else extracted.package.value
        payload = {
            "exact_identity_verified": True,
            "manufacturer": observed_manufacturer,
            "mpn": observed_mpn,
            "package": package,
            "pdf_bytes": len(data),
            "pdf_digest": pdf_digest,
            "schema": "stockroom.exact-manufacturer-datasheet/1",
            "source_url": ("" if record.datasheet is None else record.datasheet.source_url),
        }
        digest = self.evidence_store.record_provider_success(
            identity=identity,
            operation=operation,
            provider_key=self.provider_key,
            adapter_version=_DATASHEET_ADAPTER_VERSION,
            payload=payload,
            media_type="application/json",
        )
        return AdapterOutcome.success(identity, evidence_digests=(digest,))


@dataclass(frozen=True, slots=True)
class _CopyOnWriteContext:
    profile: Profile
    repo: GitRepo
    cli: KiCadCli
    config: MachineConfig
    ops: LibraryOps
    jobs: object

    def rebuild_index(self) -> None:
        return None

    def auto_push(self) -> None:
        return None


def _copy_if_present(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _seed_copy_on_write_context(
    context: ProductionApplicationContext,
    identity: ExactPartIdentity,
    root: Path,
) -> _CopyOnWriteContext:
    """Build the smallest isolated library accepted by the existing acquisition ladder."""

    from stockroom.api.jobs import JobRunner

    live_profile = context.profile
    live_record, record_bytes = _load_exact_record(
        live_profile.library.parts_dir,
        identity,
    )
    repository = GitRepo(root)
    repository.init()
    profile = Profile(live_profile.name, root / live_profile.name)
    profile.library.ensure_layout()
    part_path = profile.library.parts_dir / f"{live_record.id}.json"
    part_path.write_bytes(record_bytes)

    live_sourced = live_profile.library.sourced_dir / live_record.id
    if live_sourced.is_dir() and not live_sourced.is_symlink():
        shutil.copytree(
            live_sourced,
            profile.library.sourced_dir / live_record.id,
            dirs_exist_ok=True,
        )

    for tool_key in ("kicad", "altium"):
        assets = live_record.assets_for(tool_key)
        for kind in ("symbol", "footprint", "model"):
            asset = assets.get(kind)
            if asset is None:
                continue
            reference = asset.ref
            candidates: list[tuple[Path, Path]] = []
            if reference.file:
                relative = PurePosixPath(reference.file)
                if not relative.is_absolute() and ".." not in relative.parts:
                    candidates.append(
                        (
                            live_profile.root.joinpath(*relative.parts),
                            profile.root.joinpath(*relative.parts),
                        )
                    )
            if reference.lib:
                relative = PurePosixPath(reference.lib)
                if not relative.is_absolute() and ".." not in relative.parts:
                    candidates.append(
                        (
                            live_profile.root.joinpath(*relative.parts),
                            profile.root.joinpath(*relative.parts),
                        )
                    )
            for source, destination in candidates:
                _copy_if_present(source, destination)

    repository.commit("Seed isolated production acquisition", [profile.root], force=True)
    operations = LibraryOps(profile, repository, context.cli)
    return _CopyOnWriteContext(
        profile=profile,
        repo=repository,
        cli=context.cli,
        config=context.config,
        ops=operations,
        jobs=JobRunner(),
    )


@dataclass(frozen=True, slots=True)
class _CaptureRequest:
    mode: str = "automatic"
    vendor: str | None = None
    background: bool = False
    report_item_id: str | None = None
    should_stop: Callable[[], bool] = field(
        default=lambda: False,
        repr=False,
        compare=False,
        hash=False,
    )


_DEFAULT_CAPTURE_REQUEST = _CaptureRequest()
_CAPTURE_PROVIDER_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z", re.ASCII)


def _capture_request(item_id: str, payload: object) -> _CaptureRequest:
    """Decode only the allowlisted durable capture options from an item payload."""

    if not isinstance(payload, Mapping) or payload.get("workflow_kind") is None:
        return _DEFAULT_CAPTURE_REQUEST
    if payload.get("workflow_kind") != "guided_capture":
        raise ProductionWorkflowError("workflow item has an unsupported workflow kind")
    capture = _mapping(payload.get("capture"), "guided capture request")
    mode = capture.get("mode")
    if mode not in {"automatic", "assisted", "finish-first", "collect-all"}:
        raise ProductionWorkflowError("guided capture mode is not supported")
    vendor = capture.get("vendor")
    if vendor is not None and (
        type(vendor) is not str or _CAPTURE_PROVIDER_KEY.fullmatch(vendor) is None
    ):
        raise ProductionWorkflowError("guided capture provider key is not canonical")
    if mode == "assisted" and vendor is None:
        raise ProductionWorkflowError("assisted guided capture requires one provider")
    background = capture.get("background")
    if type(background) is not bool:
        raise ProductionWorkflowError("guided capture background flag must be a boolean")
    if mode in {"finish-first", "collect-all"} and background:
        raise ProductionWorkflowError(f"{mode} guided capture must remain visible")
    return _CaptureRequest(
        mode=cast(str, mode),
        vendor=vendor,
        background=background,
        report_item_id=item_id,
    )


@dataclass(slots=True)
class StockroomAcquisitionProviderAdapter:
    """Use verified evidence first, then the real acquisition ladder in COW staging."""

    context: ProductionApplicationContext
    evidence_store: EvidenceStore
    staging_root: Path
    provider_key: str = _ACQUISITION_PROVIDER
    executable_operations: frozenset[ProviderOperation] = frozenset(
        {KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION}
    )
    _lock: threading.Lock = field(init=False, repr=False)
    _scope_guard: threading.Lock = field(init=False, repr=False)
    _scope_locks: dict[ExactPartIdentity, threading.Lock] = field(init=False, repr=False)
    _active_capture: dict[ExactPartIdentity, _CaptureRequest] = field(init=False, repr=False)
    _last_acquisition: dict[tuple[ExactPartIdentity, _CaptureRequest], float] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._scope_guard = threading.Lock()
        self._scope_locks = {}
        self._active_capture = {}
        self._last_acquisition = {}

    @contextmanager
    def capture_scope(
        self,
        context: StageContext,
        identity: ExactPartIdentity,
    ) -> Iterator[None]:
        """Bind one durable item's capture contract across provider worker threads."""

        request = replace(
            _capture_request(context.item.id, context.item.payload),
            should_stop=context.should_stop,
        )
        with self._scope_guard:
            identity_lock = self._scope_locks.setdefault(identity, threading.Lock())
        identity_lock.acquire()
        try:
            with self._scope_guard:
                if identity in self._active_capture:
                    raise ProductionWorkflowError(
                        "the exact identity already owns a guided capture scope"
                    )
                self._active_capture[identity] = request
            yield
        finally:
            with self._scope_guard:
                self._active_capture.pop(identity, None)
            identity_lock.release()

    def _capture_options(self, identity: ExactPartIdentity) -> _CaptureRequest:
        with self._scope_guard:
            return self._active_capture.get(identity, _DEFAULT_CAPTURE_REQUEST)

    def _selection(self, identity: ExactPartIdentity) -> ProductionCadBundle | None:
        workspace = (
            self.staging_root
            / "Selection"
            / hashlib.sha256(
                (identity.authoritative_manufacturer_key + "\0" + identity.mpn_canonical).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        selected = ExactEvidenceCadBundleAdapter().select(
            evidence_store=self.evidence_store,
            identity=identity,
            workspace=workspace,
        )
        return selected if isinstance(selected, ProductionCadBundle) else None

    def _acquire(
        self,
        identity: ExactPartIdentity,
        request: _CaptureRequest,
    ) -> None:
        now = time.monotonic()
        acquisition_key = (identity, request)
        last = self._last_acquisition.get(acquisition_key)
        if last is not None and now - last < 30.0:
            return
        self._last_acquisition[acquisition_key] = now
        self.staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".Acquisition-",
            dir=self.staging_root,
        ) as temporary:
            isolated = _seed_copy_on_write_context(
                self.context,
                identity,
                Path(temporary) / "Repository",
            )
            part_id = make_part_id(identity.mpn_canonical)
            report = run_guided_capture(
                isolated,
                part_ids=(part_id,),
                vendor=request.vendor,
                headless=request.background,
                operator_authorized=request.mode == "assisted",
                finish_first=request.mode == "finish-first",
                collect_all=request.mode == "collect-all",
                should_stop=request.should_stop,
                capture_id=request.report_item_id,
            )
            if request.report_item_id is not None:
                write_durable_capture_report(request.report_item_id, report)
            record = isolated.ops.load_record(part_id)
            try:
                record_installed_kicad_role_evidence(
                    store=self.evidence_store,
                    record=record,
                    profile=isolated.profile,
                )
            except Exception:
                # The guided pair recorder may already have installed stronger evidence,
                # and a provider that produced no complete KiCad trio is an honest miss.
                pass

    def _provider_manifest(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
        bundle: ProductionCadBundle,
    ) -> str:
        artifacts_by_role = {artifact.role: artifact for artifact in bundle.artifacts}
        if operation is KICAD_CAD_OPERATION:
            symbol = artifacts_by_role[NativeCadRole.KICAD_SYMBOL]
            footprint = artifacts_by_role[NativeCadRole.KICAD_FOOTPRINT]
        else:
            symbol = artifacts_by_role[NativeCadRole.ALTIUM_SYMBOL]
            footprint = artifacts_by_role[NativeCadRole.ALTIUM_FOOTPRINT]
        model = artifacts_by_role[NativeCadRole.STEP_MODEL]
        report = {
            "identity": {
                "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
                "mpn_canonical": identity.mpn_canonical,
            },
            "operation": operation.label,
            "provider": self.provider_key,
            "schema": "stockroom.cad-validation/1",
            "selection": dict(bundle.selection_document),
            "valid": True,
        }
        evidence_artifacts = (
            EvidenceArtifact(
                "symbol",
                self.evidence_store.object_bytes(symbol.object_digest),
                (
                    "application/vnd.kicad.symbol-library"
                    if operation is KICAD_CAD_OPERATION
                    else "application/vnd.altium.schlib"
                ),
                symbol.suggested_name,
            ),
            EvidenceArtifact(
                "footprint",
                self.evidence_store.object_bytes(footprint.object_digest),
                (
                    "application/vnd.kicad.footprint"
                    if operation is KICAD_CAD_OPERATION
                    else "application/vnd.altium.pcblib"
                ),
                footprint.suggested_name,
            ),
            EvidenceArtifact(
                "model",
                self.evidence_store.object_bytes(model.object_digest),
                "model/step",
                model.suggested_name,
            ),
            EvidenceArtifact(
                "validation_report",
                _canonical_bytes(report),
                "application/json",
                "Validation.json",
            ),
        )
        return self.evidence_store.record_provider_artifact_success(
            identity=identity,
            operation=operation,
            provider_key=self.provider_key,
            adapter_version=_ACQUISITION_ADAPTER_VERSION,
            artifacts=evidence_artifacts,
        )

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome:
        if operation not in self.executable_operations:
            return AdapterOutcome.failure(FailureClassification.UNSUPPORTED_FORMAT)
        with self._lock:
            try:
                request = self._capture_options(identity)
                bundle = self._selection(identity)
                if bundle is None or request.mode in {"finish-first", "collect-all"}:
                    self._acquire(identity, request)
                    bundle = self._selection(identity)
                if bundle is None:
                    return AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)
                digest = self._provider_manifest(identity, operation, bundle)
                return AdapterOutcome.success(identity, evidence_digests=(digest,))
            except FileNotFoundError:
                return AdapterOutcome.failure(FailureClassification.NOT_FOUND_EXACT)
            except Exception:
                return AdapterOutcome.failure(FailureClassification.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class ExactRecordSemanticAdapter:
    """Concrete reconciliation/definition/template behavior for native evidence."""

    stage: StageName
    adapter_version: str = "1.0.0"

    @property
    def adapter_key(self) -> str:
        return f"exact-record-{self.stage.value}"

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionStageCompletion | ProductionStageStop:
        if request.context.stage.name is not self.stage:
            raise ProductionWorkflowError("semantic adapter received the wrong stage")
        if self.stage is StageName.RECONCILE:
            missing = request.record.missing_fields()
            if missing:
                return ProductionStageStop(
                    ProductionStopKind.DECISION,
                    "incomplete_canonical_part_record",
                    "Canonical component facts remain incomplete after automatic providers.",
                    (request.record_digest,),
                )
            datasheet, datasheet_manifest = _provider_payload(
                request,
                StageName.DATASHEET,
                DATASHEET_OPERATION,
            )
            if (
                datasheet.get("exact_identity_verified") is not True
                or datasheet.get("manufacturer") != request.identity.authoritative_manufacturer_key
                or datasheet.get("mpn") != request.identity.mpn_canonical
            ):
                raise ProductionWorkflowError("datasheet evidence does not prove exact identity")
            pdf_digest = _string(datasheet.get("pdf_digest"), "datasheet PDF digest")
            request.evidence_store.object_bytes(pdf_digest)
            document = {
                "accepted": {
                    "category": request.record.category,
                    "description": request.record.description,
                    "display_name": request.record.display_name,
                    "manufacturer": request.record.manufacturer,
                    "mpn": request.record.mpn,
                    "package": datasheet.get("package"),
                    "part_class": request.record.part_class.value,
                    "specs": request.record.specs,
                    "value": request.record.value,
                },
                "datasheet_manifest_digest": datasheet_manifest,
                "datasheet_pdf_digest": pdf_digest,
                "part_record_digest": request.record_digest,
                "schema": "stockroom.production-exact-reconciliation/1",
            }
            return ProductionStageCompletion(
                document,
                (datasheet_manifest, pdf_digest, request.record_digest),
            )

        reconciliation = _prior_document(request, StageName.RECONCILE)
        reconciliation_digest = _string(
            _prior_result(request, StageName.RECONCILE).get("document_digest"),
            "reconciliation digest",
        )
        if self.stage is StageName.CANONICAL_DEFINITION:
            identity = derive_component_identity(
                request.identity.authoritative_manufacturer_key,
                request.identity.mpn_canonical,
            )
            document = {
                "component_id": identity.component_id,
                "exact_identity": {
                    "authoritative_manufacturer_key": (
                        request.identity.authoritative_manufacturer_key
                    ),
                    "mpn_canonical": request.identity.mpn_canonical,
                },
                "facts": reconciliation["accepted"],
                "part_record_digest": request.record_digest,
                "reconciliation_digest": reconciliation_digest,
                "schema": "stockroom.production-native-definition/1",
                "strategy": "exact-native-dual-eda",
            }
            return ProductionStageCompletion(
                document,
                (request.record_digest, reconciliation_digest),
            )

        definition = _prior_document(request, StageName.CANONICAL_DEFINITION)
        definition_digest = _string(
            _prior_result(request, StageName.CANONICAL_DEFINITION).get("document_digest"),
            "definition digest",
        )
        document = {
            "component_id": definition["component_id"],
            "definition_digest": definition_digest,
            "required_common_roles": [
                "symbol",
                "footprint",
                "neutral_step_model",
            ],
            "schema": "stockroom.production-native-template-plan/1",
            "strategy": "retain-provider-native-and-cross-verify",
            "tool_targets": ["kicad", "altium"],
        }
        return ProductionStageCompletion(
            document,
            (request.record_digest, reconciliation_digest, definition_digest),
        )


def _git_bytes(
    repository: GitRepo,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        [repository.git, "-C", str(repository.root), *arguments],
        capture_output=True,
        creationflags=_WINDOWS_NO_WINDOW,
        env=environment,
        timeout=120.0,
    )
    if check and completed.returncode != 0:
        raise ProductionWorkflowError("read-only Git evidence lookup failed")
    return completed


def _git_blob(
    repository: GitRepo,
    revision: str,
    relative_path: str,
) -> bytes | None:
    if not repository.has_commit(revision):
        raise ProductionWorkflowError("publication base commit is unavailable")
    specification = f"{revision}:{relative_path}"
    exists = _git_bytes(repository, "cat-file", "-e", specification, check=False)
    if exists.returncode != 0:
        return None
    return _git_bytes(repository, "show", specification).stdout


def _git_paths(
    repository: GitRepo,
    revision: str,
    prefix: str,
) -> tuple[str, ...]:
    output = _git_bytes(
        repository,
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        revision,
        "--",
        prefix,
    ).stdout
    paths: list[str] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProductionWorkflowError("Git tree path is not canonical UTF-8") from exc
        parsed = PurePosixPath(value)
        if (
            parsed.is_absolute()
            or parsed.as_posix() != value
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise ProductionWorkflowError("Git tree path is not canonical")
        paths.append(value)
    if len({path.casefold() for path in paths}) != len(paths):
        raise ProductionWorkflowError("Git tree contains a Windows path collision")
    return tuple(sorted(paths, key=str.casefold))


def _relative_repo_path(repository: GitRepo, path: Path, label: str) -> PurePosixPath:
    try:
        relative = path.resolve(strict=True).relative_to(repository.root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProductionWorkflowError(f"{label} is outside the library repository") from exc
    value = PurePosixPath(relative.as_posix())
    if any(part in {"", ".", ".."} for part in value.parts):
        raise ProductionWorkflowError(f"{label} is not a canonical repository path")
    return value


def _write_exact(path: Path, data: bytes) -> None:
    if not data:
        raise ProductionWorkflowError("prepared publication files must be non-empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != data:
            raise ProductionWorkflowError("durable prepared publication bytes differ")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".temporary",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    if path.read_bytes() != data:
        raise ProductionWorkflowError("prepared publication failed exact-byte readback")


def _validated_catalog_row(value: object) -> dict[str, str]:
    row = _mapping(value, "catalog row")
    if set(row) != set(PART_COLUMNS) or any(type(item) is not str for item in row.values()):
        raise ProductionWorkflowError("catalog row does not match the exact schema")
    exact = {column: cast(str, row[column]) for column in PART_COLUMNS}
    if (
        not exact["Component ID"]
        or not exact["Manufacturer ID"]
        or not exact["Manufacturer"]
        or not exact["MPN"]
    ):
        raise ProductionWorkflowError("catalog row omits exact component identity")
    return exact


def _validated_catalog_rows(values: object) -> list[dict[str, str]]:
    rows = [_validated_catalog_row(value) for value in _sequence(values, "catalog rows")]
    if rows != sorted(rows, key=lambda row: row["Component ID"]):
        raise ProductionWorkflowError("catalog rows are not in canonical component order")
    component_ids = [row["Component ID"] for row in rows]
    exact_identities = [(row["Manufacturer"], row["MPN"]) for row in rows]
    if len(set(component_ids)) != len(component_ids) or len(set(exact_identities)) != len(
        exact_identities
    ):
        raise ProductionWorkflowError("catalog rows contain a duplicate exact identity")
    return rows


def _published_row_from_record(record: PartRecord) -> dict[str, str] | None:
    raw = record.extra.get(_PRODUCTION_METADATA_KEY)
    if raw is None:
        return None
    publication = _mapping(raw, "PartRecord production publication")
    if publication.get("schema") != "stockroom.production-publication/1":
        raise ProductionWorkflowError("PartRecord production publication has an unknown schema")
    return _validated_catalog_row(publication.get("catalog_row"))


def _base_catalog_rows(
    repository: GitRepo,
    revision: str,
    *,
    profile_relative: PurePosixPath,
    parts_relative: PurePosixPath,
) -> list[dict[str, str]]:
    digest_path = (profile_relative / "Catalog" / "Catalog Digest.json").as_posix()
    digest_bytes = _git_blob(repository, revision, digest_path)
    digest_rows: list[dict[str, str]] | None = None
    if digest_bytes is not None:
        try:
            digest_document = json.loads(digest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionWorkflowError("committed catalog digest is invalid") from exc
        digest = _mapping(digest_document, "committed catalog digest")
        if (
            digest.get("schema") != "stockroom.production-catalog-digest/1"
            or digest_bytes != _canonical_bytes(digest_document) + b"\n"
        ):
            raise ProductionWorkflowError("committed catalog digest is not canonical")
        digest_rows = _validated_catalog_rows(digest.get("parts"))

    record_rows: list[dict[str, str]] = []
    prefix = parts_relative.as_posix()
    for path in _git_paths(repository, revision, prefix):
        if PurePosixPath(path).suffix.casefold() != ".json":
            continue
        data = _git_blob(repository, revision, path)
        if data is None:
            raise ProductionWorkflowError("committed PartRecord disappeared during lookup")
        try:
            record = PartRecord.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
            raise ProductionWorkflowError("committed PartRecord is invalid") from exc
        row = _published_row_from_record(record)
        if row is not None:
            record_rows.append(row)
    record_rows.sort(key=lambda row: row["Component ID"])
    record_rows = _validated_catalog_rows(record_rows)
    if digest_rows is None:
        return record_rows
    by_component = {row["Component ID"]: row for row in digest_rows}
    if any(by_component.get(row["Component ID"]) != row for row in record_rows):
        raise ProductionWorkflowError(
            "committed PartRecord publication rows differ from the catalog digest"
        )
    return digest_rows


def _catalog_identity(
    rows: list[dict[str, str]],
) -> tuple[str, str, str, dict[str, object]]:
    base_metadata = {
        "artifact_role": "activation_only",
        "component_count": str(len(rows)),
        "fixture_mode": "false",
        "projection": "stockroom.catalog",
        "schema_version": str(CATALOG_SCHEMA_VERSION),
    }
    row_digest = _digest(_canonical_bytes(rows))
    semantic_document = {
        "links": {
            "altium": {
                "database_filename": CATALOG_FILENAME,
                "format_version": "1.1",
                "key_column": "MPN",
                "table": CATALOG_TABLE,
            },
            "kicad": json.loads(render_kicad_dbl()),
        },
        "metadata": base_metadata,
        "parts": rows,
        "schema": {
            "application_id": CATALOG_APPLICATION_ID,
            "columns": list(PART_COLUMNS),
            "schema_version": CATALOG_SCHEMA_VERSION,
            "table": CATALOG_TABLE,
        },
    }
    raw_digest = hashlib.sha256(_canonical_bytes(semantic_document)).digest()
    semantic_digest = digest_text(raw_digest)
    revision = digest_id("catrev", raw_digest)
    return semantic_digest, revision, row_digest, semantic_document


def _catalog_metadata(
    rows: list[dict[str, str]],
    semantic_digest: str,
    revision: str,
    row_digest: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                "artifact_role": "activation_only",
                "catalog_revision": revision,
                "catalog_semantic_digest": semantic_digest,
                "component_count": str(len(rows)),
                "fixture_mode": "false",
                "projection": "stockroom.catalog",
                "schema_version": str(CATALOG_SCHEMA_VERSION),
                "semantic_row_digest": row_digest,
            }.items()
        )
    )


def _write_catalog(
    path: Path,
    rows: list[dict[str, str]],
    *,
    semantic_digest: str,
    revision: str,
    row_digest: str,
) -> None:
    if not rows:
        raise ProductionWorkflowError("a production catalog cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".Catalog.",
        suffix=".sqlite",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(temporary, isolation_level=None)
        connection.execute("PRAGMA page_size = 4096")
        connection.execute(f"PRAGMA application_id = {CATALOG_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION}")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE catalog_metadata (
                key TEXT PRIMARY KEY COLLATE BINARY,
                value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        connection.executemany(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            _catalog_metadata(rows, semantic_digest, revision, row_digest),
        )
        definitions = ", ".join(
            f'"{column}" TEXT NOT NULL'
            + (" PRIMARY KEY COLLATE BINARY" if column == "Component ID" else "")
            for column in PART_COLUMNS
        )
        connection.execute(f'CREATE TABLE "{CATALOG_TABLE}" ({definitions}) WITHOUT ROWID')
        connection.execute(
            f"""
            CREATE UNIQUE INDEX parts_exact_manufacturer_mpn
            ON "{CATALOG_TABLE}"("Manufacturer" COLLATE BINARY, "MPN" COLLATE BINARY)
            """
        )
        quoted = ", ".join(f'"{column}"' for column in PART_COLUMNS)
        placeholders = ", ".join("?" for _ in PART_COLUMNS)
        connection.executemany(
            f'INSERT INTO "{CATALOG_TABLE}" ({quoted}) VALUES ({placeholders})',
            (tuple(row[column] for column in PART_COLUMNS) for row in rows),
        )
        connection.execute("COMMIT")
        connection.execute("VACUUM")
        connection.close()
        connection = None

        validation = sqlite3.connect(f"{temporary.resolve().as_uri()}?mode=ro", uri=True)
        try:
            validation.row_factory = sqlite3.Row
            integrity = validation.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = validation.execute("PRAGMA foreign_key_check").fetchall()
            application_id = validation.execute("PRAGMA application_id").fetchone()[0]
            user_version = validation.execute("PRAGMA user_version").fetchone()[0]
            columns = tuple(
                str(row["name"])
                for row in validation.execute(f'PRAGMA table_info("{CATALOG_TABLE}")')
            )
            metadata = tuple(
                (str(row["key"]), str(row["value"]))
                for row in validation.execute(
                    "SELECT key, value FROM catalog_metadata ORDER BY key"
                )
            )
            actual_rows = [
                {column: str(row[column]) for column in PART_COLUMNS}
                for row in validation.execute(
                    f'SELECT * FROM "{CATALOG_TABLE}" ORDER BY "Component ID"'
                )
            ]
        finally:
            validation.close()
        if (
            integrity != "ok"
            or foreign_keys
            or application_id != CATALOG_APPLICATION_ID
            or user_version != CATALOG_SCHEMA_VERSION
            or columns != PART_COLUMNS
            or metadata != _catalog_metadata(rows, semantic_digest, revision, row_digest)
            or actual_rows != rows
        ):
            raise ProductionWorkflowError("staged catalog failed exact SQLite readback")
        os.replace(temporary, path)
    except BaseException:
        if connection is not None:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _portable_tables(rows: list[dict[str, str]]) -> tuple[bytes, bytes]:
    symbols = LibTable.new("sym_lib_table")
    footprints = LibTable.new("fp_lib_table")
    for row in rows:
        symbol_reference = row["KiCad Symbol Ref"]
        footprint_reference = row["KiCad Footprint Ref"]
        symbol_nickname, symbol_separator, _symbol_entry = symbol_reference.partition(":")
        footprint_nickname, footprint_separator, _footprint_entry = footprint_reference.partition(
            ":"
        )
        if not symbol_separator or not footprint_separator or symbol_nickname != footprint_nickname:
            raise ProductionWorkflowError("catalog KiCad references are not coherent")
        description = f"{row['Manufacturer']} {row['MPN']}"
        if not symbols.append_kicad_lib(
            symbol_nickname,
            f"${{SR_LIB}}/{row['KiCad Symbol Artifact Path']}",
            description,
        ):
            raise ProductionWorkflowError("catalog contains a duplicate KiCad symbol library")
        footprint_directory = PurePosixPath(row["KiCad Footprint Artifact Path"]).parent
        if not footprints.append_kicad_lib(
            footprint_nickname,
            f"${{SR_LIB}}/{footprint_directory.as_posix()}",
            description,
        ):
            raise ProductionWorkflowError("catalog contains a duplicate KiCad footprint library")
    return symbols.serialize().encode("utf-8"), footprints.serialize().encode("utf-8")


def _publication_head(record: PartRecord, component_id: str) -> str | None:
    raw = record.extra.get(_PRODUCTION_METADATA_KEY)
    if raw is None:
        return None
    publication = _mapping(raw, "PartRecord production publication")
    if (
        publication.get("schema") != "stockroom.production-publication/1"
        or publication.get("component_id") != component_id
    ):
        raise ProductionWorkflowError("PartRecord production publication identity differs")
    value = _string(publication.get("publication_id"), "previous publication ID")
    if re.fullmatch(r"pub_[a-z2-7]{52}", value, re.ASCII) is None:
        raise ProductionWorkflowError("previous publication ID is not canonical")
    return value


def _native_artifacts(
    request: ProductionStageRequest,
) -> dict[NativeCadRole, tuple[str, str]]:
    result = _prior_result(request, StageName.NATIVE_CONVERSION_ACQUISITION)
    if result.get("schema") != "stockroom.production-native-cad/1":
        raise ProductionWorkflowError("native CAD result has an unknown schema")
    artifacts: dict[NativeCadRole, tuple[str, str]] = {}
    names: set[str] = set()
    for raw in _sequence(result.get("artifacts"), "native CAD artifacts"):
        artifact = _mapping(raw, "native CAD artifact")
        role = NativeCadRole(_string(artifact.get("role"), "native CAD role"))
        digest = _string(artifact.get("object_digest"), "native CAD digest")
        name = _string(artifact.get("suggested_name"), "native CAD filename")
        if (
            _SHA256.fullmatch(digest) is None
            or PurePosixPath(name).name != name
            or name.casefold() in names
        ):
            raise ProductionWorkflowError("native CAD artifact is not canonical")
        data = request.evidence_store.object_bytes(digest)
        if _digest(data) != digest:
            raise ProductionWorkflowError("native CAD artifact bytes differ")
        names.add(name.casefold())
        artifacts[role] = (digest, name)
    if tuple(artifacts) != tuple(NativeCadRole):
        raise ProductionWorkflowError("native CAD role matrix is incomplete")
    return artifacts


def _readback_document(
    request: ProductionStageRequest,
    stage: StageName,
) -> tuple[Mapping[str, object], str]:
    result = _prior_result(request, stage)
    digest = _string(result.get("readback_report_digest"), "readback report digest")
    try:
        document = json.loads(request.evidence_store.object_bytes(digest))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionWorkflowError("native CAD readback report is invalid") from exc
    report = _mapping(document, "native CAD readback report")
    if report.get("valid") is not True:
        raise ProductionWorkflowError("native CAD readback report is not valid")
    return report, digest


def _first_purchase(record: PartRecord) -> Mapping[str, object]:
    if not record.purchase:
        return {}
    purchase = record.purchase[0]
    return {
        "currency": purchase.currency,
        "part_number": purchase.part_number,
        "price_breaks": purchase.price_breaks,
        "stock": purchase.stock,
        "url": purchase.url,
        "vendor": purchase.vendor,
    }


@dataclass(frozen=True, slots=True)
class ExactNativePublicationAdapter:
    """Build one cumulative dual-EDA projection without touching the live library."""

    repository: GitRepo
    profile: Profile
    evidence_store: EvidenceStore
    live_catalog_path: Path
    machine_local_root: Path
    adapter_key: str = "exact-native-publication"
    adapter_version: str = "1.0.0"

    def _candidate(
        self,
        request: ProductionPublicationRequest,
    ) -> tuple[dict[str, object], tuple[str, ...], str | None]:
        stage = request.stage
        identity = derive_component_identity(
            stage.identity.authoritative_manufacturer_key,
            stage.identity.mpn_canonical,
        )
        definition_result = _prior_result(stage, StageName.CANONICAL_DEFINITION)
        definition_digest = _string(
            definition_result.get("document_digest"),
            "canonical definition digest",
        )
        template_result = _prior_result(stage, StageName.TEMPLATE_GENERATION)
        template_digest = _string(
            template_result.get("document_digest"),
            "template plan digest",
        )
        native = _native_artifacts(stage)
        native_digests = {role.value: digest for role, (digest, _name) in native.items()}
        selection_result = _prior_result(
            stage,
            StageName.NATIVE_CONVERSION_ACQUISITION,
        )
        selection_digest = _string(
            selection_result.get("selection_digest"),
            "CAD selection digest",
        )
        cross_result = _prior_result(stage, StageName.CROSS_EDA_VERIFICATION)
        cross_digest = _string(cross_result.get("report_digest"), "cross-EDA digest")
        canonical_bundle_digest = _digest(
            _canonical_bytes(
                {
                    "definition_digest": definition_digest,
                    "part_record_digest": stage.record_digest,
                    "template_plan_digest": template_digest,
                }
            )
        )
        for digest in (
            definition_digest,
            template_digest,
            selection_digest,
            cross_digest,
            *native_digests.values(),
        ):
            stage.evidence_store.object_bytes(digest)
        previous = _publication_head(stage.record, identity.component_id)
        document: dict[str, object] = {
            "canonical_bundle_digest": canonical_bundle_digest,
            "definition_digest": definition_digest,
            "native_artifacts": native_digests,
            "part_record_digest": stage.record_digest,
            "previous_publication_id": previous,
            "publication_scope": "one_exact_component_cumulative_catalog",
            "schema": "stockroom.exact-native-publication-candidate/1",
            "selection_digest": selection_digest,
            "template_plan_digest": template_digest,
            "verification_digest": cross_digest,
        }
        evidence = tuple(
            sorted(
                {
                    stage.record_digest,
                    definition_digest,
                    template_digest,
                    selection_digest,
                    cross_digest,
                    *native_digests.values(),
                }
            )
        )
        return document, evidence, previous

    def prepare_candidate(
        self,
        request: ProductionPublicationRequest,
        /,
    ) -> ProductionPublicationCandidate:
        document, evidence, previous = self._candidate(request)
        return ProductionPublicationCandidate(
            document,
            evidence,
            expected_head_publication_id=previous,
        )

    def _paths(
        self,
        stage: ProductionStageRequest,
        candidate_digest: str,
    ) -> tuple[
        PurePosixPath,
        PurePosixPath,
        dict[NativeCadRole, PurePosixPath],
        dict[NativeCadRole, PurePosixPath],
    ]:
        profile_relative = _relative_repo_path(
            self.repository,
            self.profile.root,
            "active profile",
        )
        parts_relative = _relative_repo_path(
            self.repository,
            self.profile.library.parts_dir,
            "active parts directory",
        )
        identity = derive_component_identity(
            stage.identity.authoritative_manufacturer_key,
            stage.identity.mpn_canonical,
        )
        digest = candidate_digest.removeprefix("sha256:")
        artifacts = _native_artifacts(stage)
        symbol_name = artifacts[NativeCadRole.KICAD_SYMBOL][1]
        footprint_name = artifacts[NativeCadRole.KICAD_FOOTPRINT][1]
        model_name = artifacts[NativeCadRole.STEP_MODEL][1]
        altium_symbol_name = artifacts[NativeCadRole.ALTIUM_SYMBOL][1]
        altium_footprint_name = artifacts[NativeCadRole.ALTIUM_FOOTPRINT][1]
        footprint_library = f"{Path(footprint_name).stem}.pretty"
        repo_paths = {
            NativeCadRole.KICAD_SYMBOL: (
                profile_relative
                / "EDA"
                / "KiCad"
                / "Symbols"
                / identity.component_id
                / digest
                / symbol_name
            ),
            NativeCadRole.KICAD_FOOTPRINT: (
                profile_relative
                / "EDA"
                / "KiCad"
                / "Footprints"
                / identity.component_id
                / digest
                / footprint_library
                / footprint_name
            ),
            # Keep the exact provider STEP beside the exact footprint. Foreign
            # footprints commonly carry a basename-only model reference; this
            # preserves that already-verified link without rewriting either file.
            NativeCadRole.STEP_MODEL: (
                profile_relative
                / "EDA"
                / "KiCad"
                / "Footprints"
                / identity.component_id
                / digest
                / footprint_library
                / model_name
            ),
            NativeCadRole.ALTIUM_SYMBOL: (
                profile_relative
                / "EDA"
                / "Altium"
                / "Symbols"
                / identity.component_id
                / digest
                / altium_symbol_name
            ),
            NativeCadRole.ALTIUM_FOOTPRINT: (
                profile_relative
                / "EDA"
                / "Altium"
                / "Footprints"
                / identity.component_id
                / digest
                / altium_footprint_name
            ),
        }
        profile_paths = {
            role: PurePosixPath(*path.relative_to(profile_relative).parts)
            for role, path in repo_paths.items()
        }
        return profile_relative, parts_relative, repo_paths, profile_paths

    def _catalog_row(
        self,
        stage: ProductionStageRequest,
        candidate: Mapping[str, object],
        candidate_digest: str,
        repo_paths: Mapping[NativeCadRole, PurePosixPath],
        profile_paths: Mapping[NativeCadRole, PurePosixPath],
    ) -> tuple[dict[str, str], str, str, str, str]:
        identity = derive_component_identity(
            stage.identity.authoritative_manufacturer_key,
            stage.identity.mpn_canonical,
        )
        kicad_report, kicad_report_digest = _readback_document(
            stage,
            StageName.KICAD_BUILD_READBACK,
        )
        altium_report, altium_report_digest = _readback_document(
            stage,
            StageName.ALTIUM_BUILD_READBACK,
        )
        kicad_symbol_entry = _string(
            kicad_report.get("symbol_entry"),
            "KiCad symbol entry",
        )
        kicad_footprint_entry = _string(
            kicad_report.get("footprint_entry"),
            "KiCad footprint entry",
        )
        altium_symbol_entry = _string(
            altium_report.get("symbol_entry"),
            "Altium symbol entry",
        )
        altium_footprint_entry = _string(
            altium_report.get("footprint_entry"),
            "Altium footprint entry",
        )
        native = _mapping(candidate.get("native_artifacts"), "candidate native artifacts")
        nickname = f"Stockroom_{identity.component_id}"
        reconciliation = _prior_document(stage, StageName.RECONCILE)
        facts = _mapping(reconciliation.get("accepted"), "reconciled facts")
        purchase = _first_purchase(stage.record)
        datasheet_url = "" if stage.record.datasheet is None else stage.record.datasheet.source_url
        price_breaks = purchase.get("price_breaks")
        price = ""
        if isinstance(price_breaks, list) and price_breaks:
            first = price_breaks[0]
            if isinstance(first, Mapping):
                raw_price = first.get("price")
                if raw_price is not None:
                    price = str(raw_price)
        row = {column: "" for column in PART_COLUMNS}
        row.update(
            {
                "Altium Footprint Artifact Digest": _string(
                    native.get(NativeCadRole.ALTIUM_FOOTPRINT.value),
                    "Altium footprint digest",
                ),
                "Altium Footprint Artifact Path": (
                    PurePosixPath(
                        *profile_paths[NativeCadRole.ALTIUM_FOOTPRINT].parts[2:]
                    ).as_posix()
                ),
                "Altium Footprint Template ID": "native.evidence.footprint.v1",
                "Altium Symbol Artifact Digest": _string(
                    native.get(NativeCadRole.ALTIUM_SYMBOL.value),
                    "Altium symbol digest",
                ),
                "Altium Symbol Artifact Path": (
                    PurePosixPath(*profile_paths[NativeCadRole.ALTIUM_SYMBOL].parts[2:]).as_posix()
                ),
                "Altium Symbol Template ID": "native.evidence.symbol.v1",
                "Artifact Set Digest": _digest(_canonical_bytes(dict(native))),
                "Canonical Bundle Digest": _string(
                    candidate.get("canonical_bundle_digest"),
                    "canonical bundle digest",
                ),
                "Category": stage.record.category,
                "Comment": stage.record.value,
                "Component ID": identity.component_id,
                "ComponentLink1Description": ("Datasheet" if datasheet_url else ""),
                "ComponentLink1URL": datasheet_url,
                "Definition Digest": _string(
                    candidate.get("definition_digest"),
                    "definition digest",
                ),
                "Description": stage.record.description,
                "Footprint Path": (
                    PurePosixPath(
                        *profile_paths[NativeCadRole.ALTIUM_FOOTPRINT].parts[2:]
                    ).as_posix()
                ),
                "Footprint Ref": altium_footprint_entry,
                "KiCad Footprint Artifact Digest": _string(
                    native.get(NativeCadRole.KICAD_FOOTPRINT.value),
                    "KiCad footprint digest",
                ),
                "KiCad Footprint Artifact Path": profile_paths[
                    NativeCadRole.KICAD_FOOTPRINT
                ].as_posix(),
                "KiCad Footprint Ref": f"{nickname}:{kicad_footprint_entry}",
                "KiCad Footprint Template ID": "native.evidence.footprint.v1",
                "KiCad Symbol Artifact Digest": _string(
                    native.get(NativeCadRole.KICAD_SYMBOL.value),
                    "KiCad symbol digest",
                ),
                "KiCad Symbol Artifact Path": profile_paths[NativeCadRole.KICAD_SYMBOL].as_posix(),
                "KiCad Symbol Ref": f"{nickname}:{kicad_symbol_entry}",
                "KiCad Symbol Template ID": "native.evidence.symbol.v1",
                "Library Path": (
                    PurePosixPath(*profile_paths[NativeCadRole.ALTIUM_SYMBOL].parts[2:]).as_posix()
                ),
                "Library Ref": altium_symbol_entry,
                "Lifecycle": str(stage.record.specs.get("lifecycle", "")),
                "MPN": stage.record.mpn,
                "Manufacturer": stage.record.manufacturer,
                "Manufacturer ID": identity.manufacturer_id,
                "Package": str(facts.get("package") or stage.record.specs.get("package") or ""),
                "Price": price,
                "Stock": ("" if purchase.get("stock") is None else str(purchase.get("stock"))),
                "Stockroom ID": stage.record.id,
                "Supplier": str(purchase.get("vendor") or ""),
                "SupplierPartNumber": str(purchase.get("part_number") or ""),
                "SupplierURL": str(purchase.get("url") or ""),
                "Value": stage.record.value,
                "Verification Digest": _string(
                    candidate.get("verification_digest"),
                    "verification digest",
                ),
            }
        )
        return (
            _validated_catalog_row(row),
            kicad_symbol_entry,
            kicad_footprint_entry,
            altium_symbol_entry,
            altium_footprint_entry,
        )

    def _stage_tracked(
        self,
        root: Path,
        relative: PurePosixPath,
        data: bytes,
        *,
        expected_base_commit: str,
        tracked: list[PreparedTarget],
    ) -> None:
        target_path = relative.as_posix()
        _write_exact(root.joinpath(*relative.parts), data)
        previous = _git_blob(self.repository, expected_base_commit, target_path)
        if previous != data:
            tracked.append(PreparedTarget(target_path, _digest(data)))

    def prepare_manifest(
        self,
        request: ProductionPublicationRequest,
        /,
        *,
        candidate_document: Mapping[str, object],
        candidate_digest: str,
        publication_id: str,
    ) -> PreparedPublicationManifest:
        if _digest(_canonical_bytes(dict(candidate_document))) != candidate_digest:
            raise ProductionWorkflowError("publication candidate digest differs")
        expected_candidate, _evidence, previous = self._candidate(request)
        adapter_candidate = _mapping(
            candidate_document.get("candidate"),
            "publication adapter candidate",
        )
        if dict(adapter_candidate) != expected_candidate:
            raise ProductionWorkflowError("publication candidate changed during preparation")
        stage = request.stage
        identity = derive_component_identity(
            stage.identity.authoritative_manufacturer_key,
            stage.identity.mpn_canonical,
        )
        if candidate_document.get("component_id") != identity.component_id:
            raise ProductionWorkflowError("publication candidate component identity differs")
        (
            profile_relative,
            parts_relative,
            repo_paths,
            profile_paths,
        ) = self._paths(stage, candidate_digest)
        root = (stage.workspace / "Prepared Publication" / publication_id).absolute()
        root.mkdir(parents=True, exist_ok=True)
        try:
            root.resolve(strict=True).relative_to(self.repository.root.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ProductionWorkflowError("publication staging cannot be inside the repository")

        native = _native_artifacts(stage)
        tracked: list[PreparedTarget] = []
        for role in NativeCadRole:
            digest, _name = native[role]
            data = stage.evidence_store.object_bytes(digest)
            self._stage_tracked(
                root,
                repo_paths[role],
                data,
                expected_base_commit=request.expected_base_commit,
                tracked=tracked,
            )

        component_root = profile_relative / "Components" / identity.component_id
        definition_digest = _string(
            adapter_candidate.get("definition_digest"),
            "definition digest",
        )
        template_digest = _string(
            adapter_candidate.get("template_plan_digest"),
            "template plan digest",
        )
        verification_digest = _string(
            adapter_candidate.get("verification_digest"),
            "verification digest",
        )
        component_files = {
            component_root / "Component.json": _canonical_bytes(
                {
                    "canonical_bundle_digest": adapter_candidate["canonical_bundle_digest"],
                    "component_id": identity.component_id,
                    "manufacturer": stage.identity.authoritative_manufacturer_key,
                    "manufacturer_id": identity.manufacturer_id,
                    "mpn": stage.identity.mpn_canonical,
                    "part_record_id": stage.record.id,
                    "schema": "stockroom.production-component/1",
                }
            )
            + b"\n",
            component_root / "Definition.json": stage.evidence_store.object_bytes(
                definition_digest
            ),
            component_root / "Template Plan.json": stage.evidence_store.object_bytes(
                template_digest
            ),
            component_root / "Verification.json": stage.evidence_store.object_bytes(
                verification_digest
            ),
            component_root / "Publication Candidate.json": (
                _canonical_bytes(dict(candidate_document)) + b"\n"
            ),
        }
        for relative, data in component_files.items():
            self._stage_tracked(
                root,
                relative,
                data,
                expected_base_commit=request.expected_base_commit,
                tracked=tracked,
            )

        selection_digest = _string(
            adapter_candidate.get("selection_digest"),
            "selection digest",
        )
        try:
            selection = json.loads(stage.evidence_store.object_bytes(selection_digest))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionWorkflowError("CAD selection evidence is invalid") from exc
        selected = _mapping(selection, "CAD selection evidence")
        kicad_manifest = _string(
            selected.get("kicad_manifest_digest"),
            "KiCad evidence manifest",
        )
        altium_manifest = _string(
            selected.get("altium_manifest_digest"),
            "Altium evidence manifest",
        )
        kicad_variant = resolve_cad_variant(
            stage.evidence_store,
            identity=stage.identity,
            tool="kicad",
            manifest_digest=kicad_manifest,
        )
        altium_variant = resolve_cad_variant(
            stage.evidence_store,
            identity=stage.identity,
            tool="altium",
            manifest_digest=altium_manifest,
        )
        if not same_cad_evidence_set(
            kicad_variant.descriptor,
            altium_variant.descriptor,
        ):
            raise ProductionWorkflowError(
                "publication candidate does not resolve to one provider evidence set"
            )

        (
            catalog_row,
            kicad_symbol_entry,
            kicad_footprint_entry,
            altium_symbol_entry,
            altium_footprint_entry,
        ) = self._catalog_row(
            stage,
            adapter_candidate,
            candidate_digest,
            repo_paths,
            profile_paths,
        )
        updated_record = PartRecord.loads(stage.record.dumps())
        origin = AssetOrigin(
            vendor=kicad_variant.descriptor.provider,
            extra={
                "altium_evidence_manifest": altium_manifest,
                "candidate_digest": candidate_digest,
                "evidence_set_manifest": kicad_manifest,
                "kicad_evidence_manifest": kicad_manifest,
                "verification_digest": verification_digest,
            },
        )
        nickname = f"Stockroom_{identity.component_id}"
        updated_record.assets_for("kicad").symbol = Asset(
            AssetRef(lib=nickname, name=kicad_symbol_entry),
            origin,
        )
        updated_record.assets_for("kicad").footprint = Asset(
            AssetRef(lib=nickname, name=kicad_footprint_entry),
            origin,
        )
        updated_record.assets_for("kicad").model = Asset(
            AssetRef(file=profile_paths[NativeCadRole.STEP_MODEL].as_posix()),
            origin,
        )
        updated_record.assets_for("altium").symbol = Asset(
            AssetRef(
                lib=profile_paths[NativeCadRole.ALTIUM_SYMBOL].as_posix(),
                name=altium_symbol_entry,
            ),
            origin,
        )
        updated_record.assets_for("altium").footprint = Asset(
            AssetRef(
                lib=profile_paths[NativeCadRole.ALTIUM_FOOTPRINT].as_posix(),
                name=altium_footprint_entry,
            ),
            origin,
        )
        updated_record.assets_for("altium").model = Asset(
            AssetRef(file=profile_paths[NativeCadRole.STEP_MODEL].as_posix()),
            origin,
        )
        updated_record.cad_variants.select("kicad", kicad_variant.pointer)
        updated_record.cad_variants.select("altium", altium_variant.pointer)
        updated_record.extra[_PRODUCTION_METADATA_KEY] = {
            "candidate_digest": candidate_digest,
            "catalog_row": catalog_row,
            "component_id": identity.component_id,
            "previous_publication_id": previous,
            "publication_id": publication_id,
            "schema": "stockroom.production-publication/1",
        }
        record_relative = parts_relative / f"{updated_record.id}.json"
        self._stage_tracked(
            root,
            record_relative,
            updated_record.dumps().encode("utf-8"),
            expected_base_commit=request.expected_base_commit,
            tracked=tracked,
        )

        rows = _base_catalog_rows(
            self.repository,
            request.expected_base_commit,
            profile_relative=profile_relative,
            parts_relative=parts_relative,
        )
        by_component = {row["Component ID"]: row for row in rows}
        for row in rows:
            if (row["Manufacturer"], row["MPN"]) == (
                catalog_row["Manufacturer"],
                catalog_row["MPN"],
            ) and row["Component ID"] != identity.component_id:
                raise ProductionWorkflowError(
                    "catalog exact identity resolves to a different component ID"
                )
        by_component[identity.component_id] = catalog_row
        rows = sorted(by_component.values(), key=lambda row: row["Component ID"])
        rows = _validated_catalog_rows(rows)
        semantic_digest, revision, row_digest, semantic_document = _catalog_identity(rows)
        catalog_document = {
            "catalog_revision": revision,
            "catalog_semantic_digest": semantic_digest,
            "outputs": [
                {
                    "filename": "Catalog Digest.json",
                    "role": "tracked_portable",
                },
                {
                    "filename": "Stockroom.kicad_dbl",
                    "role": "tracked_portable",
                },
                {
                    "filename": CATALOG_FILENAME,
                    "role": "activation_only",
                },
                {
                    "filename": "Stockroom.DbLib",
                    "role": "machine_local",
                },
            ],
            "parts": rows,
            "schema": "stockroom.production-catalog-digest/1",
            "schema_version": CATALOG_SCHEMA_VERSION,
            "semantic_document_digest": _digest(_canonical_bytes(semantic_document)),
            "semantic_row_digest": row_digest,
        }
        catalog_digest_relative = profile_relative / "Catalog" / "Catalog Digest.json"
        self._stage_tracked(
            root,
            catalog_digest_relative,
            _canonical_bytes(catalog_document) + b"\n",
            expected_base_commit=request.expected_base_commit,
            tracked=tracked,
        )
        kicad_dbl_relative = profile_relative / "EDA" / "KiCad" / "Stockroom.kicad_dbl"
        self._stage_tracked(
            root,
            kicad_dbl_relative,
            render_kicad_dbl(),
            expected_base_commit=request.expected_base_commit,
            tracked=tracked,
        )
        symbol_table, footprint_table = _portable_tables(rows)
        self._stage_tracked(
            root,
            profile_relative / "EDA" / "KiCad" / _PORTABLE_SYMBOL_TABLE,
            symbol_table,
            expected_base_commit=request.expected_base_commit,
            tracked=tracked,
        )
        self._stage_tracked(
            root,
            profile_relative / "EDA" / "KiCad" / _PORTABLE_FOOTPRINT_TABLE,
            footprint_table,
            expected_base_commit=request.expected_base_commit,
            tracked=tracked,
        )
        if not tracked:
            raise ProductionWorkflowError("publication candidate changes no tracked authority")

        catalog_relative = PurePosixPath("Activation") / CATALOG_FILENAME
        catalog_path = root.joinpath(*catalog_relative.parts)
        _write_catalog(
            catalog_path,
            rows,
            semantic_digest=semantic_digest,
            revision=revision,
            row_digest=row_digest,
        )
        catalog_sha256 = _digest(catalog_path.read_bytes())
        machine_targets: list[PreparedTarget] = []
        for role in (
            NativeCadRole.ALTIUM_SYMBOL,
            NativeCadRole.ALTIUM_FOOTPRINT,
        ):
            machine_artifact = PurePosixPath(*profile_paths[role].parts[2:])
            data = stage.evidence_store.object_bytes(native[role][0])
            _write_exact(root.joinpath(*machine_artifact.parts), data)
            machine_targets.append(PreparedTarget(machine_artifact.as_posix(), _digest(data)))
        machine_relative = PurePosixPath("Stockroom.DbLib")
        dblib_bytes = render_dblib(
            CATALOG_TABLE,
            CATALOG_FILENAME,
            db_path=str(self.live_catalog_path.resolve()),
        ).encode("utf-8")
        _write_exact(root.joinpath(*machine_relative.parts), dblib_bytes)
        machine_targets.append(PreparedTarget(machine_relative.as_posix(), _digest(dblib_bytes)))
        machine_local = tuple(
            sorted(machine_targets, key=lambda target: target.target_path.casefold())
        )
        return PreparedPublicationManifest(
            publication_id=publication_id,
            component_id=identity.component_id,
            staging_root=root,
            tracked_files=tuple(sorted(tracked, key=lambda target: target.target_path.casefold())),
            machine_local_files=machine_local,
            catalog_staged_path=catalog_relative.as_posix(),
            catalog_sha256=catalog_sha256,
            catalog_revision=revision,
            catalog_semantic_digest=semantic_digest,
            commit_message=(
                f"Complete {stage.identity.authoritative_manufacturer_key} "
                f"{stage.identity.mpn_canonical}"
            ),
        )


def _registration(
    adapter: ExecutableProviderAdapter,
    *,
    key: str,
    version: str,
    operations: tuple[ProviderOperation, ...],
    max_concurrency: int,
) -> ProviderRegistration:
    return ProviderRegistration(
        ProviderDeclaration(
            key=key,
            adapter_version=version,
            operations=operations,
            max_concurrency=max_concurrency,
        ),
        adapter,
    )


def build_production_provider_components(
    context: ProductionApplicationContext,
    *,
    evidence_store: EvidenceStore,
    staging_root: Path,
) -> tuple[
    ProviderPlanner,
    ProviderExecutionRuntime,
    tuple[ProviderPolicyInput, ...],
    StockroomAcquisitionProviderAdapter,
]:
    """Compose a complete executable ordinary-part provider policy."""

    record_adapter = CanonicalRecordProviderAdapter(
        context.profile.library.parts_dir,
        evidence_store,
    )
    datasheet_adapter = ManufacturerDatasheetProviderAdapter(
        context.profile.root,
        context.profile.library.parts_dir,
        evidence_store,
        staging_root / "Datasheets",
    )
    acquisition_adapter = StockroomAcquisitionProviderAdapter(
        context,
        evidence_store,
        staging_root / "Acquisition",
    )
    registrations = [
        _registration(
            record_adapter,
            key=_RECORD_PROVIDER,
            version=_RECORD_ADAPTER_VERSION,
            operations=(METADATA_OPERATION,),
            max_concurrency=8,
        ),
        _registration(
            datasheet_adapter,
            key=_DATASHEET_PROVIDER,
            version=_DATASHEET_ADAPTER_VERSION,
            operations=(DATASHEET_OPERATION,),
            max_concurrency=4,
        ),
        _registration(
            acquisition_adapter,
            key=_ACQUISITION_PROVIDER,
            version=_ACQUISITION_ADAPTER_VERSION,
            operations=(KICAD_CAD_OPERATION, ALTIUM_CAD_OPERATION),
            max_concurrency=1,
        ),
        *build_configured_distributor_metadata_registrations(
            context.config,
            evidence_store,
        ),
    ]
    keys = [registration.declaration.key for registration in registrations]
    if len(set(keys)) != len(keys):
        raise ProductionWorkflowError("production provider registry contains duplicate keys")
    policies: list[ProviderPolicyInput] = []
    for registration in registrations:
        for operation in registration.declaration.operations:
            built_in = registration.declaration.key in {
                _RECORD_PROVIDER,
                _DATASHEET_PROVIDER,
                _ACQUISITION_PROVIDER,
            }
            policies.append(
                ProviderPolicyInput(
                    provider_key=registration.declaration.key,
                    operation=operation,
                    trust=(TrustDecision.PRIMARY if built_in else TrustDecision.SECONDARY),
                    license=LicenseDecision.ALLOWED,
                    authentication=(
                        AuthenticationState.NOT_REQUIRED
                        if built_in
                        else AuthenticationState.AVAILABLE
                    ),
                    health=ProviderHealth.HEALTHY,
                    priority=0 if built_in else 10,
                )
            )
    coverage = {
        operation
        for registration in registrations
        for operation in registration.declaration.operations
    }
    required = {
        METADATA_OPERATION,
        DATASHEET_OPERATION,
        KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION,
    }
    if coverage != required:
        missing = sorted(
            (operation.label for operation in required - coverage),
        )
        extra = sorted(
            (operation.label for operation in coverage - required),
        )
        raise ProductionWorkflowError(
            f"production provider coverage differs; missing={missing!r}, extra={extra!r}"
        )
    planner = ProviderPlanner(tuple(registrations))
    policy_inputs = tuple(policies)
    # Validate complete policy coverage now rather than on the first submitted part.
    planner.policy_semantic_digest(policy_inputs)
    runtime = ProviderExecutionRuntime(
        planner,
        evidence_verifier=evidence_store,
    )
    return planner, runtime, policy_inputs, acquisition_adapter


def build_production_workflow_registry_for_context(
    context: ProductionApplicationContext,
    workflow_store: WorkflowStore,
) -> ProductionWorkflowRegistry:
    """Build the packaged production registry around the lifecycle-owned store."""

    if not isinstance(context.repo, GitRepo):
        raise TypeError("production context requires GitRepo")
    if not isinstance(context.profile, Profile):
        raise TypeError("production context requires Profile")
    if not isinstance(context.config, MachineConfig):
        raise TypeError("production context requires MachineConfig")
    if not isinstance(context.cli, KiCadCli):
        raise TypeError("production context requires KiCadCli")
    if not isinstance(workflow_store, WorkflowStore):
        raise TypeError("production workflow requires the lifecycle WorkflowStore")
    repository = context.repo
    profile = context.profile
    if not repository.is_git_repo() or not repository.head():
        raise ProductionWorkflowError("production workflow requires a committed Git library")
    _relative_repo_path(repository, profile.root, "active profile")
    _relative_repo_path(repository, profile.library.parts_dir, "active parts directory")

    key = hashlib.sha256(
        (
            str(repository.root.resolve()).casefold()
            + "\0"
            + str(profile.root.resolve()).casefold()
        ).encode("utf-8")
    ).hexdigest()
    state_root = capture_state_root().parent / "Production Workflow" / key
    staging_root = (state_root / "Staging").absolute()
    evidence_store = EvidenceStore((capture_state_root() / "Evidence").absolute())
    activation_root = (state_root / "Activation").absolute()
    live_catalog_path = activation_root / CATALOG_FILENAME
    machine_local_root = (state_root / "Altium").absolute()
    try:
        state_root.resolve(strict=False).relative_to(repository.root.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ProductionWorkflowError(
            "production runtime state cannot be inside the library repository"
        )
    for directory in (
        staging_root,
        live_catalog_path.parent,
        machine_local_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        if directory.is_symlink():
            raise ProductionWorkflowError("production state directories cannot be links")

    planner, provider_runtime, policies, acquisition_adapter = build_production_provider_components(
        context,
        evidence_store=evidence_store,
        staging_root=staging_root,
    )
    publisher = ScopedComponentPublisher(
        workflow_store,
        repository,
        live_catalog_path=live_catalog_path,
        machine_local_root=machine_local_root,
    )
    publication_adapter = ExactNativePublicationAdapter(
        repository=repository,
        profile=profile,
        evidence_store=evidence_store,
        live_catalog_path=live_catalog_path,
        machine_local_root=machine_local_root,
    )
    semantic_adapters: Mapping[StageName, ProductionSemanticAdapter] = {
        stage: ExactRecordSemanticAdapter(stage) for stage in PRODUCTION_SEMANTIC_STAGES
    }
    return build_production_workflow_handlers(
        repository=repository,
        library_root=profile.root,
        parts_dir=profile.library.parts_dir,
        staging_root=staging_root,
        evidence_store=evidence_store,
        planner=planner,
        provider_runtime=provider_runtime,
        policy_inputs=policies,
        semantic_adapters=semantic_adapters,
        publication_adapter=publication_adapter,
        publisher=publisher,
        provider_stage_scope=acquisition_adapter.capture_scope,
    )


__all__ = [
    "CanonicalRecordProviderAdapter",
    "ExactNativePublicationAdapter",
    "ExactRecordSemanticAdapter",
    "ManufacturerDatasheetProviderAdapter",
    "ProductionApplicationContext",
    "StockroomAcquisitionProviderAdapter",
    "build_production_provider_components",
    "build_production_workflow_registry_for_context",
]
