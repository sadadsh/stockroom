"""One-part durable orchestration for the qualified ON Semiconductor S1M fixture.

This is intentionally a narrow integration slice.  It proves that the durable
fourteen-stage workflow can carry one exact component from intake through
canonical definition, native dual-EDA readback, catalog projection, and a
scoped publication receipt.  Fixture evidence is always labelled as fixture
evidence; ``fixture_mode=False`` remains unavailable until a real Altium
adapter exists.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Literal, cast

from stockroom.catalog import (
    CatalogArtifactRole,
    CatalogArtifacts,
    CatalogProjection,
    ProjectedArtifact,
    stage_catalog_projection,
    validate_catalog_projection,
)
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)
from stockroom.eda import (
    ArtifactDigest,
    DualEdaProjectionResult,
    EvidenceDigest,
    ObservedPad,
    ObservedPin,
    PortableKiCadLinkProjection,
    PortableLibraryRow,
    PortableTableArtifact,
    ToolBinding,
    ToolProjection,
    UnsupportedProjection,
    project_passive_bundle,
    project_portable_kicad_links,
)
from stockroom.publish import (
    PreparedPublicationManifest,
    PreparedTarget,
    ScopedComponentPublisher,
)
from stockroom.vcs import GitRepo
from stockroom.workflow import (
    BatchRecord,
    BatchStatus,
    CompletionOutcome,
    ComponentPublicationReceipt,
    ExactIdentityOutcome,
    IntakeIdentity,
    PublicationProposalOutcome,
    PublicationState,
    StageContext,
    StageHandlerRegistry,
    StageName,
    StageStatus,
    WorkflowRuntime,
    WorkflowStore,
)
from stockroom.workflow.identifiers import derive_publication_identity, parse_sha256
from stockroom.workflow.model import canonical_json

_MANUFACTURER = "ON Semiconductor"
_MPN = "S1M"
_FUNCTIONAL_KIND = "diode"
_VALUE = "1 A 1000 V"
_PACKAGE = "SMA (DO-214AC)"
_FIXTURE_LOCATOR = "qualified-fixture://stockroom/on-semiconductor/s1m/sample-intlib"
_REGISTRY_REVISION = "onsemi-qualified-fixture-registry-v1"
_RULE_REVISION = "authoritative-exact-v1"
_SCHEMA_VERSION = 1

JsonObject = dict[str, object]
ToolKey = Literal["kicad", "altium"]
ArtifactKind = Literal["symbol", "footprint"]


class FixturePlanningError(RuntimeError):
    """Durable fixture evidence or a staged projection violated an invariant."""


class PlanningStalled(FixturePlanningError):
    """No workflow or publication transition can advance an unfinished batch."""


@dataclass(frozen=True, slots=True)
class FixtureRunResult:
    """The durable terminal evidence for one completed fixture batch."""

    batch: BatchRecord
    item_id: str
    publication_id: str
    receipt: ComponentPublicationReceipt


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_json(document: object) -> str:
    encoded = canonical_json(document).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise FixturePlanningError(f"{label} is not a JSON object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise FixturePlanningError(f"{label} is not a JSON array")
    return cast(Sequence[object], value)


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise FixturePlanningError(f"{label} is not a JSON string")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise FixturePlanningError(f"{label} is not a JSON integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise FixturePlanningError(f"{label} is not a JSON boolean")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _exact_keys(
    value: object,
    expected: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    document = _mapping(value, label)
    if frozenset(document) != expected:
        raise FixturePlanningError(f"{label} has an unexpected JSON shape")
    return document


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, list):
        return [_thaw(item) for item in value]
    return value


def _relative_posix(root: Path, path: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FixturePlanningError("projection path escaped the item staging root") from exc
    result = relative.as_posix()
    pure = PurePosixPath(result)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise FixturePlanningError("projection path is not a portable relative path")
    return result


def _path_at(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if (
        not relative_path
        or pure.is_absolute()
        or pure.as_posix() != relative_path
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise FixturePlanningError("staged artifact path is not portable")
    path = root.joinpath(*pure.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FixturePlanningError("staged artifact path escaped its root") from exc
    return path


def _install_exact_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != content:
            raise FixturePlanningError(
                f"durable staged file differs from its canonical bytes: {path.name}"
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".temporary",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if path.read_bytes() != content:
        raise FixturePlanningError("canonical staged file failed byte readback")


def _artifact_json(artifact: ArtifactDigest) -> JsonObject:
    return {
        "digest": artifact.digest,
        "kind": artifact.kind,
        "reference": artifact.reference,
        "relative_path": artifact.relative_path,
        "size_bytes": artifact.size_bytes,
        "template_id": artifact.template_id,
        "tool": artifact.tool,
    }


def _artifact_from_json(value: object) -> ArtifactDigest:
    document = _exact_keys(
        value,
        frozenset(
            {
                "digest",
                "kind",
                "reference",
                "relative_path",
                "size_bytes",
                "template_id",
                "tool",
            }
        ),
        "EDA artifact",
    )
    tool_text = _string(document["tool"], "EDA artifact tool")
    kind_text = _string(document["kind"], "EDA artifact kind")
    if tool_text not in {"kicad", "altium"}:
        raise FixturePlanningError("EDA artifact tool is unsupported")
    if kind_text not in {"symbol", "footprint"}:
        raise FixturePlanningError("EDA artifact kind is unsupported")
    return ArtifactDigest(
        tool=tool_text,
        kind=kind_text,
        template_id=_string(document["template_id"], "EDA artifact template"),
        reference=_string(document["reference"], "EDA artifact reference"),
        relative_path=_string(document["relative_path"], "EDA artifact path"),
        digest=_string(document["digest"], "EDA artifact digest"),
        size_bytes=_integer(document["size_bytes"], "EDA artifact size"),
    )


def _evidence_json(evidence: EvidenceDigest) -> JsonObject:
    return {
        "digest": evidence.digest,
        "locator": evidence.locator,
        "size_bytes": evidence.size_bytes,
    }


def _evidence_from_json(value: object) -> EvidenceDigest:
    document = _exact_keys(
        value,
        frozenset({"digest", "locator", "size_bytes"}),
        "EDA evidence",
    )
    return EvidenceDigest(
        locator=_string(document["locator"], "EDA evidence locator"),
        digest=_string(document["digest"], "EDA evidence digest"),
        size_bytes=_integer(document["size_bytes"], "EDA evidence size"),
    )


def _pin_json(pin: ObservedPin) -> JsonObject:
    return {
        "name": pin.name,
        "native_number": pin.native_number,
        "tool_terminal": pin.tool_terminal,
    }


def _pin_from_json(value: object) -> ObservedPin:
    document = _exact_keys(
        value,
        frozenset({"name", "native_number", "tool_terminal"}),
        "observed pin",
    )
    return ObservedPin(
        native_number=_string(document["native_number"], "native pin number"),
        name=_string(document["name"], "native pin name"),
        tool_terminal=_string(document["tool_terminal"], "pin tool terminal"),
    )


def _pad_json(pad: ObservedPad) -> JsonObject:
    return {
        "native_number": pad.native_number,
        "tool_terminal": pad.tool_terminal,
    }


def _pad_from_json(value: object) -> ObservedPad:
    document = _exact_keys(
        value,
        frozenset({"native_number", "tool_terminal"}),
        "observed pad",
    )
    return ObservedPad(
        native_number=_string(document["native_number"], "native pad number"),
        tool_terminal=_string(document["tool_terminal"], "pad tool terminal"),
    )


def _binding_json(binding: ToolBinding) -> JsonObject:
    return {
        "footprint_library": binding.footprint_library,
        "footprint_library_nickname": binding.footprint_library_nickname,
        "footprint_ref": binding.footprint_ref,
        "footprint_template_id": binding.footprint_template_id,
        "source_footprint_reference": binding.source_footprint_reference,
        "source_symbol_reference": binding.source_symbol_reference,
        "symbol_library": binding.symbol_library,
        "symbol_library_nickname": binding.symbol_library_nickname,
        "symbol_ref": binding.symbol_ref,
        "symbol_template_id": binding.symbol_template_id,
    }


def _binding_from_json(value: object) -> ToolBinding:
    keys = frozenset(
        {
            "footprint_library",
            "footprint_library_nickname",
            "footprint_ref",
            "footprint_template_id",
            "source_footprint_reference",
            "source_symbol_reference",
            "symbol_library",
            "symbol_library_nickname",
            "symbol_ref",
            "symbol_template_id",
        }
    )
    document = _exact_keys(value, keys, "tool binding")
    return ToolBinding(
        symbol_template_id=_string(document["symbol_template_id"], "symbol template"),
        footprint_template_id=_string(
            document["footprint_template_id"],
            "footprint template",
        ),
        source_symbol_reference=_string(
            document["source_symbol_reference"],
            "source symbol reference",
        ),
        source_footprint_reference=_string(
            document["source_footprint_reference"],
            "source footprint reference",
        ),
        symbol_library=_string(document["symbol_library"], "symbol library"),
        symbol_library_nickname=_optional_string(
            document["symbol_library_nickname"],
            "symbol library nickname",
        ),
        symbol_ref=_string(document["symbol_ref"], "symbol reference"),
        footprint_library=_string(
            document["footprint_library"],
            "footprint library",
        ),
        footprint_library_nickname=_optional_string(
            document["footprint_library_nickname"],
            "footprint library nickname",
        ),
        footprint_ref=_string(document["footprint_ref"], "footprint reference"),
    )


def _tool_json(projection: ToolProjection) -> JsonObject:
    return {
        "artifacts": [_artifact_json(artifact) for artifact in projection.artifacts],
        "binding": _binding_json(projection.binding),
        "evidence": [_evidence_json(evidence) for evidence in projection.evidence],
        "fixture_mode": projection.fixture_mode,
        "pads": [_pad_json(pad) for pad in projection.pads],
        "pins": [_pin_json(pin) for pin in projection.pins],
        "tool": projection.tool,
        "tool_version": projection.tool_version,
    }


def _tool_from_json(value: object) -> ToolProjection:
    document = _exact_keys(
        value,
        frozenset(
            {
                "artifacts",
                "binding",
                "evidence",
                "fixture_mode",
                "pads",
                "pins",
                "tool",
                "tool_version",
            }
        ),
        "tool projection",
    )
    tool_text = _string(document["tool"], "tool projection key")
    if tool_text not in {"kicad", "altium"}:
        raise FixturePlanningError("tool projection key is unsupported")
    artifacts = tuple(
        _artifact_from_json(item) for item in _sequence(document["artifacts"], "tool artifacts")
    )
    pins = tuple(_pin_from_json(item) for item in _sequence(document["pins"], "tool pins"))
    pads = tuple(_pad_from_json(item) for item in _sequence(document["pads"], "tool pads"))
    evidence = tuple(
        _evidence_from_json(item) for item in _sequence(document["evidence"], "tool evidence")
    )
    if len(artifacts) != 2 or len(pins) != 2 or len(pads) != 2:
        raise FixturePlanningError("tool projection does not contain a two-pin artifact set")
    return ToolProjection(
        tool=tool_text,
        tool_version=_string(document["tool_version"], "tool version"),
        fixture_mode=_boolean(document["fixture_mode"], "tool fixture mode"),
        binding=_binding_from_json(document["binding"]),
        artifacts=artifacts,
        pins=pins,
        pads=pads,
        evidence=evidence,
    )


def _projection_json(result: DualEdaProjectionResult) -> JsonObject:
    return {
        "altium": _tool_json(result.altium),
        "canonical_bundle_digest": result.canonical_bundle_digest,
        "canonical_terminal_numbers": list(result.canonical_terminal_numbers),
        "kicad": _tool_json(result.kicad),
        "limitations": list(result.limitations),
        "production_ready": result.production_ready,
        "semantic_cross_check_passed": result.semantic_cross_check_passed,
    }


def _projection_from_json(value: object) -> DualEdaProjectionResult:
    document = _exact_keys(
        value,
        frozenset(
            {
                "altium",
                "canonical_bundle_digest",
                "canonical_terminal_numbers",
                "kicad",
                "limitations",
                "production_ready",
                "semantic_cross_check_passed",
            }
        ),
        "dual-EDA projection",
    )
    terminals = tuple(
        _string(item, "canonical terminal")
        for item in _sequence(
            document["canonical_terminal_numbers"],
            "canonical terminal numbers",
        )
    )
    limitations = tuple(
        _string(item, "projection limitation")
        for item in _sequence(document["limitations"], "projection limitations")
    )
    if len(terminals) != 2:
        raise FixturePlanningError("dual-EDA projection has an invalid terminal count")
    result = DualEdaProjectionResult(
        canonical_bundle_digest=_string(
            document["canonical_bundle_digest"],
            "canonical bundle digest",
        ),
        canonical_terminal_numbers=terminals,
        kicad=_tool_from_json(document["kicad"]),
        altium=_tool_from_json(document["altium"]),
        limitations=limitations,
    )
    if (
        _boolean(
            document["semantic_cross_check_passed"],
            "semantic cross-check state",
        )
        is not result.semantic_cross_check_passed
        or _boolean(document["production_ready"], "production-ready state")
        is not result.production_ready
    ):
        raise FixturePlanningError("derived dual-EDA state was altered")
    return result


def _portable_row_json(row: PortableLibraryRow) -> JsonObject:
    return {
        "artifact_digest": row.artifact_digest,
        "artifact_relative_path": row.artifact_relative_path,
        "kind": row.kind,
        "library_reference": row.library_reference,
        "library_relative_path": row.library_relative_path,
        "nickname": row.nickname,
        "uri": row.uri,
    }


def _portable_row_from_json(value: object) -> PortableLibraryRow:
    document = _exact_keys(
        value,
        frozenset(
            {
                "artifact_digest",
                "artifact_relative_path",
                "kind",
                "library_reference",
                "library_relative_path",
                "nickname",
                "uri",
            }
        ),
        "portable KiCad row",
    )
    kind = _string(document["kind"], "portable KiCad row kind")
    if kind not in {"symbol", "footprint"}:
        raise FixturePlanningError("portable KiCad row kind is unsupported")
    return PortableLibraryRow(
        kind=kind,
        nickname=_string(document["nickname"], "portable KiCad nickname"),
        uri=_string(document["uri"], "portable KiCad URI"),
        library_reference=_string(
            document["library_reference"],
            "portable KiCad library reference",
        ),
        library_relative_path=_string(
            document["library_relative_path"],
            "portable KiCad library path",
        ),
        artifact_relative_path=_string(
            document["artifact_relative_path"],
            "portable KiCad artifact path",
        ),
        artifact_digest=_string(
            document["artifact_digest"],
            "portable KiCad artifact digest",
        ),
    )


def _portable_table_json(table: PortableTableArtifact) -> JsonObject:
    return {
        "digest": table.digest,
        "kind": table.kind,
        "relative_path": table.relative_path,
        "row_count": table.row_count,
        "size_bytes": table.size_bytes,
    }


def _portable_table_from_json(value: object) -> PortableTableArtifact:
    document = _exact_keys(
        value,
        frozenset(
            {
                "digest",
                "kind",
                "relative_path",
                "row_count",
                "size_bytes",
            }
        ),
        "portable KiCad table",
    )
    kind = _string(document["kind"], "portable KiCad table kind")
    if kind not in {"symbol", "footprint"}:
        raise FixturePlanningError("portable KiCad table kind is unsupported")
    return PortableTableArtifact(
        kind=kind,
        relative_path=_string(
            document["relative_path"],
            "portable KiCad table path",
        ),
        digest=_string(document["digest"], "portable KiCad table digest"),
        size_bytes=_integer(
            document["size_bytes"],
            "portable KiCad table size",
        ),
        row_count=_integer(
            document["row_count"],
            "portable KiCad table row count",
        ),
    )


def _portable_links_json(projection: PortableKiCadLinkProjection) -> JsonObject:
    return {
        "footprint_rows": [_portable_row_json(row) for row in projection.footprint_rows],
        "footprint_table": _portable_table_json(projection.footprint_table),
        "requires_machine_local_install": projection.requires_machine_local_install,
        "symbol_rows": [_portable_row_json(row) for row in projection.symbol_rows],
        "symbol_table": _portable_table_json(projection.symbol_table),
    }


def _portable_links_from_json(value: object) -> PortableKiCadLinkProjection:
    document = _exact_keys(
        value,
        frozenset(
            {
                "footprint_rows",
                "footprint_table",
                "requires_machine_local_install",
                "symbol_rows",
                "symbol_table",
            }
        ),
        "portable KiCad link projection",
    )
    symbol_rows = tuple(
        _portable_row_from_json(row)
        for row in _sequence(document["symbol_rows"], "portable symbol rows")
    )
    footprint_rows = tuple(
        _portable_row_from_json(row)
        for row in _sequence(
            document["footprint_rows"],
            "portable footprint rows",
        )
    )
    result = PortableKiCadLinkProjection(
        symbol_table=_portable_table_from_json(document["symbol_table"]),
        footprint_table=_portable_table_from_json(document["footprint_table"]),
        symbol_rows=symbol_rows,
        footprint_rows=footprint_rows,
    )
    if (
        _boolean(
            document["requires_machine_local_install"],
            "portable KiCad install requirement",
        )
        is not result.requires_machine_local_install
    ):
        raise FixturePlanningError("portable KiCad activation state was altered")
    return result


class OnePartFixtureRunner:
    """Bind the durable workflow to the one qualified S1M integration slice."""

    def __init__(
        self,
        store: WorkflowStore,
        staging_root: str | Path,
        repository: GitRepo,
        fixture_path: str | Path,
        *,
        fixture_mode: bool,
        live_catalog_path: str | Path | None = None,
        machine_local_root: str | Path | None = None,
    ):
        if type(fixture_mode) is not bool:
            raise TypeError("fixture_mode must be an explicit boolean")
        if fixture_mode is not True:
            raise UnsupportedProjection(
                "fixture_mode=False requires a real native Altium adapter, which is not implemented"
            )
        if not isinstance(store, WorkflowStore):
            raise TypeError("store must be a WorkflowStore")
        if not isinstance(repository, GitRepo):
            raise TypeError("repository must be a GitRepo")

        root = Path(staging_root).absolute()
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise FixturePlanningError("staging_root must be a non-linked directory")

        fixture = Path(fixture_path).absolute()
        if not fixture.is_file() or fixture.is_symlink() or fixture.suffix.casefold() != ".intlib":
            raise FixturePlanningError("fixture_path must be a non-linked existing .IntLib")
        if not repository.is_git_repo() or not repository.head():
            raise FixturePlanningError(
                "repository must be initialized with an attached base commit"
            )
        repo_root = repository.root.absolute()
        try:
            root.resolve().relative_to(repo_root.resolve())
        except ValueError:
            pass
        else:
            raise FixturePlanningError("staging_root must be outside the publication repository")

        activation_root = root / "Active"
        activation_root.mkdir(parents=True, exist_ok=True)
        live = (
            activation_root / "Catalog.sqlite"
            if live_catalog_path is None
            else Path(live_catalog_path).absolute()
        )
        live.parent.mkdir(parents=True, exist_ok=True)
        if live.name.casefold() != "catalog.sqlite" or live.parent.is_symlink():
            raise FixturePlanningError(
                "live_catalog_path must name Catalog.sqlite in a non-linked directory"
            )
        local_root = (
            activation_root if machine_local_root is None else Path(machine_local_root).absolute()
        )
        local_root.mkdir(parents=True, exist_ok=True)
        if local_root.is_symlink() or not local_root.is_dir():
            raise FixturePlanningError("machine_local_root must be a non-linked directory")

        self.store = store
        self.staging_root = root.resolve()
        self.repository = repository
        self.fixture_path = fixture.resolve()
        self.fixture_mode = fixture_mode
        self.live_catalog_path = live.resolve()
        self.machine_local_root = local_root.resolve()
        handlers = {
            StageName.IDENTITY_DEDUPE: self._identity,
            StageName.METADATA: self._metadata,
            StageName.DATASHEET: self._datasheet,
            StageName.EXISTING_EVIDENCE: self._existing_evidence,
            StageName.CAD_ACQUISITION: self._cad_acquisition,
            StageName.RECONCILE: self._reconcile,
            StageName.CANONICAL_DEFINITION: self._canonical_definition,
            StageName.TEMPLATE_GENERATION: self._template_generation,
            StageName.NATIVE_CONVERSION_ACQUISITION: self._native_conversion,
            StageName.KICAD_BUILD_READBACK: self._kicad_readback,
            StageName.ALTIUM_BUILD_READBACK: self._altium_readback,
            StageName.CROSS_EDA_VERIFICATION: self._cross_eda_verification,
            StageName.CATALOG_LINK_GENERATION: self._catalog_link_generation,
            StageName.PUBLISH: self._publish_proposal,
        }
        self._handlers: StageHandlerRegistry = MappingProxyType(handlers)
        self.runtime = WorkflowRuntime(store, self._handlers)
        self.publisher = ScopedComponentPublisher(
            store,
            repository,
            live_catalog_path=self.live_catalog_path,
            machine_local_root=self.machine_local_root,
        )

    @property
    def handlers(self) -> StageHandlerRegistry:
        """Return the complete immutable fourteen-stage handler registry."""

        return self._handlers

    def submit_fixture(
        self,
        *,
        idempotency_key: str | None = None,
    ) -> BatchRecord:
        """Submit the exact qualified identity with explicit fixture provenance."""

        return self.store.submit_batch(
            (
                IntakeIdentity(
                    manufacturer=_MANUFACTURER,
                    mpn=_MPN,
                    payload={
                        "fixture": self._fixture_evidence(),
                        "fixture_mode": True,
                        "schema_version": _SCHEMA_VERSION,
                    },
                ),
            ),
            idempotency_key=idempotency_key,
        )

    def poll_stage(self, worker_id: str):
        """Dispatch at most one durable workflow stage."""

        return self.runtime.poll_once(worker_id)

    def run_to_completion(
        self,
        batch_id: str,
        *,
        worker_id: str = "qualified_fixture_runner",
        max_transitions: int = 128,
    ) -> FixtureRunResult:
        """Advance stages and scoped publication until one durable receipt exists."""

        if type(max_transitions) is not int or max_transitions <= 0:
            raise ValueError("max_transitions must be a positive integer")
        self._one_item(batch_id)
        for _ in range(max_transitions):
            batch = self.store.get_batch(batch_id)
            if batch.status is BatchStatus.COMPLETED:
                return self._completed_result(batch)
            if batch.status in {
                BatchStatus.CANCELLED,
                BatchStatus.FAILED,
                BatchStatus.PAUSED,
            }:
                raise PlanningStalled(f"fixture batch reached terminal status {batch.status.value}")

            dispatch = self.runtime.poll_once(worker_id)
            if dispatch is not None:
                continue
            leases = self.store.claim_publications(worker_id, limit=1)
            if leases:
                lease = leases[0]
                operation = self.store.get_publication_operation(lease.publication_id)
                manifest = self._manifest_for_batch(
                    batch_id,
                    expected_base_commit=operation.expected_base_commit,
                )
                if manifest.publication_id != lease.publication_id:
                    raise FixturePlanningError(
                        "reconstructed manifest differs from publication lease"
                    )
                if lease.state is PublicationState.PREPARING:
                    self.publisher.publish(manifest, lease)
                else:
                    self.publisher.reconcile(manifest, lease)
                continue
            raise PlanningStalled(
                "unfinished fixture batch has no ready stage or publication lease"
            )
        raise PlanningStalled("fixture batch exceeded its transition bound")

    def _one_item(self, batch_id: str):
        items = self.store.list_items(batch_id)
        if len(items) != 1:
            raise FixturePlanningError(
                "the qualified fixture runner requires exactly one batch item"
            )
        return items[0]

    def _item_root(self, item_id: str) -> Path:
        root = self.staging_root / "Items" / item_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _require_exact_item(self, context: StageContext) -> None:
        item = context.item
        if (
            item.manufacturer != _MANUFACTURER
            or item.mpn != _MPN
            or item.manufacturer_key != _MANUFACTURER
            or item.mpn_key != _MPN
        ):
            raise FixturePlanningError(
                "qualified fixture runner supports only exact ON Semiconductor/S1M"
            )

    def _fixture_evidence(self) -> JsonObject:
        digest = _sha256_file(self.fixture_path)
        return {
            "content_digest": digest,
            "fixture_mode": True,
            "locator": _FIXTURE_LOCATOR,
            "size_bytes": self.fixture_path.stat().st_size,
            "source_kind": "qualified_fixture",
        }

    def _facts(self) -> JsonObject:
        return {
            "functional_kind": _FUNCTIONAL_KIND,
            "manufacturer": _MANUFACTURER,
            "mpn": _MPN,
            "package": _PACKAGE,
            "value": _VALUE,
        }

    def _identity_document(self) -> JsonObject:
        return {
            "fixture": self._fixture_evidence(),
            "fixture_mode": True,
            "kind": "exact_qualified_fixture_identity",
            "schema_version": _SCHEMA_VERSION,
        }

    def _metadata_document(self) -> JsonObject:
        return {
            "evidence": self._fixture_evidence(),
            "facts": self._facts(),
            "kind": "qualified_fixture_metadata",
            "schema_version": _SCHEMA_VERSION,
        }

    def _datasheet_document(self) -> JsonObject:
        return {
            "claims": {
                "package": _PACKAGE,
                "value": _VALUE,
            },
            "evidence": self._fixture_evidence(),
            "kind": "qualified_fixture_claim_evidence",
            "limitations": [
                "No live manufacturer datasheet was retrieved in fixture mode.",
            ],
            "schema_version": _SCHEMA_VERSION,
        }

    def _existing_evidence_document(self) -> JsonObject:
        return {
            "evidence": self._fixture_evidence(),
            "identity": {
                "manufacturer": _MANUFACTURER,
                "mpn": _MPN,
            },
            "kind": "qualified_existing_native_evidence",
            "schema_version": _SCHEMA_VERSION,
        }

    def _cad_document(self) -> JsonObject:
        return {
            "evidence": self._fixture_evidence(),
            "fixture_mode": True,
            "kind": "qualified_altium_intlib_acquisition",
            "limitations": [
                "The Altium source is a checked-in qualified fixture, not a live acquisition.",
            ],
            "schema_version": _SCHEMA_VERSION,
        }

    def _reconcile_document(self) -> JsonObject:
        return {
            "evidence": self._fixture_evidence(),
            "facts": self._facts(),
            "kind": "reconciled_qualified_fixture_claims",
            "schema_version": _SCHEMA_VERSION,
            "selection_rule_revision": _RULE_REVISION,
        }

    def _require_prior(
        self,
        context: StageContext,
        stage: StageName,
        expected: object,
    ) -> None:
        actual = context.prior_results.get(stage)
        if _thaw(actual) != expected:
            raise FixturePlanningError(
                f"{stage.value} durable result differs from qualified fixture evidence"
            )

    def _identity(self, context: StageContext) -> ExactIdentityOutcome:
        self._require_exact_item(context)
        return ExactIdentityOutcome(
            authoritative_manufacturer_key=_MANUFACTURER,
            mpn_canonical=_MPN,
            registry_revision=_REGISTRY_REVISION,
            rule_revision=_RULE_REVISION,
            evidence=self._identity_document(),
        )

    def _metadata(self, context: StageContext) -> CompletionOutcome:
        self._require_exact_item(context)
        return CompletionOutcome(self._metadata_document())

    def _datasheet(self, context: StageContext) -> CompletionOutcome:
        self._require_exact_item(context)
        return CompletionOutcome(self._datasheet_document())

    def _existing_evidence(self, context: StageContext) -> CompletionOutcome:
        self._require_exact_item(context)
        return CompletionOutcome(self._existing_evidence_document())

    def _cad_acquisition(self, context: StageContext) -> CompletionOutcome:
        self._require_exact_item(context)
        return CompletionOutcome(self._cad_document())

    def _reconcile(self, context: StageContext) -> CompletionOutcome:
        self._require_prior(
            context,
            StageName.METADATA,
            self._metadata_document(),
        )
        self._require_prior(
            context,
            StageName.DATASHEET,
            self._datasheet_document(),
        )
        self._require_prior(
            context,
            StageName.EXISTING_EVIDENCE,
            self._existing_evidence_document(),
        )
        return CompletionOutcome(self._reconcile_document())

    def _build_bundle(self) -> CanonicalPassiveBundle:
        fixture = self._fixture_evidence()
        digest = _string(fixture["content_digest"], "fixture content digest")
        value_evidence = AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"{_FIXTURE_LOCATOR}#value",
            content_digest=digest,
        )
        package_evidence = AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"{_FIXTURE_LOCATOR}#package",
            content_digest=digest,
        )
        return build_two_pin_passive_bundle(
            authoritative_manufacturer_key=_MANUFACTURER,
            mpn_canonical=_MPN,
            functional_kind="diode",
            value=_VALUE,
            package=_PACKAGE,
            value_evidence=value_evidence,
            package_evidence=package_evidence,
        )

    def _canonical_result(
        self,
        item_id: str,
        bundle: CanonicalPassiveBundle,
    ) -> JsonObject:
        item_root = self._item_root(item_id)
        relative_path = (
            PurePosixPath("Components") / bundle.identity.component_id / "Canonical Component.json"
        ).as_posix()
        path = _path_at(item_root, relative_path)
        _install_exact_file(path, bundle.canonical_bytes())
        digest = _sha256_file(path)
        if digest != bundle.canonical_digest():
            raise FixturePlanningError("canonical component file digest link is invalid")
        return {
            "bundle": bundle.model_dump(mode="json"),
            "bundle_digest": digest,
            "kind": "canonical_passive_bundle",
            "path": relative_path,
            "schema_version": _SCHEMA_VERSION,
        }

    def _bundle_from_prior(
        self,
        prior_results: Mapping[StageName, object],
    ) -> tuple[CanonicalPassiveBundle, Mapping[str, object]]:
        raw = prior_results.get(StageName.CANONICAL_DEFINITION)
        document = _exact_keys(
            raw,
            frozenset(
                {
                    "bundle",
                    "bundle_digest",
                    "kind",
                    "path",
                    "schema_version",
                }
            ),
            "canonical definition result",
        )
        try:
            bundle = CanonicalPassiveBundle.model_validate_json(
                canonical_json(_thaw(document["bundle"]))
            )
        except ValueError as exc:
            raise FixturePlanningError("durable canonical definition does not reconstruct") from exc
        if (
            document["kind"] != "canonical_passive_bundle"
            or document["schema_version"] != _SCHEMA_VERSION
            or document["bundle_digest"] != bundle.canonical_digest()
        ):
            raise FixturePlanningError("durable canonical definition proof differs")
        return bundle, document

    def _canonical_definition(self, context: StageContext) -> CompletionOutcome:
        self._require_prior(
            context,
            StageName.RECONCILE,
            self._reconcile_document(),
        )
        bundle = self._build_bundle()
        return CompletionOutcome(self._canonical_result(context.item.id, bundle))

    def _template_document(self, bundle: CanonicalPassiveBundle) -> JsonObject:
        return {
            "artifact_set_digest": bundle.verification.artifact_set_digest,
            "kind": "shared_template_plan",
            "schema_version": _SCHEMA_VERSION,
            "templates": [
                template.model_dump(mode="json") for template in bundle.artifacts.shared_templates
            ],
            "tool_bindings": [
                binding.model_dump(mode="json") for binding in bundle.artifacts.tool_bindings
            ],
        }

    def _template_generation(self, context: StageContext) -> CompletionOutcome:
        bundle, _document = self._bundle_from_prior(context.prior_results)
        return CompletionOutcome(self._template_document(bundle))

    def _verify_projection_files(
        self,
        item_root: Path,
        projection: DualEdaProjectionResult,
    ) -> None:
        expected: set[str] = set()
        for artifact in projection.artifacts:
            path = _path_at(item_root, artifact.relative_path)
            if (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_size != artifact.size_bytes
                or _sha256_file(path) != artifact.digest
            ):
                raise FixturePlanningError(
                    f"EDA artifact failed durable byte readback: {artifact.relative_path}"
                )
            expected.add(artifact.relative_path)
        eda_root = item_root / "EDA"
        actual = {
            path.relative_to(item_root).as_posix() for path in eda_root.rglob("*") if path.is_file()
        }
        if actual != expected:
            raise FixturePlanningError("EDA staging tree contains unexpected files")

    def _materialize_projection(
        self,
        item_id: str,
        bundle: CanonicalPassiveBundle,
    ) -> DualEdaProjectionResult:
        item_root = self._item_root(item_id)
        attempts = self.staging_root / ".Attempts"
        attempts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=attempts,
            prefix=f"{item_id}.",
        ) as temporary:
            attempt = Path(temporary)
            result = project_passive_bundle(
                bundle,
                attempt,
                fixture_mode=True,
                altium_intlib=self.fixture_path,
            )
            self._verify_projection_files(attempt, result)
            target = item_root / "EDA"
            if target.exists():
                self._verify_projection_files(item_root, result)
            else:
                os.replace(attempt / "EDA", target)
            self._verify_projection_files(item_root, result)
            return result

    def _native_document(self, result: DualEdaProjectionResult) -> JsonObject:
        return {
            "kind": "qualified_dual_eda_projection",
            "projection": _projection_json(result),
            "schema_version": _SCHEMA_VERSION,
        }

    def _projection_from_prior(
        self,
        prior_results: Mapping[StageName, object],
    ) -> DualEdaProjectionResult:
        raw = prior_results.get(StageName.NATIVE_CONVERSION_ACQUISITION)
        document = _exact_keys(
            raw,
            frozenset({"kind", "projection", "schema_version"}),
            "native conversion result",
        )
        if (
            document["kind"] != "qualified_dual_eda_projection"
            or document["schema_version"] != _SCHEMA_VERSION
        ):
            raise FixturePlanningError("native conversion result version differs")
        return _projection_from_json(document["projection"])

    def _native_conversion(self, context: StageContext) -> CompletionOutcome:
        self._require_prior(
            context,
            StageName.CAD_ACQUISITION,
            self._cad_document(),
        )
        bundle, _document = self._bundle_from_prior(context.prior_results)
        result = self._materialize_projection(context.item.id, bundle)
        if result.canonical_bundle_digest != bundle.canonical_digest():
            raise FixturePlanningError("EDA projection references a different bundle")
        return CompletionOutcome(self._native_document(result))

    def _tool_readback_document(
        self,
        result: DualEdaProjectionResult,
        tool: ToolKey,
    ) -> JsonObject:
        projection = result.kicad if tool == "kicad" else result.altium
        return {
            "canonical_bundle_digest": result.canonical_bundle_digest,
            "kind": f"{tool}_native_build_readback",
            "projection": _tool_json(projection),
            "schema_version": _SCHEMA_VERSION,
        }

    def _kicad_readback(self, context: StageContext) -> CompletionOutcome:
        bundle, _document = self._bundle_from_prior(context.prior_results)
        self._require_prior(
            context,
            StageName.TEMPLATE_GENERATION,
            self._template_document(bundle),
        )
        result = self._projection_from_prior(context.prior_results)
        self._verify_projection_files(self._item_root(context.item.id), result)
        return CompletionOutcome(self._tool_readback_document(result, "kicad"))

    def _altium_readback(self, context: StageContext) -> CompletionOutcome:
        bundle, _document = self._bundle_from_prior(context.prior_results)
        self._require_prior(
            context,
            StageName.TEMPLATE_GENERATION,
            self._template_document(bundle),
        )
        result = self._projection_from_prior(context.prior_results)
        self._verify_projection_files(self._item_root(context.item.id), result)
        return CompletionOutcome(self._tool_readback_document(result, "altium"))

    def _catalog_artifacts(
        self,
        projection: DualEdaProjectionResult,
    ) -> CatalogArtifacts:
        links = tuple(
            ProjectedArtifact(
                tool=artifact.tool,
                kind=artifact.kind,
                template_id=artifact.template_id,
                reference=artifact.reference,
                path=artifact.relative_path,
                digest=artifact.digest,
            )
            for artifact in projection.artifacts
        )
        return CatalogArtifacts(
            links=(links[0], links[1], links[2], links[3]),
        )

    def _verify_portable_links(
        self,
        item_root: Path,
        projection: PortableKiCadLinkProjection,
    ) -> None:
        expected: set[str] = set()
        for table in (projection.symbol_table, projection.footprint_table):
            path = _path_at(item_root, table.relative_path)
            if (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_size != table.size_bytes
                or _sha256_file(path) != table.digest
            ):
                raise FixturePlanningError(
                    f"portable KiCad table failed byte readback: {table.relative_path}"
                )
            expected.add(table.relative_path)
        table_root = item_root / "Stockroom-Portable-KiCad-Tables"
        actual = {
            path.relative_to(item_root).as_posix()
            for path in table_root.rglob("*")
            if path.is_file()
        }
        if actual != expected:
            raise FixturePlanningError("portable KiCad table staging contains unexpected files")

    def _materialize_portable_links(
        self,
        item_id: str,
        projection: DualEdaProjectionResult,
    ) -> PortableKiCadLinkProjection:
        item_root = self._item_root(item_id)
        attempts = self.staging_root / ".Attempts"
        attempts.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=attempts,
            prefix=f"{item_id}.kicad-links.",
        ) as temporary:
            attempt = Path(temporary)
            result = project_portable_kicad_links((projection,), attempt)
            self._verify_portable_links(attempt, result)
            target = item_root / "Stockroom-Portable-KiCad-Tables"
            if target.exists():
                self._verify_portable_links(item_root, result)
            else:
                os.replace(
                    attempt / "Stockroom-Portable-KiCad-Tables",
                    target,
                )
            self._verify_portable_links(item_root, result)
            return result

    def _cross_document(
        self,
        projection: DualEdaProjectionResult,
        portable_links: PortableKiCadLinkProjection,
    ) -> JsonObject:
        artifacts = self._catalog_artifacts(projection)
        return {
            "artifacts": artifacts.model_dump(mode="json"),
            "canonical_bundle_digest": projection.canonical_bundle_digest,
            "kind": "qualified_cross_eda_verification",
            "limitations": list(projection.limitations),
            "portable_kicad_links": _portable_links_json(portable_links),
            "production_ready": projection.production_ready,
            "schema_version": _SCHEMA_VERSION,
            "semantic_cross_check_passed": projection.semantic_cross_check_passed,
        }

    def _cross_eda_verification(self, context: StageContext) -> CompletionOutcome:
        result = self._projection_from_prior(context.prior_results)
        self._require_prior(
            context,
            StageName.KICAD_BUILD_READBACK,
            self._tool_readback_document(result, "kicad"),
        )
        self._require_prior(
            context,
            StageName.ALTIUM_BUILD_READBACK,
            self._tool_readback_document(result, "altium"),
        )
        self._verify_projection_files(self._item_root(context.item.id), result)
        portable_links = self._materialize_portable_links(context.item.id, result)
        return CompletionOutcome(self._cross_document(result, portable_links))

    def _artifacts_from_prior(
        self,
        item_id: str,
        prior_results: Mapping[StageName, object],
    ) -> CatalogArtifacts:
        raw = prior_results.get(StageName.CROSS_EDA_VERIFICATION)
        document = _exact_keys(
            raw,
            frozenset(
                {
                    "artifacts",
                    "canonical_bundle_digest",
                    "kind",
                    "limitations",
                    "portable_kicad_links",
                    "production_ready",
                    "schema_version",
                    "semantic_cross_check_passed",
                }
            ),
            "cross-EDA result",
        )
        projection = self._projection_from_prior(prior_results)
        portable_links = _portable_links_from_json(document["portable_kicad_links"])
        self._verify_portable_links(self._item_root(item_id), portable_links)
        if _thaw(document) != self._cross_document(projection, portable_links):
            raise FixturePlanningError("cross-EDA durable proof differs")
        try:
            return CatalogArtifacts.model_validate_json(
                canonical_json(_thaw(document["artifacts"]))
            )
        except ValueError as exc:
            raise FixturePlanningError("catalog artifact links do not reconstruct") from exc

    def _catalog_document(
        self,
        item_root: Path,
        projection: CatalogProjection,
    ) -> JsonObject:
        digest_by_path = {
            projection.catalog_path: projection.catalog_sqlite_digest,
            projection.kicad_dbl_path: projection.kicad_dbl_digest,
            projection.altium_dblib_path: projection.altium_dblib_digest,
            projection.catalog_digest_path: projection.catalog_digest_document_digest,
        }
        return {
            "altium_catalog_path": str(projection.altium_catalog_path),
            "catalog_staged_path": _relative_posix(
                item_root,
                projection.catalog_path,
            ),
            "fixture_mode": projection.fixture_mode,
            "kind": "catalog_link_projection",
            "outputs": [
                {
                    "digest": digest_by_path[output.path],
                    "path": _relative_posix(item_root, output.path),
                    "role": output.role.value,
                }
                for output in projection.outputs
            ],
            "revision": projection.revision,
            "row_count": projection.row_count,
            "schema_version": _SCHEMA_VERSION,
            "semantic_digest": projection.semantic_digest,
            "semantic_row_digest": projection.semantic_row_digest,
        }

    def _catalog_link_generation(self, context: StageContext) -> CompletionOutcome:
        bundle, _document = self._bundle_from_prior(context.prior_results)
        artifacts = self._artifacts_from_prior(
            context.item.id,
            context.prior_results,
        )
        item_root = self._item_root(context.item.id)
        projection = stage_catalog_projection(
            bundle,
            artifacts,
            item_root / "Catalog",
            fixture_mode=True,
            altium_catalog_path=self.live_catalog_path,
        )
        return CompletionOutcome(self._catalog_document(item_root, projection))

    def _validated_catalog(
        self,
        item_id: str,
        prior_results: Mapping[StageName, object],
    ) -> CatalogProjection:
        bundle, _document = self._bundle_from_prior(prior_results)
        artifacts = self._artifacts_from_prior(item_id, prior_results)
        item_root = self._item_root(item_id)
        projection = validate_catalog_projection(
            item_root / "Catalog",
            bundle,
            artifacts,
            fixture_mode=True,
            altium_catalog_path=self.live_catalog_path,
        )
        raw = prior_results.get(StageName.CATALOG_LINK_GENERATION)
        if _thaw(raw) != self._catalog_document(item_root, projection):
            raise FixturePlanningError("catalog durable proof differs from readback")
        return projection

    def _prepared_targets(
        self,
        item_id: str,
        prior_results: Mapping[StageName, object],
    ) -> tuple[
        tuple[PreparedTarget, ...],
        tuple[PreparedTarget, ...],
        CatalogProjection,
    ]:
        item_root = self._item_root(item_id)
        bundle, canonical = self._bundle_from_prior(prior_results)
        result = self._projection_from_prior(prior_results)
        self._verify_projection_files(item_root, result)
        catalog = self._validated_catalog(item_id, prior_results)
        cross = _mapping(
            prior_results.get(StageName.CROSS_EDA_VERIFICATION),
            "cross-EDA result",
        )
        portable_links = _portable_links_from_json(cross.get("portable_kicad_links"))
        self._verify_portable_links(item_root, portable_links)

        canonical_path = _string(canonical["path"], "canonical component path")
        canonical_digest = _string(
            canonical["bundle_digest"],
            "canonical component digest",
        )
        if canonical_digest != bundle.canonical_digest():
            raise FixturePlanningError("canonical component digest differs")
        tracked = [
            PreparedTarget(
                target_path=canonical_path,
                sha256=canonical_digest,
            ),
            *(
                PreparedTarget(
                    target_path=artifact.relative_path,
                    sha256=artifact.digest,
                )
                for artifact in result.artifacts
            ),
            PreparedTarget(
                target_path=portable_links.symbol_table.relative_path,
                sha256=portable_links.symbol_table.digest,
            ),
            PreparedTarget(
                target_path=portable_links.footprint_table.relative_path,
                sha256=portable_links.footprint_table.digest,
            ),
        ]
        machine_local: list[PreparedTarget] = []
        digest_by_path = {
            catalog.catalog_path: catalog.catalog_sqlite_digest,
            catalog.kicad_dbl_path: catalog.kicad_dbl_digest,
            catalog.altium_dblib_path: catalog.altium_dblib_digest,
            catalog.catalog_digest_path: catalog.catalog_digest_document_digest,
        }
        for output in catalog.outputs:
            prepared = PreparedTarget(
                target_path=_relative_posix(item_root, output.path),
                sha256=digest_by_path[output.path],
            )
            if output.role is CatalogArtifactRole.TRACKED_PORTABLE:
                tracked.append(prepared)
            elif output.role is CatalogArtifactRole.MACHINE_LOCAL:
                machine_local.append(prepared)
        tracked.sort(key=lambda target: target.target_path.casefold())
        machine_local.sort(key=lambda target: target.target_path.casefold())
        return tuple(tracked), tuple(machine_local), catalog

    def _candidate_digest(
        self,
        bundle: CanonicalPassiveBundle,
        tracked: tuple[PreparedTarget, ...],
        catalog: CatalogProjection,
    ) -> str:
        return _sha256_json(
            {
                "canonical_bundle_digest": bundle.canonical_digest(),
                "catalog_revision": catalog.revision,
                "catalog_semantic_digest": catalog.semantic_digest,
                "component_id": bundle.identity.component_id,
                "fixture_mode": True,
                "schema_version": _SCHEMA_VERSION,
                "tracked_files": [
                    {
                        "path": target.target_path,
                        "sha256": target.sha256,
                    }
                    for target in tracked
                ],
            }
        )

    def _manifest(
        self,
        item_id: str,
        prior_results: Mapping[StageName, object],
        *,
        expected_base_commit: str,
    ) -> PreparedPublicationManifest:
        if not expected_base_commit or not self.repository.has_commit(expected_base_commit):
            raise FixturePlanningError(
                "publication base commit is unavailable in the supplied repository"
            )
        bundle, _canonical = self._bundle_from_prior(prior_results)
        tracked, machine_local, catalog = self._prepared_targets(
            item_id,
            prior_results,
        )
        candidate_digest = self._candidate_digest(bundle, tracked, catalog)
        publication = derive_publication_identity(
            parse_sha256(bundle.identity.identity_digest, "component identity digest"),
            parse_sha256(candidate_digest, "candidate digest"),
        )
        item_root = self._item_root(item_id)
        return PreparedPublicationManifest(
            publication_id=publication.publication_id,
            component_id=bundle.identity.component_id,
            staging_root=item_root,
            tracked_files=tracked,
            machine_local_files=machine_local,
            catalog_staged_path=_relative_posix(item_root, catalog.catalog_path),
            catalog_sha256=catalog.catalog_sqlite_digest,
            catalog_revision=catalog.revision,
            catalog_semantic_digest=catalog.semantic_digest,
            commit_message="Add ON Semiconductor S1M",
        )

    def _publish_proposal(self, context: StageContext) -> PublicationProposalOutcome:
        expected_base_commit = self.repository.head()
        manifest = self._manifest(
            context.item.id,
            context.prior_results,
            expected_base_commit=expected_base_commit,
        )
        bundle, _document = self._bundle_from_prior(context.prior_results)
        tracked, _machine_local, catalog = self._prepared_targets(
            context.item.id,
            context.prior_results,
        )
        return PublicationProposalOutcome(
            candidate_digest=self._candidate_digest(bundle, tracked, catalog),
            manifest_digest=manifest.digest,
            expected_base_commit=expected_base_commit,
        )

    def _completed_stage_results(
        self,
        item_id: str,
    ) -> Mapping[StageName, object]:
        results: dict[StageName, object] = {}
        for stage in self.store.list_stages(item_id):
            if stage.status is StageStatus.COMPLETED and stage.result is not None:
                results[stage.name] = stage.result
        return MappingProxyType(results)

    def _manifest_for_batch(
        self,
        batch_id: str,
        *,
        expected_base_commit: str,
    ) -> PreparedPublicationManifest:
        item = self._one_item(batch_id)
        manifest = self._manifest(
            item.id,
            self._completed_stage_results(item.id),
            expected_base_commit=expected_base_commit,
        )
        membership = self.store.get_publication_membership(item.id)
        if membership is None or membership.publication_id != manifest.publication_id:
            raise FixturePlanningError(
                "durable publication membership differs from reconstructed manifest"
            )
        operation = self.store.get_publication_operation(membership.publication_id)
        if (
            operation.expected_base_commit != expected_base_commit
            or operation.manifest_digest != manifest.digest
        ):
            raise FixturePlanningError(
                "durable publication plan differs from reconstructed manifest"
            )
        return manifest

    def _completed_result(self, batch: BatchRecord) -> FixtureRunResult:
        item = self._one_item(batch.id)
        membership = self.store.get_publication_membership(item.id)
        if membership is None:
            raise FixturePlanningError("completed fixture batch has no publication membership")
        receipt = self.store.get_component_publication_receipt(membership.publication_id)
        if receipt is None:
            raise FixturePlanningError(
                "completed fixture batch has no component publication receipt"
            )
        return FixtureRunResult(
            batch=batch,
            item_id=item.id,
            publication_id=membership.publication_id,
            receipt=receipt,
        )
