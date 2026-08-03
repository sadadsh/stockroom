"""Fail-closed production handlers for the complete Stockroom workflow graph.

The existing workflow kernel deliberately knows nothing about ``PartRecord``,
provider transports, CAD files, or Git.  This module is the production
composition boundary:

* intake is bound to one canonical on-disk ``PartRecord`` by exact part ID,
  manufacturer, and MPN;
* provider handlers may add immutable evidence, but cannot complete on an
  unverified digest;
* reconciliation/definition/template adapters write only to an isolated
  staging root and must return content-addressed evidence;
* native KiCad and Altium files are re-read and cross-verified by Stockroom,
  rather than trusted because files happen to exist;
* the catalog adapter prepares an immutable publication manifest outside the
  repository; the publish stage only proposes that manifest;
* the existing :class:`ScopedComponentPublisher` remains the sole live-library,
  Git, catalog, and machine-local mutation boundary.

No fixture or synthetic adapter is imported here.  Provider availability is
exactly the registrations and policies supplied by the application.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol, TypeAlias, cast

from stockroom.cad_variants import (
    ResolvedCadVariant,
    list_cad_variants,
    resolve_cad_variant,
    same_cad_evidence_set,
)
from stockroom.capture.cad_composition import (
    cross_eda_report_is_proved,
)
from stockroom.capture.cross_eda import (
    read_altium_footprint,
    read_altium_symbol,
    verify_cross_eda_component,
    verify_kicad_component,
)
from stockroom.capture.identity import same_manufacturer, same_mpn
from stockroom.capture.verified_pair import resolve_verified_pair
from stockroom.evidence import EvidenceStore
from stockroom.model.part import PartRecord
from stockroom.model.part_id import is_valid_part_id, part_id_matches
from stockroom.planning.provider_policy import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    ExactPartIdentity,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyInput,
)
from stockroom.planning.provider_runtime import ProviderExecutionRuntime
from stockroom.publish import (
    PreparedPublicationManifest,
    PreparedTarget,
    ScopedComponentPublisher,
)
from stockroom.vcs import GitRepo
from stockroom.workflow import (
    CompletionOutcome,
    ComponentPublicationReceipt,
    DecisionKind,
    DecisionOutcome,
    ExactIdentityOutcome,
    PermanentFailureOutcome,
    PublicationLease,
    PublicationProposalOutcome,
    PublicationState,
    RetryOutcome,
    StageContext,
    StageHandler,
    StageHandlerRegistry,
    StageName,
    StageOutcome,
)
from stockroom.workflow.identifiers import (
    authoritative_text,
    derive_component_identity,
    derive_publication_identity,
    digest_text,
    parse_sha256,
)
from stockroom.workflow.model import canonical_json

from .provider_workflow import (
    PROVIDER_WORKFLOW_STAGES,
    ProviderRetryBounds,
    build_provider_stage_handlers,
)

JsonObject: TypeAlias = dict[str, object]
ProviderStageScope: TypeAlias = Callable[
    [StageContext, ExactPartIdentity],
    AbstractContextManager[None],
]
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_TECHNICAL_KEY = re.compile(r"[a-z][a-z0-9._-]{1,127}\Z", re.ASCII)
_IDENTITY_RULE_REVISION = "production-part-record-exact-v1"
_IDENTITY_REGISTRY_REVISION = "part-record-v4"
_SCHEMA_VERSION = 1

PRODUCTION_SEMANTIC_STAGES = (
    StageName.RECONCILE,
    StageName.CANONICAL_DEFINITION,
    StageName.TEMPLATE_GENERATION,
)

_PROVIDER_OPERATION_BY_LABEL: Mapping[str, ProviderOperation] = MappingProxyType(
    {
        METADATA_OPERATION.label: METADATA_OPERATION,
        DATASHEET_OPERATION.label: DATASHEET_OPERATION,
        KICAD_CAD_OPERATION.label: KICAD_CAD_OPERATION,
        ALTIUM_CAD_OPERATION.label: ALTIUM_CAD_OPERATION,
    }
)

_FORBIDDEN_PRODUCTION_TEXT = (
    "qualified-fixture://",
    "stockroom.synthetic",
    "stockroom.scale-simulation",
)


class ProductionWorkflowError(RuntimeError):
    """Production composition or immutable stage evidence is invalid."""


class ProductionStopKind(StrEnum):
    RETRY = "retry"
    DECISION = "decision"
    FAILURE = "failure"


class NativeCadRole(StrEnum):
    KICAD_SYMBOL = "kicad_symbol"
    KICAD_FOOTPRINT = "kicad_footprint"
    STEP_MODEL = "step_model"
    ALTIUM_SYMBOL = "altium_symbol"
    ALTIUM_FOOTPRINT = "altium_footprint"


_NATIVE_ROLE_ORDER = tuple(NativeCadRole)
_NATIVE_ROLE_SUFFIXES: Mapping[NativeCadRole, frozenset[str]] = MappingProxyType(
    {
        NativeCadRole.KICAD_SYMBOL: frozenset({".kicad_sym"}),
        NativeCadRole.KICAD_FOOTPRINT: frozenset({".kicad_mod"}),
        NativeCadRole.STEP_MODEL: frozenset({".step", ".stp"}),
        NativeCadRole.ALTIUM_SYMBOL: frozenset({".schlib"}),
        NativeCadRole.ALTIUM_FOOTPRINT: frozenset({".pcblib"}),
    }
)


@dataclass(frozen=True, slots=True)
class ProductionRetryPolicy:
    default_delay_seconds: float = 30.0
    minimum_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 3_600.0
    maximum_attempts: int = 5

    def __post_init__(self) -> None:
        delays = (
            self.default_delay_seconds,
            self.minimum_delay_seconds,
            self.maximum_delay_seconds,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
            for value in delays
        ):
            raise ProductionWorkflowError("retry delays must be positive finite numbers")
        if not (
            self.minimum_delay_seconds <= self.default_delay_seconds <= self.maximum_delay_seconds
        ):
            raise ProductionWorkflowError("default retry delay must lie inside its bounds")
        if type(self.maximum_attempts) is not int or not 1 <= self.maximum_attempts <= 100:
            raise ProductionWorkflowError("maximum_attempts must be between 1 and 100")

    def clamp(self, requested: float | None) -> float:
        value = self.default_delay_seconds if requested is None else requested
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ProductionWorkflowError("retry delay must be a positive finite number")
        return min(
            float(self.maximum_delay_seconds),
            max(float(self.minimum_delay_seconds), float(value)),
        )


@dataclass(frozen=True, slots=True)
class ProductionStageStop:
    disposition: ProductionStopKind
    code: str
    message: str
    evidence_digests: tuple[str, ...] = ()
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ProductionStageCompletion:
    document: Mapping[str, object]
    evidence_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductionStageRequest:
    context: StageContext
    identity: ExactPartIdentity
    record: PartRecord
    record_digest: str
    workspace: Path
    evidence_store: EvidenceStore


class ProductionSemanticAdapter(Protocol):
    @property
    def adapter_key(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionStageCompletion | ProductionStageStop: ...


@dataclass(frozen=True, slots=True)
class NativeCadArtifact:
    role: NativeCadRole
    object_digest: str
    suggested_name: str


@dataclass(frozen=True, slots=True)
class ProductionCadBundle:
    artifacts: tuple[
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
    ]
    evidence_digests: tuple[str, ...]
    selection_document: Mapping[str, object]


class ProductionCadBundleAdapter(Protocol):
    @property
    def adapter_key(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionCadBundle | ProductionStageStop: ...


@dataclass(frozen=True, slots=True)
class ProductionPublicationCandidate:
    document: Mapping[str, object]
    evidence_digests: tuple[str, ...]
    expected_head_publication_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProductionPublicationRequest:
    stage: ProductionStageRequest
    expected_base_commit: str


class ProductionPublicationAdapter(Protocol):
    @property
    def adapter_key(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    def prepare_candidate(
        self,
        request: ProductionPublicationRequest,
        /,
    ) -> ProductionPublicationCandidate | ProductionStageStop: ...

    def prepare_manifest(
        self,
        request: ProductionPublicationRequest,
        /,
        *,
        candidate_document: Mapping[str, object],
        candidate_digest: str,
        publication_id: str,
    ) -> PreparedPublicationManifest: ...


@dataclass(frozen=True, slots=True)
class _ExactRecord:
    record: PartRecord
    path: Path
    data: bytes
    digest: str
    identity: ExactPartIdentity


@dataclass(frozen=True, slots=True)
class _LiveState:
    head: str
    library_digest: str


@dataclass(frozen=True, slots=True)
class _PublicationDescriptor:
    manifest: PreparedPublicationManifest
    candidate_digest: str
    expected_base_commit: str
    expected_head_publication_id: str | None


def _strict(document: JsonObject) -> JsonObject:
    canonical_json(document)
    return document


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _digest_json(value: object) -> str:
    return _digest_bytes(canonical_json(value).encode("utf-8"))


def _canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _valid_digest(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


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
        raise ProductionWorkflowError(f"{label} is not a non-empty JSON string")
    return value


def _provider_detail_attestation(
    validation: Mapping[str, object],
    identity: ExactPartIdentity,
) -> ExactPartIdentity | None:
    """Recover only the exact provider-page identity preserved in CAD evidence.

    Older provider-native libraries can omit a manufacturer parameter even though the
    browser capture proved the exact manufacturer and MPN on the provider detail page.
    The immutable validation report is the authority for that narrow missing-field
    binding; the evidence manifest and every artifact are still reverified separately.
    """

    if validation.get("valid") is not True:
        return None
    raw_observations = validation.get("identity_observations")
    if not isinstance(raw_observations, Mapping):
        return None
    raw_detail = raw_observations.get("provider_detail_page")
    if not isinstance(raw_detail, Mapping):
        return None
    manufacturer = raw_detail.get("manufacturer")
    mpn = raw_detail.get("mpn")
    if type(manufacturer) is not str or type(mpn) is not str:
        return None
    if not same_manufacturer(
        manufacturer,
        identity.authoritative_manufacturer_key,
    ) or not same_mpn(mpn, identity.mpn_canonical):
        return None
    return ExactPartIdentity(manufacturer, mpn)


def _assert_production_value(value: object, *, label: str) -> None:
    """Reject the known non-production provenance markers recursively."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.casefold() == "fixture_mode" and item is True:
                raise ProductionWorkflowError(f"{label} contains fixture-mode evidence")
            _assert_production_value(item, label=label)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_production_value(item, label=label)
        return
    if isinstance(value, str):
        folded = value.casefold()
        if any(marker in folded for marker in _FORBIDDEN_PRODUCTION_TEXT):
            raise ProductionWorkflowError(f"{label} contains non-production provenance")


def _relative_path(root: Path, path: Path, *, label: str) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProductionWorkflowError(f"{label} escaped its staging root") from exc
    value = relative.as_posix()
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise ProductionWorkflowError(f"{label} is not a portable relative path")
    return value


def _path_under(root: Path, relative_path: str) -> Path:
    parsed = PurePosixPath(relative_path)
    if (
        not relative_path
        or parsed.is_absolute()
        or parsed.as_posix() != relative_path
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ProductionWorkflowError("prepared path is not a canonical relative path")
    path = root.joinpath(*parsed.parts)
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ProductionWorkflowError("prepared path escaped its staging root") from exc
    return path


def _native_artifact_name(role: NativeCadRole, value: object) -> str:
    name = _string(value, f"{role.value} suggested name")
    if (
        len(name) > 255
        or PurePosixPath(name).name != name
        or Path(name).name != name
        or name.endswith((" ", "."))
        or any(character in name for character in '<>:"/\\|?*')
        or Path(name).suffix.casefold() not in _NATIVE_ROLE_SUFFIXES[role]
    ):
        raise ProductionWorkflowError(f"{role.value} suggested name is not a safe native filename")
    return name


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _install_exact(path: Path, data: bytes) -> None:
    if not data:
        raise ProductionWorkflowError("staged files must be non-empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ProductionWorkflowError("staging path cannot traverse a link")
    if path.exists():
        if not path.is_file() or _is_link(path) or path.read_bytes() != data:
            raise ProductionWorkflowError("durable staged path differs from its exact bytes")
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
        raise ProductionWorkflowError("staged file failed exact byte readback")


def _validate_adapter_identity(adapter: object, label: str) -> tuple[str, str]:
    key = getattr(adapter, "adapter_key", None)
    version = getattr(adapter, "adapter_version", None)
    if (
        type(key) is not str
        or _TECHNICAL_KEY.fullmatch(key) is None
        or type(version) is not str
        or not version
        or version != version.strip()
        or len(version) > 128
    ):
        raise ProductionWorkflowError(f"{label} has no canonical adapter identity")
    _assert_production_value((key, version), label=label)
    return key, version


class ExactEvidenceCadBundleAdapter:
    """Select one strict dual-EDA pair from immutable exact-identity evidence."""

    adapter_key = "exact-evidence-cad-bundle"
    adapter_version = "1.0.0"

    def execute(
        self,
        request: ProductionStageRequest,
        /,
    ) -> ProductionCadBundle | ProductionStageStop:
        return self.select(
            evidence_store=request.evidence_store,
            identity=request.identity,
            workspace=request.workspace,
        )

    def select(
        self,
        *,
        evidence_store: EvidenceStore,
        identity: ExactPartIdentity,
        workspace: Path,
    ) -> ProductionCadBundle | ProductionStageStop:
        """Select from exact retained evidence without requiring a workflow context."""

        store = evidence_store
        workspace.mkdir(parents=True, exist_ok=True)
        altium_variants = list_cad_variants(
            store,
            identity=identity,
            tool="altium",
        )
        kicad_by_manifest = {
            descriptor.manifest_digest: descriptor
            for descriptor in list_cad_variants(
                store,
                identity=identity,
                tool="kicad",
            )
        }
        attempts: list[JsonObject] = []
        for descriptor in altium_variants:
            try:
                kicad_descriptor = kicad_by_manifest.get(descriptor.manifest_digest)
                if kicad_descriptor is None or not same_cad_evidence_set(
                    kicad_descriptor,
                    descriptor,
                ):
                    raise ProductionWorkflowError(
                        "KiCad and Altium evidence did not come from one provider download set"
                    )
                verified_pair = resolve_verified_pair(
                    store,
                    identity=identity,
                    manifest_digest=descriptor.manifest_digest,
                )
                kicad = verified_pair.kicad
                altium = verified_pair.altium
                validation = verified_pair.validation
                attestation = _provider_detail_attestation(validation, identity)
                with tempfile.TemporaryDirectory(
                    prefix=".Altium-Candidate-",
                    dir=workspace,
                ) as temporary:
                    root = Path(temporary)
                    kicad_artifacts = {
                        artifact.asset_kind: artifact for artifact in kicad.descriptor.artifacts
                    }
                    altium_artifacts = {
                        artifact.asset_kind: artifact for artifact in altium.descriptor.artifacts
                    }
                    symbol = root / _native_artifact_name(
                        NativeCadRole.KICAD_SYMBOL,
                        kicad_artifacts["symbol"].suggested_name,
                    )
                    footprint = root / _native_artifact_name(
                        NativeCadRole.KICAD_FOOTPRINT,
                        kicad_artifacts["footprint"].suggested_name,
                    )
                    model = root / _native_artifact_name(
                        NativeCadRole.STEP_MODEL,
                        kicad_artifacts["model"].suggested_name,
                    )
                    schlib = root / _native_artifact_name(
                        NativeCadRole.ALTIUM_SYMBOL,
                        altium_artifacts["symbol"].suggested_name,
                    )
                    pcblib = root / _native_artifact_name(
                        NativeCadRole.ALTIUM_FOOTPRINT,
                        altium_artifacts["footprint"].suggested_name,
                    )
                    symbol.write_bytes(kicad.data["symbol"])
                    footprint.write_bytes(kicad.data["footprint"])
                    model.write_bytes(kicad.data["model"])
                    schlib.write_bytes(altium.data["symbol"])
                    pcblib.write_bytes(altium.data["footprint"])
                    verification = verify_cross_eda_component(
                        identity=identity,
                        kicad_symbol=symbol,
                        kicad_footprint=footprint,
                        step_model=model,
                        altium_sources=(schlib, pcblib),
                        altium_identity_attestation=attestation,
                        altium_footprint_entry=verified_pair.altium_footprint_entry,
                    )
                if not cross_eda_report_is_proved(verification):
                    raise ProductionWorkflowError("strict cross-EDA verification was not proved")
                selection_document = _strict(
                    {
                        "altium_manifest_digest": descriptor.manifest_digest,
                        "cross_eda_verification": verification,
                        "evidence_provider": descriptor.provider,
                        "evidence_set_manifest_digest": descriptor.manifest_digest,
                        "kicad_manifest_digest": descriptor.manifest_digest,
                        "schema": "stockroom.production-cad-selection/1",
                    }
                )
                selection_digest = store.install_bytes(_canonical_bytes(selection_document))
                artifacts = self._artifacts(kicad, altium)
                return ProductionCadBundle(
                    artifacts=artifacts,
                    evidence_digests=(
                        descriptor.manifest_digest,
                        selection_digest,
                    ),
                    selection_document=selection_document,
                )
            except Exception as exc:
                attempts.append(
                    {
                        "altium_manifest_digest": descriptor.manifest_digest,
                        "failure": type(exc).__name__,
                        "provider": descriptor.provider,
                    }
                )
        return ProductionStageStop(
            ProductionStopKind.DECISION,
            "exact_dual_eda_evidence_unavailable",
            (
                "No retained exact-identity KiCad, Altium, and STEP set from one provider "
                "download passed native cross-verification."
            ),
            evidence_digests=(),
        )

    @staticmethod
    def _artifact(
        resolved: ResolvedCadVariant,
        role: NativeCadRole,
        asset_kind: str,
    ) -> NativeCadArtifact:
        descriptor = next(
            artifact
            for artifact in resolved.descriptor.artifacts
            if artifact.asset_kind == asset_kind
        )
        return NativeCadArtifact(
            role,
            descriptor.artifact_digest,
            descriptor.suggested_name,
        )

    @classmethod
    def _artifacts(
        cls,
        kicad: ResolvedCadVariant,
        altium: ResolvedCadVariant,
    ) -> tuple[
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
        NativeCadArtifact,
    ]:
        return (
            cls._artifact(
                kicad,
                NativeCadRole.KICAD_SYMBOL,
                "symbol",
            ),
            cls._artifact(
                kicad,
                NativeCadRole.KICAD_FOOTPRINT,
                "footprint",
            ),
            cls._artifact(
                kicad,
                NativeCadRole.STEP_MODEL,
                "model",
            ),
            cls._artifact(
                altium,
                NativeCadRole.ALTIUM_SYMBOL,
                "symbol",
            ),
            cls._artifact(
                altium,
                NativeCadRole.ALTIUM_FOOTPRINT,
                "footprint",
            ),
        )


class ProductionWorkflowRegistry(Mapping[StageName, StageHandler]):
    """Immutable complete handler registry plus the only publication executor."""

    def __init__(
        self,
        *,
        repository: GitRepo,
        library_root: Path,
        parts_dir: Path,
        staging_root: Path,
        evidence_store: EvidenceStore,
        planner: ProviderPlanner,
        provider_runtime: ProviderExecutionRuntime,
        policy_inputs: tuple[ProviderPolicyInput, ...],
        semantic_adapters: Mapping[StageName, ProductionSemanticAdapter],
        publication_adapter: ProductionPublicationAdapter,
        publisher: ScopedComponentPublisher,
        cad_bundle_adapter: ProductionCadBundleAdapter | None = None,
        provider_stage_scope: ProviderStageScope | None = None,
        clock: Callable[[], float] = time.time,
        retry_policy: ProductionRetryPolicy = ProductionRetryPolicy(),
        provider_retry_bounds: ProviderRetryBounds = ProviderRetryBounds(),
    ):
        if not isinstance(repository, GitRepo) or not repository.is_git_repo():
            raise ProductionWorkflowError("repository must be an initialized Git repository")
        if not repository.head():
            raise ProductionWorkflowError("repository must have an exact base commit")
        if not isinstance(evidence_store, EvidenceStore):
            raise TypeError("evidence_store must be an EvidenceStore")
        if not isinstance(publisher, ScopedComponentPublisher):
            raise TypeError("publisher must be a ScopedComponentPublisher")
        if publisher.repository.root.resolve() != repository.root.resolve():
            raise ProductionWorkflowError("publisher and handlers must share one repository")
        if type(retry_policy) is not ProductionRetryPolicy:
            raise TypeError("retry_policy must be a ProductionRetryPolicy")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if provider_stage_scope is not None and not callable(provider_stage_scope):
            raise TypeError("provider_stage_scope must be callable")

        repo_root = repository.root.resolve(strict=True)
        library = Path(library_root)
        parts = Path(parts_dir)
        staging = Path(staging_root)
        if not library.is_absolute() or not parts.is_absolute() or not staging.is_absolute():
            raise ProductionWorkflowError("production roots must be absolute paths")
        library = library.resolve(strict=True)
        parts = parts.resolve(strict=True)
        staging.mkdir(parents=True, exist_ok=True)
        staging = staging.resolve(strict=True)
        if (
            not library.is_dir()
            or _is_link(library)
            or not parts.is_dir()
            or _is_link(parts)
            or not parts.is_relative_to(library)
        ):
            raise ProductionWorkflowError(
                "parts_dir must be a non-linked directory in library_root"
            )
        if not library.is_relative_to(repo_root):
            raise ProductionWorkflowError("library_root must be inside the publication repository")
        if _is_link(staging) or staging.is_relative_to(repo_root):
            raise ProductionWorkflowError("staging_root must be non-linked and outside repository")
        evidence_root = evidence_store.root.resolve(strict=True)
        if evidence_root.is_relative_to(repo_root) or staging.is_relative_to(evidence_root):
            raise ProductionWorkflowError(
                "evidence and workflow staging roots must be isolated from the repository"
            )

        supplied_semantic = dict(semantic_adapters)
        if set(supplied_semantic) != set(PRODUCTION_SEMANTIC_STAGES):
            missing = sorted(
                stage.value for stage in set(PRODUCTION_SEMANTIC_STAGES) - set(supplied_semantic)
            )
            extra = sorted(
                stage.value for stage in set(supplied_semantic) - set(PRODUCTION_SEMANTIC_STAGES)
            )
            raise ProductionWorkflowError(
                f"semantic adapter coverage is incomplete (missing={missing}, extra={extra})"
            )
        for stage, adapter in supplied_semantic.items():
            if not callable(getattr(adapter, "execute", None)):
                raise TypeError(f"semantic adapter for {stage.value} is not executable")
            _validate_adapter_identity(adapter, f"{stage.value} adapter")
        native_adapter = cad_bundle_adapter or ExactEvidenceCadBundleAdapter()
        if not callable(getattr(native_adapter, "execute", None)):
            raise TypeError("cad_bundle_adapter is not executable")
        _validate_adapter_identity(native_adapter, "CAD bundle adapter")
        if not callable(getattr(publication_adapter, "prepare_candidate", None)) or not callable(
            getattr(publication_adapter, "prepare_manifest", None)
        ):
            raise TypeError("publication_adapter does not implement both preparation steps")
        _validate_adapter_identity(publication_adapter, "publication adapter")

        self.repository = repository
        self.repo_root = repo_root
        self.library_root = library
        self.parts_dir = parts
        self.staging_root = staging
        self.evidence_store = evidence_store
        self.publisher = publisher
        self.semantic_adapters = MappingProxyType(supplied_semantic)
        self.cad_bundle_adapter = native_adapter
        self.publication_adapter = publication_adapter
        self.provider_stage_scope = provider_stage_scope
        self.clock = clock
        self.retry_policy = retry_policy

        provider_handlers = build_provider_stage_handlers(
            exact_identity=self._provider_identity,
            planner=planner,
            runtime=provider_runtime,
            policy_inputs=policy_inputs,
            clock=clock,
            retry_bounds=provider_retry_bounds,
        )
        if set(provider_handlers) != set(PROVIDER_WORKFLOW_STAGES):
            raise ProductionWorkflowError("provider handler factory returned incomplete coverage")

        handlers: dict[StageName, StageHandler] = {
            StageName.IDENTITY_DEDUPE: self._identity,
            **{
                stage: self._wrap_provider(stage, provider_handlers[stage])
                for stage in PROVIDER_WORKFLOW_STAGES
            },
            StageName.EXISTING_EVIDENCE: self._existing_evidence,
            **{
                stage: self._semantic_handler(stage, supplied_semantic[stage])
                for stage in PRODUCTION_SEMANTIC_STAGES
            },
            StageName.NATIVE_CONVERSION_ACQUISITION: self._native_conversion,
            StageName.KICAD_BUILD_READBACK: self._kicad_readback,
            StageName.ALTIUM_BUILD_READBACK: self._altium_readback,
            StageName.CROSS_EDA_VERIFICATION: self._cross_eda_verification,
            StageName.CATALOG_LINK_GENERATION: self._catalog_link_generation,
            StageName.PUBLISH: self._publish_proposal,
        }
        expected = set(StageName)
        if set(handlers) != expected:
            missing = sorted(stage.value for stage in expected - set(handlers))
            extra = sorted(stage.value for stage in set(handlers) - expected)
            raise ProductionWorkflowError(
                f"production handler registry is incomplete (missing={missing}, extra={extra})"
            )
        if any(not callable(handler) for handler in handlers.values()):
            raise ProductionWorkflowError("production handler registry contains a non-callable")
        self._handlers: StageHandlerRegistry = MappingProxyType(handlers)

    @property
    def handlers(self) -> StageHandlerRegistry:
        return self._handlers

    def __getitem__(self, key: StageName) -> StageHandler:
        return self._handlers[StageName(key)]

    def __iter__(self) -> Iterator[StageName]:
        return iter(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)

    def execute_publication(
        self,
        lease: PublicationLease,
        *,
        now: float | None = None,
    ) -> ComponentPublicationReceipt:
        """Run or recover one durable operation through the existing atomic publisher."""

        operation = self.publisher.store.get_publication_operation(lease.publication_id)
        descriptor = self._load_publication_descriptor(operation.manifest_digest)
        manifest = descriptor.manifest
        if (
            manifest.publication_id != lease.publication_id
            or descriptor.expected_base_commit != operation.expected_base_commit
            or descriptor.candidate_digest != operation.candidate_digest
        ):
            raise ProductionWorkflowError(
                "durable publication operation differs from its prepared descriptor"
            )
        if lease.state is PublicationState.PREPARING:
            return self.publisher.publish(manifest, lease, now=now)
        return self.publisher.reconcile(manifest, lease, now=now)

    def _failure(
        self,
        stage: StageName,
        kind: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> PermanentFailureOutcome:
        document: JsonObject = {
            "kind": kind,
            "schema_version": _SCHEMA_VERSION,
            "stage": stage.value,
        }
        if details:
            document["details"] = dict(details)
        return PermanentFailureOutcome(_strict(document))

    def _item_key(self, context: StageContext) -> str:
        return hashlib.sha256(context.item.id.encode("utf-8")).hexdigest()

    def _item_root(self, context: StageContext) -> Path:
        root = self.staging_root / "Items" / self._item_key(context)
        root.mkdir(parents=True, exist_ok=True)
        if _is_link(root):
            raise ProductionWorkflowError("item staging root cannot be linked")
        return root

    def _workspace(self, context: StageContext) -> Path:
        root = (
            self._item_root(context)
            / "Stages"
            / context.stage.name.value
            / f"Attempt-{context.stage.attempt_count}"
        )
        root.mkdir(parents=True, exist_ok=True)
        if _is_link(root):
            raise ProductionWorkflowError("stage workspace cannot be linked")
        return root

    def _identity_pointer_path(self, context: StageContext) -> Path:
        return self.staging_root / "Identity Snapshots" / f"{self._item_key(context)}.json"

    def _load_exact_record(
        self,
        context: StageContext,
        *,
        require_snapshot: bool,
    ) -> _ExactRecord:
        payload = _mapping(context.item.payload, "workflow item payload")
        part_id = _string(payload.get("part_id"), "payload part_id")
        if not is_valid_part_id(part_id):
            raise ProductionWorkflowError("payload part_id is not canonical")
        path = self.parts_dir / f"{part_id}.json"
        if not path.is_file() or _is_link(path) or path.parent.resolve() != self.parts_dir:
            raise ProductionWorkflowError("exact PartRecord file is missing or linked")
        data = path.read_bytes()
        if not data or data.startswith(b"\xef\xbb\xbf"):
            raise ProductionWorkflowError("PartRecord bytes are empty or carry a UTF-8 BOM")
        try:
            text = data.decode("utf-8")
            record = PartRecord.loads(text)
        except Exception as exc:
            raise ProductionWorkflowError("PartRecord cannot be parsed exactly") from exc
        canonical_lf = record.dumps().encode("utf-8")
        canonical_crlf = canonical_lf.replace(b"\n", b"\r\n")
        if data not in (canonical_lf, canonical_crlf):
            raise ProductionWorkflowError("PartRecord file is not canonical current-schema JSON")
        if record.is_future_schema():
            raise ProductionWorkflowError("future-schema PartRecord cannot enter this workflow")
        if (
            record.id != part_id
            or not part_id_matches(part_id, record.mpn)
            or record.manufacturer != context.item.manufacturer
            or record.mpn != context.item.mpn
            or record.manufacturer != context.item.manufacturer_key
            or record.mpn != context.item.mpn_key
        ):
            raise ProductionWorkflowError(
                "submitted part ID, manufacturer, MPN, and PartRecord do not match exactly"
            )
        authoritative_text(record.manufacturer, "PartRecord manufacturer")
        authoritative_text(record.mpn, "PartRecord MPN")
        digest = _digest_bytes(data)
        exact = _ExactRecord(
            record=record,
            path=path,
            data=data,
            digest=digest,
            identity=ExactPartIdentity(record.manufacturer, record.mpn),
        )
        if require_snapshot:
            pointer_path = self._identity_pointer_path(context)
            if not pointer_path.is_file() or _is_link(pointer_path):
                raise ProductionWorkflowError("identity snapshot pointer is missing or linked")
            pointer_bytes = pointer_path.read_bytes()
            try:
                pointer = json.loads(pointer_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProductionWorkflowError("identity snapshot pointer is invalid") from exc
            if (
                type(pointer) is not dict
                or _canonical_bytes(pointer) != pointer_bytes
                or pointer
                != {
                    "item_id": context.item.id,
                    "part_id": part_id,
                    "record_digest": digest,
                    "schema": "stockroom.production-identity-snapshot/1",
                }
            ):
                raise ProductionWorkflowError("PartRecord bytes drifted after identity resolution")
            if self.evidence_store.object_bytes(digest) != data:
                raise ProductionWorkflowError("identity snapshot CAS bytes differ")
        return exact

    def _library_digest(self) -> str:
        digest = hashlib.sha256(b"stockroom.production-library-state.v1\0")
        seen: set[str] = set()
        for path in sorted(self.library_root.rglob("*"), key=lambda item: str(item).casefold()):
            relative = path.relative_to(self.library_root).as_posix()
            folded = relative.casefold()
            if folded in seen:
                raise ProductionWorkflowError("library contains a Windows path collision")
            seen.add(folded)
            if _is_link(path):
                raise ProductionWorkflowError("live library cannot contain links or junctions")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ProductionWorkflowError("live library contains an unsupported path type")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        return digest_text(digest.digest())

    def _live_state(self) -> _LiveState:
        return _LiveState(
            head=self.repository.head(),
            library_digest=self._library_digest(),
        )

    def _invoke_guarded(
        self,
        stage: StageName,
        context: StageContext,
        operation: Callable[[], object],
    ) -> object | PermanentFailureOutcome:
        try:
            before = self._live_state()
            value = operation()
            after = self._live_state()
        except Exception as exc:
            return self._failure(
                stage,
                "production_adapter_failure",
                details={"exception_type": type(exc).__name__},
            )
        if before != after:
            return self._failure(
                stage,
                "live_library_mutation_before_publish",
                details={
                    "base_changed": before.head != after.head,
                    "library_changed": before.library_digest != after.library_digest,
                },
            )
        try:
            self._load_exact_record(context, require_snapshot=True)
        except Exception as exc:
            return self._failure(
                stage,
                "source_part_record_drift",
                details={"exception_type": type(exc).__name__},
            )
        return value

    def _identity(self, context: StageContext) -> StageOutcome:
        stage = StageName.IDENTITY_DEDUPE
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")
        try:
            before = self._live_state()
            exact = self._load_exact_record(context, require_snapshot=False)
            installed = self.evidence_store.install_bytes(exact.data)
            if installed != exact.digest:
                raise ProductionWorkflowError("PartRecord CAS address differs")
            pointer = _strict(
                {
                    "item_id": context.item.id,
                    "part_id": exact.record.id,
                    "record_digest": exact.digest,
                    "schema": "stockroom.production-identity-snapshot/1",
                }
            )
            _install_exact(self._identity_pointer_path(context), _canonical_bytes(pointer))
            if self._live_state() != before:
                raise ProductionWorkflowError("identity resolution mutated the live library")
            derived = derive_component_identity(
                exact.identity.authoritative_manufacturer_key,
                exact.identity.mpn_canonical,
            )
            return ExactIdentityOutcome(
                authoritative_manufacturer_key=exact.identity.authoritative_manufacturer_key,
                mpn_canonical=exact.identity.mpn_canonical,
                registry_revision=_IDENTITY_REGISTRY_REVISION,
                rule_revision=_IDENTITY_RULE_REVISION,
                evidence=_strict(
                    {
                        "component_id": derived.component_id,
                        "part_id": exact.record.id,
                        "record_digest": exact.digest,
                        "schema": "stockroom.production-exact-identity-evidence/1",
                    }
                ),
            )
        except Exception as exc:
            return self._failure(
                stage,
                "exact_part_record_identity_rejected",
                details={"exception_type": type(exc).__name__},
            )

    def _provider_identity(self, context: StageContext) -> ExactPartIdentity:
        return self._load_exact_record(context, require_snapshot=True).identity

    def _wrap_provider(self, stage: StageName, handler: StageHandler) -> StageHandler:
        def execute(context: StageContext) -> StageOutcome:
            if context.stage.name is not stage:
                return self._failure(stage, "handler_stage_mismatch")

            def invoke() -> StageOutcome:
                if stage is not StageName.CAD_ACQUISITION or self.provider_stage_scope is None:
                    return handler(context)
                identity = self._provider_identity(context)
                with self.provider_stage_scope(context, identity):
                    return handler(context)

            guarded = self._invoke_guarded(stage, context, invoke)
            if isinstance(guarded, PermanentFailureOutcome):
                return guarded
            outcome = cast(StageOutcome, guarded)
            if not isinstance(outcome, CompletionOutcome):
                return outcome
            try:
                self._verify_provider_completion(stage, context, outcome)
            except Exception as exc:
                return self._failure(
                    stage,
                    "provider_completion_evidence_rejected",
                    details={"exception_type": type(exc).__name__},
                )
            return outcome

        return execute

    def _verify_provider_completion(
        self,
        stage: StageName,
        context: StageContext,
        outcome: CompletionOutcome,
    ) -> None:
        document = _mapping(outcome.result, "provider completion")
        if document.get("stage") != stage.value:
            raise ProductionWorkflowError("provider completion names a different stage")
        identity = self._provider_identity(context)
        operations = _sequence(document.get("operations"), "provider operations")
        if not operations:
            raise ProductionWorkflowError("provider completion has no operations")
        for raw_operation in operations:
            operation = _mapping(raw_operation, "provider operation")
            operation_label = _string(operation.get("operation"), "provider operation label")
            selected = _mapping(operation.get("selected"), "selected provider attempt")
            provider_key = _string(selected.get("provider_key"), "selected provider key")
            adapter_version = _string(
                selected.get("adapter_version"),
                "selected adapter version",
            )
            digests = _sequence(selected.get("evidence_digests"), "selected evidence digests")
            if not digests:
                raise ProductionWorkflowError("provider selected no immutable evidence")
            expected_operation = _PROVIDER_OPERATION_BY_LABEL.get(operation_label)
            if expected_operation is None:
                raise ProductionWorkflowError("provider completion names an unknown operation")
            for raw_digest in digests:
                digest = _string(raw_digest, "provider evidence digest")
                self.evidence_store.verify_provider_success(
                    digest,
                    identity=identity,
                    operation=expected_operation,
                    provider_key=provider_key,
                    adapter_version=adapter_version,
                )
                self._verify_evidence_object(digest)

    def _verify_evidence_object(self, digest: str) -> bytes:
        if not _valid_digest(digest):
            raise ProductionWorkflowError("evidence digest is not canonical")
        data = self.evidence_store.object_bytes(digest)
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return data
        if _canonical_bytes(value) == data:
            _assert_production_value(value, label="evidence object")
        return data

    def _existing_evidence(self, context: StageContext) -> StageOutcome:
        stage = StageName.EXISTING_EVIDENCE
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")

        def inspect() -> CompletionOutcome:
            exact = self._load_exact_record(context, require_snapshot=True)
            tools: list[JsonObject] = []
            for tool in ("kicad", "altium"):
                listed = list_cad_variants(
                    self.evidence_store,
                    identity=exact.identity,
                    tool=tool,
                )
                active_pointer = exact.record.cad_variants.selection_for(tool)
                active: JsonObject | None = None
                if active_pointer is not None:
                    resolved = resolve_cad_variant(
                        self.evidence_store,
                        identity=exact.identity,
                        tool=tool,
                        manifest_digest=active_pointer.manifest_digest,
                    )
                    if resolved.pointer != active_pointer:
                        raise ProductionWorkflowError(
                            "active CAD pointer differs from reverified evidence"
                        )
                    report = self.evidence_store.verified_cad_validation_report(
                        active_pointer.manifest_digest,
                        identity=exact.identity,
                    )
                    if report.get("valid") is not True:
                        raise ProductionWorkflowError(
                            "active CAD pointer has no valid readback report"
                        )
                    active = {
                        "manifest_digest": active_pointer.manifest_digest,
                        "provider": active_pointer.provider,
                    }
                tools.append(
                    {
                        "active": active,
                        "tool": tool,
                        "variants": [
                            {
                                "manifest_digest": descriptor.manifest_digest,
                                "provider": descriptor.provider,
                                "source_manifests": list(descriptor.source_manifests),
                            }
                            for descriptor in listed
                        ],
                    }
                )
            document = _strict(
                {
                    "identity": {
                        "authoritative_manufacturer_key": (
                            exact.identity.authoritative_manufacturer_key
                        ),
                        "mpn_canonical": exact.identity.mpn_canonical,
                    },
                    "part_record_digest": exact.digest,
                    "schema": "stockroom.production-existing-evidence/1",
                    "searched_complete_bundle_roles": True,
                    "tools": tools,
                }
            )
            evidence_digest = self.evidence_store.install_bytes(_canonical_bytes(document))
            return CompletionOutcome(
                _strict(
                    {
                        "evidence_digest": evidence_digest,
                        "part_record_digest": exact.digest,
                        "schema": "stockroom.production-stage-result/1",
                        "stage": stage.value,
                    }
                )
            )

        guarded = self._invoke_guarded(stage, context, inspect)
        return cast(StageOutcome, guarded)

    def _request(self, context: StageContext) -> ProductionStageRequest:
        exact = self._load_exact_record(context, require_snapshot=True)
        return ProductionStageRequest(
            context=context,
            identity=exact.identity,
            record=exact.record,
            record_digest=exact.digest,
            workspace=self._workspace(context),
            evidence_store=self.evidence_store,
        )

    def _semantic_handler(
        self,
        stage: StageName,
        adapter: ProductionSemanticAdapter,
    ) -> StageHandler:
        adapter_key, adapter_version = _validate_adapter_identity(
            adapter,
            f"{stage.value} adapter",
        )

        def execute(context: StageContext) -> StageOutcome:
            if context.stage.name is not stage:
                return self._failure(stage, "handler_stage_mismatch")
            guarded = self._invoke_guarded(
                stage,
                context,
                lambda: adapter.execute(self._request(context)),
            )
            if isinstance(guarded, PermanentFailureOutcome):
                return guarded
            if isinstance(guarded, ProductionStageStop):
                return self._stop_outcome(stage, context, guarded)
            if type(guarded) is not ProductionStageCompletion:
                return self._failure(stage, "invalid_production_adapter_result")
            try:
                request = self._request(context)
                document = dict(guarded.document)
                canonical_json(document)
                _assert_production_value(document, label=f"{stage.value} completion")
                evidence = self._verified_digests(
                    guarded.evidence_digests,
                    include=(request.record_digest,),
                )
                document_digest = self.evidence_store.install_bytes(_canonical_bytes(document))
                evidence = tuple(sorted(set((*evidence, document_digest))))
                return CompletionOutcome(
                    _strict(
                        {
                            "adapter": {
                                "key": adapter_key,
                                "version": adapter_version,
                            },
                            "document_digest": document_digest,
                            "evidence_digests": list(evidence),
                            "part_record_digest": request.record_digest,
                            "schema": "stockroom.production-stage-result/1",
                            "stage": stage.value,
                        }
                    )
                )
            except Exception as exc:
                return self._failure(
                    stage,
                    "production_stage_evidence_rejected",
                    details={"exception_type": type(exc).__name__},
                )

        return execute

    def _verified_digests(
        self,
        values: tuple[str, ...],
        *,
        include: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        if type(values) is not tuple or any(not _valid_digest(value) for value in values):
            raise ProductionWorkflowError("adapter evidence must be immutable digest tuples")
        combined = tuple(sorted(set((*values, *include))))
        if not combined:
            raise ProductionWorkflowError("successful stage requires immutable evidence")
        for digest in combined:
            self._verify_evidence_object(digest)
        return combined

    def _stop_outcome(
        self,
        stage: StageName,
        context: StageContext,
        stop: ProductionStageStop,
    ) -> StageOutcome:
        try:
            if (
                type(stop) is not ProductionStageStop
                or not isinstance(stop.disposition, ProductionStopKind)
                or type(stop.code) is not str
                or _TECHNICAL_KEY.fullmatch(stop.code) is None
                or type(stop.message) is not str
                or not stop.message
                or stop.message != stop.message.strip()
            ):
                raise ProductionWorkflowError("stage stop is not canonical")
            exact = self._load_exact_record(context, require_snapshot=True)
            evidence = self._verified_digests(
                stop.evidence_digests,
                include=(exact.digest,),
            )
            document = _strict(
                {
                    "code": stop.code,
                    "evidence_digests": list(evidence),
                    "identity": {
                        "authoritative_manufacturer_key": (
                            exact.identity.authoritative_manufacturer_key
                        ),
                        "mpn_canonical": exact.identity.mpn_canonical,
                    },
                    "kind": f"production_stage_{stop.disposition.value}",
                    "message": stop.message,
                    "schema_version": _SCHEMA_VERSION,
                    "stage": stage.value,
                }
            )
            if stop.disposition is ProductionStopKind.FAILURE:
                return PermanentFailureOutcome(document)
            if stop.disposition is ProductionStopKind.DECISION:
                document["question"] = stop.message
                return DecisionOutcome(DecisionKind.SAFETY, _strict(document))
            if context.stage.attempt_count >= self.retry_policy.maximum_attempts:
                return self._failure(
                    stage,
                    "production_retry_exhausted",
                    details={
                        "attempt_count": context.stage.attempt_count,
                        "code": stop.code,
                    },
                )
            now = float(self.clock())
            if not math.isfinite(now):
                raise ProductionWorkflowError("retry clock is invalid")
            return RetryOutcome(
                document,
                now + self.retry_policy.clamp(stop.retry_after_seconds),
            )
        except Exception as exc:
            return self._failure(
                stage,
                "invalid_production_stage_stop",
                details={"exception_type": type(exc).__name__},
            )

    def _native_conversion(self, context: StageContext) -> StageOutcome:
        stage = StageName.NATIVE_CONVERSION_ACQUISITION
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")
        guarded = self._invoke_guarded(
            stage,
            context,
            lambda: self.cad_bundle_adapter.execute(self._request(context)),
        )
        if isinstance(guarded, PermanentFailureOutcome):
            return guarded
        if isinstance(guarded, ProductionStageStop):
            return self._stop_outcome(stage, context, guarded)
        if type(guarded) is not ProductionCadBundle:
            return self._failure(stage, "invalid_cad_bundle_adapter_result")
        try:
            request = self._request(context)
            if tuple(artifact.role for artifact in guarded.artifacts) != _NATIVE_ROLE_ORDER:
                raise ProductionWorkflowError("native CAD bundle role matrix is incomplete")
            artifacts: list[JsonObject] = []
            artifact_digests: list[str] = []
            materialized_names: set[str] = set()
            for artifact in guarded.artifacts:
                if type(artifact) is not NativeCadArtifact:
                    raise ProductionWorkflowError("native CAD bundle artifact is invalid")
                data = self._verify_evidence_object(artifact.object_digest)
                suggested_name = _native_artifact_name(
                    artifact.role,
                    artifact.suggested_name,
                )
                folded_name = suggested_name.casefold()
                if folded_name in materialized_names:
                    raise ProductionWorkflowError(
                        "native CAD bundle contains a Windows filename collision"
                    )
                materialized_names.add(folded_name)
                path = request.workspace / "Native" / suggested_name
                _install_exact(path, data)
                artifacts.append(
                    {
                        "object_digest": artifact.object_digest,
                        "relative_path": _relative_path(
                            request.workspace,
                            path,
                            label="native CAD artifact",
                        ),
                        "role": artifact.role.value,
                        "size_bytes": len(data),
                        "suggested_name": suggested_name,
                    }
                )
                artifact_digests.append(artifact.object_digest)
            selection = dict(guarded.selection_document)
            canonical_json(selection)
            _assert_production_value(selection, label="CAD selection")
            selection_digest = self.evidence_store.install_bytes(_canonical_bytes(selection))
            evidence = self._verified_digests(
                guarded.evidence_digests,
                include=(
                    request.record_digest,
                    selection_digest,
                    *artifact_digests,
                ),
            )
            return CompletionOutcome(
                _strict(
                    {
                        "adapter": {
                            "key": self.cad_bundle_adapter.adapter_key,
                            "version": self.cad_bundle_adapter.adapter_version,
                        },
                        "artifacts": artifacts,
                        "evidence_digests": list(evidence),
                        "part_record_digest": request.record_digest,
                        "schema": "stockroom.production-native-cad/1",
                        "selection_digest": selection_digest,
                        "stage": stage.value,
                    }
                )
            )
        except Exception as exc:
            return self._failure(
                stage,
                "native_cad_bundle_rejected",
                details={"exception_type": type(exc).__name__},
            )

    def _native_artifacts(
        self,
        context: StageContext,
        workspace: Path,
    ) -> dict[NativeCadRole, Path]:
        raw = _mapping(
            context.prior_results.get(StageName.NATIVE_CONVERSION_ACQUISITION),
            "native CAD dependency",
        )
        if (
            raw.get("schema") != "stockroom.production-native-cad/1"
            or raw.get("stage") != StageName.NATIVE_CONVERSION_ACQUISITION.value
        ):
            raise ProductionWorkflowError("native CAD dependency has an unknown schema")
        result: dict[NativeCadRole, Path] = {}
        materialized_names: set[str] = set()
        for raw_artifact in _sequence(raw.get("artifacts"), "native CAD artifacts"):
            artifact = _mapping(raw_artifact, "native CAD artifact")
            role = NativeCadRole(_string(artifact.get("role"), "native CAD role"))
            digest = _string(artifact.get("object_digest"), "native CAD object digest")
            data = self._verify_evidence_object(digest)
            if artifact.get("size_bytes") != len(data):
                raise ProductionWorkflowError("native CAD artifact size differs")
            suggested_name = _native_artifact_name(
                role,
                artifact.get("suggested_name"),
            )
            relative = _string(
                artifact.get("relative_path"),
                "native CAD artifact relative path",
            )
            if PurePosixPath(relative).name != suggested_name:
                raise ProductionWorkflowError(
                    "native CAD artifact path differs from its suggested name"
                )
            folded_name = suggested_name.casefold()
            if folded_name in materialized_names:
                raise ProductionWorkflowError(
                    "native CAD dependency contains a Windows filename collision"
                )
            materialized_names.add(folded_name)
            destination = workspace / "Readback" / suggested_name
            _install_exact(destination, data)
            result[role] = destination
        if tuple(result) != _NATIVE_ROLE_ORDER:
            raise ProductionWorkflowError("native CAD dependency role matrix is incomplete")
        return result

    def _strict_cross_report(
        self,
        context: StageContext,
        request: ProductionStageRequest,
        paths: Mapping[NativeCadRole, Path],
    ) -> tuple[JsonObject, str]:
        native_result = _mapping(
            context.prior_results.get(StageName.NATIVE_CONVERSION_ACQUISITION),
            "native CAD dependency",
        )
        selection_digest = _string(
            native_result.get("selection_digest"),
            "native CAD selection digest",
        )
        selection_bytes = self._verify_evidence_object(selection_digest)
        selection = _mapping(
            json.loads(selection_bytes),
            "native CAD selection",
        )
        manifest_digest = _string(
            selection.get("evidence_set_manifest_digest"),
            "native CAD evidence-set manifest",
        )
        if (
            selection.get("kicad_manifest_digest") != manifest_digest
            or selection.get("altium_manifest_digest") != manifest_digest
        ):
            raise ProductionWorkflowError("native CAD selection is not one evidence set")
        validation = self.evidence_store.verified_cad_validation_report(
            manifest_digest,
            identity=request.identity,
        )
        attestation = _provider_detail_attestation(validation, request.identity)
        report = verify_cross_eda_component(
            identity=request.identity,
            kicad_symbol=paths[NativeCadRole.KICAD_SYMBOL],
            kicad_footprint=paths[NativeCadRole.KICAD_FOOTPRINT],
            step_model=paths[NativeCadRole.STEP_MODEL],
            altium_sources=(
                paths[NativeCadRole.ALTIUM_SYMBOL],
                paths[NativeCadRole.ALTIUM_FOOTPRINT],
            ),
            altium_identity_attestation=attestation,
        )
        if not cross_eda_report_is_proved(report):
            raise ProductionWorkflowError("native CAD cross-verification was not proved")
        _assert_production_value(report, label="cross-EDA report")
        return report, self.evidence_store.install_bytes(_canonical_bytes(report))

    def _kicad_readback(self, context: StageContext) -> StageOutcome:
        stage = StageName.KICAD_BUILD_READBACK
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")

        def verify() -> CompletionOutcome:
            request = self._request(context)
            paths = self._native_artifacts(context, request.workspace)
            cross_report, cross_digest = self._strict_cross_report(context, request, paths)
            kicad_section = _mapping(cross_report.get("kicad"), "cross-EDA KiCad section")
            allowed = frozenset(
                _string(value, "unrepresented KiCad pad")
                for value in _sequence(
                    kicad_section.get("unrepresented_pad_numbers"),
                    "unrepresented KiCad pads",
                )
            )
            report = verify_kicad_component(
                identity=request.identity,
                kicad_symbol=paths[NativeCadRole.KICAD_SYMBOL],
                kicad_footprint=paths[NativeCadRole.KICAD_FOOTPRINT],
                step_model=paths[NativeCadRole.STEP_MODEL],
                allowed_unrepresented_pads=allowed,
            )
            report_digest = self.evidence_store.install_bytes(_canonical_bytes(report))
            return CompletionOutcome(
                _strict(
                    {
                        "cross_eda_report_digest": cross_digest,
                        "evidence_digests": sorted(
                            {request.record_digest, cross_digest, report_digest}
                        ),
                        "readback_report_digest": report_digest,
                        "schema": "stockroom.production-kicad-readback/1",
                        "stage": stage.value,
                    }
                )
            )

        guarded = self._invoke_guarded(stage, context, verify)
        return cast(StageOutcome, guarded)

    def _altium_readback(self, context: StageContext) -> StageOutcome:
        stage = StageName.ALTIUM_BUILD_READBACK
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")

        def verify() -> CompletionOutcome:
            request = self._request(context)
            paths = self._native_artifacts(context, request.workspace)
            cross_report, cross_digest = self._strict_cross_report(context, request, paths)
            cross_altium = _mapping(
                cross_report.get("altium"),
                "cross-EDA Altium section",
            )
            footprint_entry = _string(
                cross_altium.get("footprint_entry"),
                "cross-EDA Altium footprint entry",
            )
            symbol = read_altium_symbol(
                paths[NativeCadRole.ALTIUM_SYMBOL],
                request.identity.mpn_canonical,
            )
            footprint = read_altium_footprint(
                paths[NativeCadRole.ALTIUM_FOOTPRINT],
                footprint_entry,
            )
            readback = _strict(
                {
                    "footprint_entry": footprint.entry,
                    "manufacturer": symbol.manufacturer,
                    "mpn": symbol.mpn,
                    "pad_count": len(footprint.pads),
                    "pin_count": len(symbol.pins),
                    "schema": "stockroom.production-altium-readback/1",
                    "symbol_entry": symbol.entry,
                    "valid": True,
                }
            )
            report_digest = self.evidence_store.install_bytes(_canonical_bytes(readback))
            return CompletionOutcome(
                _strict(
                    {
                        "cross_eda_report_digest": cross_digest,
                        "evidence_digests": sorted(
                            {request.record_digest, cross_digest, report_digest}
                        ),
                        "readback_report_digest": report_digest,
                        "schema": "stockroom.production-altium-readback-stage/1",
                        "stage": stage.value,
                    }
                )
            )

        guarded = self._invoke_guarded(stage, context, verify)
        return cast(StageOutcome, guarded)

    def _cross_eda_verification(self, context: StageContext) -> StageOutcome:
        stage = StageName.CROSS_EDA_VERIFICATION
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")

        def verify() -> CompletionOutcome:
            request = self._request(context)
            paths = self._native_artifacts(context, request.workspace)
            report, report_digest = self._strict_cross_report(context, request, paths)
            dependencies = (
                StageName.KICAD_BUILD_READBACK,
                StageName.ALTIUM_BUILD_READBACK,
            )
            for dependency in dependencies:
                prior = _mapping(context.prior_results.get(dependency), dependency.value)
                if prior.get("cross_eda_report_digest") != report_digest:
                    raise ProductionWorkflowError(
                        "native readback and join cross-EDA reports differ"
                    )
            return CompletionOutcome(
                _strict(
                    {
                        "evidence_digests": [request.record_digest, report_digest],
                        "report_digest": report_digest,
                        "report_schema": report["schema"],
                        "schema": "stockroom.production-cross-eda-result/1",
                        "stage": stage.value,
                        "valid": True,
                    }
                )
            )

        guarded = self._invoke_guarded(stage, context, verify)
        return cast(StageOutcome, guarded)

    def _catalog_link_generation(self, context: StageContext) -> StageOutcome:
        stage = StageName.CATALOG_LINK_GENERATION
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")
        expected_base = self.repository.head()
        if not expected_base:
            return self._failure(stage, "publication_base_unavailable")

        def prepare() -> (
            tuple[
                ProductionStageRequest,
                ProductionPublicationCandidate,
                JsonObject,
                str,
                PreparedPublicationManifest,
            ]
            | ProductionStageStop
        ):
            stage_request = self._request(context)
            request = ProductionPublicationRequest(stage_request, expected_base)
            candidate = self.publication_adapter.prepare_candidate(request)
            if isinstance(candidate, ProductionStageStop):
                return candidate
            if type(candidate) is not ProductionPublicationCandidate:
                raise ProductionWorkflowError("publication candidate has an invalid type")
            adapter_document = dict(candidate.document)
            canonical_json(adapter_document)
            _assert_production_value(adapter_document, label="publication candidate")
            evidence = self._verified_digests(
                candidate.evidence_digests,
                include=(stage_request.record_digest,),
            )
            cross_result = _mapping(
                context.prior_results.get(StageName.CROSS_EDA_VERIFICATION),
                "cross-EDA result",
            )
            cross_digest = _string(
                cross_result.get("report_digest"),
                "cross-EDA report digest",
            )
            self._verify_evidence_object(cross_digest)
            identity_result = _mapping(
                context.prior_results.get(StageName.IDENTITY_DEDUPE),
                "identity result",
            )
            component_id = _string(identity_result.get("component_id"), "component ID")
            identity_digest = _string(
                identity_result.get("identity_digest"),
                "component identity digest",
            )
            candidate_document = _strict(
                {
                    "adapter": {
                        "key": self.publication_adapter.adapter_key,
                        "version": self.publication_adapter.adapter_version,
                    },
                    "candidate": adapter_document,
                    "component_id": component_id,
                    "cross_eda_report_digest": cross_digest,
                    "evidence_digests": sorted(set((*evidence, cross_digest))),
                    "identity_digest": identity_digest,
                    "part_record_digest": stage_request.record_digest,
                    "schema": "stockroom.production-publication-candidate/1",
                }
            )
            candidate_digest = _digest_json(candidate_document)
            publication = derive_publication_identity(
                parse_sha256(identity_digest, "identity digest"),
                parse_sha256(candidate_digest, "candidate digest"),
            )
            manifest = self.publication_adapter.prepare_manifest(
                request,
                candidate_document=candidate_document,
                candidate_digest=candidate_digest,
                publication_id=publication.publication_id,
            )
            return (
                stage_request,
                candidate,
                candidate_document,
                candidate_digest,
                manifest,
            )

        guarded = self._invoke_guarded(stage, context, prepare)
        if isinstance(guarded, PermanentFailureOutcome):
            return guarded
        if isinstance(guarded, ProductionStageStop):
            return self._stop_outcome(stage, context, guarded)
        try:
            request, candidate, candidate_document, candidate_digest, manifest = cast(
                tuple[
                    ProductionStageRequest,
                    ProductionPublicationCandidate,
                    JsonObject,
                    str,
                    PreparedPublicationManifest,
                ],
                guarded,
            )
            identity_result = _mapping(
                context.prior_results.get(StageName.IDENTITY_DEDUPE),
                "identity result",
            )
            component_id = _string(identity_result.get("component_id"), "component ID")
            identity_digest = _string(
                identity_result.get("identity_digest"),
                "component identity digest",
            )
            publication = derive_publication_identity(
                parse_sha256(identity_digest, "identity digest"),
                parse_sha256(candidate_digest, "candidate digest"),
            )
            if (
                type(manifest) is not PreparedPublicationManifest
                or manifest.component_id != component_id
                or manifest.publication_id != publication.publication_id
            ):
                raise ProductionWorkflowError(
                    "prepared manifest identity differs from the exact candidate"
                )
            self._validate_manifest_files(manifest)
            descriptor_digest = self._store_publication_descriptor(
                manifest,
                candidate_digest=candidate_digest,
                expected_base_commit=expected_base,
                expected_head_publication_id=candidate.expected_head_publication_id,
            )
            candidate_object_digest = self.evidence_store.install_bytes(
                _canonical_bytes(candidate_document)
            )
            evidence = self._verified_digests(
                candidate.evidence_digests,
                include=(
                    request.record_digest,
                    candidate_object_digest,
                    descriptor_digest,
                ),
            )
            return CompletionOutcome(
                _strict(
                    {
                        "candidate_digest": candidate_digest,
                        "candidate_object_digest": candidate_object_digest,
                        "descriptor_digest": descriptor_digest,
                        "evidence_digests": list(evidence),
                        "expected_base_commit": expected_base,
                        "expected_head_publication_id": (candidate.expected_head_publication_id),
                        "manifest_digest": manifest.digest,
                        "publication_id": manifest.publication_id,
                        "schema": "stockroom.production-publication-preparation/1",
                        "stage": stage.value,
                    }
                )
            )
        except Exception as exc:
            return self._failure(
                stage,
                "publication_preparation_rejected",
                details={"exception_type": type(exc).__name__},
            )

    def _validate_manifest_files(self, manifest: PreparedPublicationManifest) -> None:
        root = manifest.staging_root.resolve(strict=True)
        if (
            not root.is_dir()
            or _is_link(root)
            or not root.is_relative_to(self.staging_root)
            or root.is_relative_to(self.repo_root)
        ):
            raise ProductionWorkflowError(
                "publication staging root must be isolated under workflow staging"
            )
        for target in (*manifest.tracked_files, *manifest.machine_local_files):
            path = _path_under(root, target.target_path)
            if (
                not path.is_file()
                or _is_link(path)
                or _digest_bytes(path.read_bytes()) != target.sha256
            ):
                raise ProductionWorkflowError(
                    "prepared publication target bytes differ from their manifest"
                )
        catalog = _path_under(root, manifest.catalog_staged_path)
        if (
            not catalog.is_file()
            or _is_link(catalog)
            or _digest_bytes(catalog.read_bytes()) != manifest.catalog_sha256
        ):
            raise ProductionWorkflowError("prepared catalog bytes differ from their manifest")

    def _manifest_document(
        self,
        manifest: PreparedPublicationManifest,
        *,
        candidate_digest: str,
        expected_base_commit: str,
        expected_head_publication_id: str | None,
    ) -> JsonObject:
        return _strict(
            {
                "candidate_digest": candidate_digest,
                "expected_base_commit": expected_base_commit,
                "expected_head_publication_id": expected_head_publication_id,
                "manifest": {
                    "catalog_revision": manifest.catalog_revision,
                    "catalog_semantic_digest": manifest.catalog_semantic_digest,
                    "catalog_sha256": manifest.catalog_sha256,
                    "catalog_staged_path": manifest.catalog_staged_path,
                    "commit_message": manifest.commit_message,
                    "component_id": manifest.component_id,
                    "local_preparation_digest": manifest.local_preparation_digest,
                    "machine_local_files": [
                        {
                            "sha256": target.sha256,
                            "target_path": target.target_path,
                        }
                        for target in manifest.machine_local_files
                    ],
                    "manifest_digest": manifest.digest,
                    "publication_id": manifest.publication_id,
                    "staging_root": str(manifest.staging_root),
                    "tracked_files": [
                        {
                            "sha256": target.sha256,
                            "target_path": target.target_path,
                        }
                        for target in manifest.tracked_files
                    ],
                },
                "schema": "stockroom.production-publication-descriptor/1",
            }
        )

    def _descriptor_path(self, manifest_digest: str) -> Path:
        parse_sha256(manifest_digest, "manifest digest")
        return (
            self.staging_root
            / "Publication Manifests"
            / f"{manifest_digest.removeprefix('sha256:')}.json"
        )

    def _store_publication_descriptor(
        self,
        manifest: PreparedPublicationManifest,
        *,
        candidate_digest: str,
        expected_base_commit: str,
        expected_head_publication_id: str | None,
    ) -> str:
        document = self._manifest_document(
            manifest,
            candidate_digest=candidate_digest,
            expected_base_commit=expected_base_commit,
            expected_head_publication_id=expected_head_publication_id,
        )
        data = _canonical_bytes(document)
        digest = self.evidence_store.install_bytes(data)
        _install_exact(self._descriptor_path(manifest.digest), data)
        return digest

    def _load_publication_descriptor(self, manifest_digest: str) -> _PublicationDescriptor:
        path = self._descriptor_path(manifest_digest)
        if not path.is_file() or _is_link(path):
            raise ProductionWorkflowError("publication descriptor is missing or linked")
        data = path.read_bytes()
        try:
            document = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductionWorkflowError("publication descriptor is invalid JSON") from exc
        if (
            type(document) is not dict
            or _canonical_bytes(document) != data
            or document.get("schema") != "stockroom.production-publication-descriptor/1"
        ):
            raise ProductionWorkflowError("publication descriptor is not canonical")
        manifest_document = _mapping(document.get("manifest"), "prepared manifest")

        def targets(name: str) -> tuple[PreparedTarget, ...]:
            return tuple(
                PreparedTarget(
                    target_path=_string(item.get("target_path"), "prepared target path"),
                    sha256=_string(item.get("sha256"), "prepared target digest"),
                )
                for item in (
                    _mapping(value, "prepared target")
                    for value in _sequence(manifest_document.get(name), name)
                )
            )

        manifest = PreparedPublicationManifest(
            publication_id=_string(
                manifest_document.get("publication_id"),
                "publication ID",
            ),
            component_id=_string(manifest_document.get("component_id"), "component ID"),
            staging_root=Path(
                _string(manifest_document.get("staging_root"), "publication staging root")
            ),
            tracked_files=targets("tracked_files"),
            machine_local_files=targets("machine_local_files"),
            catalog_staged_path=_string(
                manifest_document.get("catalog_staged_path"),
                "catalog staged path",
            ),
            catalog_sha256=_string(
                manifest_document.get("catalog_sha256"),
                "catalog digest",
            ),
            catalog_revision=_string(
                manifest_document.get("catalog_revision"),
                "catalog revision",
            ),
            catalog_semantic_digest=_string(
                manifest_document.get("catalog_semantic_digest"),
                "catalog semantic digest",
            ),
            commit_message=_string(
                manifest_document.get("commit_message"),
                "commit message",
            ),
        )
        if (
            manifest.digest != manifest_digest
            or manifest_document.get("manifest_digest") != manifest.digest
            or manifest_document.get("local_preparation_digest")
            != manifest.local_preparation_digest
        ):
            raise ProductionWorkflowError("publication descriptor digest links differ")
        self._validate_manifest_files(manifest)
        return _PublicationDescriptor(
            manifest=manifest,
            candidate_digest=_string(
                document.get("candidate_digest"),
                "candidate digest",
            ),
            expected_base_commit=_string(
                document.get("expected_base_commit"),
                "expected base commit",
            ),
            expected_head_publication_id=(
                None
                if document.get("expected_head_publication_id") is None
                else _string(
                    document.get("expected_head_publication_id"),
                    "expected head publication ID",
                )
            ),
        )

    def _publish_proposal(self, context: StageContext) -> StageOutcome:
        stage = StageName.PUBLISH
        if context.stage.name is not stage:
            return self._failure(stage, "handler_stage_mismatch")
        try:
            self._load_exact_record(context, require_snapshot=True)
            preparation = _mapping(
                context.prior_results.get(StageName.CATALOG_LINK_GENERATION),
                "publication preparation",
            )
            if preparation.get("schema") != "stockroom.production-publication-preparation/1":
                raise ProductionWorkflowError("publication preparation schema is unknown")
            manifest_digest = _string(
                preparation.get("manifest_digest"),
                "manifest digest",
            )
            candidate_digest = _string(
                preparation.get("candidate_digest"),
                "candidate digest",
            )
            expected_base = _string(
                preparation.get("expected_base_commit"),
                "expected base commit",
            )
            descriptor = self._load_publication_descriptor(manifest_digest)
            if (
                descriptor.candidate_digest != candidate_digest
                or descriptor.expected_base_commit != expected_base
                or descriptor.manifest.publication_id != preparation.get("publication_id")
                or descriptor.expected_head_publication_id
                != preparation.get("expected_head_publication_id")
            ):
                raise ProductionWorkflowError(
                    "publication preparation differs from its durable descriptor"
                )
            if self.repository.head() != expected_base:
                return self._failure(stage, "publication_base_drift")
            before = self._live_state()
            self._validate_manifest_files(descriptor.manifest)
            if self._live_state() != before:
                return self._failure(stage, "live_library_mutation_before_publish")
            return PublicationProposalOutcome(
                candidate_digest=candidate_digest,
                manifest_digest=manifest_digest,
                expected_base_commit=expected_base,
                expected_head_publication_id=descriptor.expected_head_publication_id,
            )
        except Exception as exc:
            return self._failure(
                stage,
                "publication_proposal_rejected",
                details={"exception_type": type(exc).__name__},
            )


def build_production_workflow_handlers(
    *,
    repository: GitRepo,
    library_root: Path,
    parts_dir: Path,
    staging_root: Path,
    evidence_store: EvidenceStore,
    planner: ProviderPlanner,
    provider_runtime: ProviderExecutionRuntime,
    policy_inputs: tuple[ProviderPolicyInput, ...],
    semantic_adapters: Mapping[StageName, ProductionSemanticAdapter],
    publication_adapter: ProductionPublicationAdapter,
    publisher: ScopedComponentPublisher,
    cad_bundle_adapter: ProductionCadBundleAdapter | None = None,
    provider_stage_scope: ProviderStageScope | None = None,
    clock: Callable[[], float] = time.time,
    retry_policy: ProductionRetryPolicy = ProductionRetryPolicy(),
    provider_retry_bounds: ProviderRetryBounds = ProviderRetryBounds(),
) -> ProductionWorkflowRegistry:
    """Build one complete immutable production registry for AppContext wiring."""

    return ProductionWorkflowRegistry(
        repository=repository,
        library_root=library_root,
        parts_dir=parts_dir,
        staging_root=staging_root,
        evidence_store=evidence_store,
        planner=planner,
        provider_runtime=provider_runtime,
        policy_inputs=policy_inputs,
        semantic_adapters=semantic_adapters,
        publication_adapter=publication_adapter,
        publisher=publisher,
        cad_bundle_adapter=cad_bundle_adapter,
        provider_stage_scope=provider_stage_scope,
        clock=clock,
        retry_policy=retry_policy,
        provider_retry_bounds=provider_retry_bounds,
    )


__all__ = [
    "ExactEvidenceCadBundleAdapter",
    "NativeCadArtifact",
    "NativeCadRole",
    "PRODUCTION_SEMANTIC_STAGES",
    "ProductionCadBundle",
    "ProductionCadBundleAdapter",
    "ProductionPublicationAdapter",
    "ProductionPublicationCandidate",
    "ProductionPublicationRequest",
    "ProductionRetryPolicy",
    "ProductionSemanticAdapter",
    "ProductionStageCompletion",
    "ProductionStageRequest",
    "ProductionStageStop",
    "ProductionStopKind",
    "ProductionWorkflowError",
    "ProductionWorkflowRegistry",
    "build_production_workflow_handlers",
]
