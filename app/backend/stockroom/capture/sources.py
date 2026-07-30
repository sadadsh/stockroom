"""Fail-closed non-browser CAD acquisition sources.

This module contains no catalogue resolver and no provider URL constants.  A caller may
construct a :class:`DirectCadOffer` only after an existing, policy-admitted provider route has
resolved an exact manufacturer and MPN to explicit HTTPS downloads.  Downloaded bytes still pass
through Stockroom's normal immutable-evidence, ingest, native-readback, and atomic-attach path;
the source accepts activation only when that path returns a reverified same-manifest dual-EDA
record.  Anything less is retained as supplementary evidence and never projected.

Deterministic generation is equally narrow.  It is enabled only for exact identities listed in
``GenerationQualification`` records, from explicitly supported part classes and profiles, with
network manufacturer evidence that a caller can reverify in the evidence store.  There is no
local-file, upload, LCSC, EasyEDA, or arbitrary-MPN entry point.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from stockroom.capture.complete import (
    ProviderOutcomeStatus,
    SourceOutcome,
    provider_outcome_from_source,
    sanitize_provider_reason,
)
from stockroom.capture.download_broker import DownloadBroker, DownloadReceipt, DownloadTask
from stockroom.capture.evidence import exact_identity
from stockroom.capture.requirements import Requirement, capture_needs
from stockroom.domain.canonical import AuthoritativeEvidence
from stockroom.model.part_class import PartClass, parse_part_class
from stockroom.planning import ExactPartIdentity

DIRECT_SOURCE_ADAPTER_VERSION = "direct-network-cad-v1"
GENERATOR_SOURCE_ADAPTER_VERSION = "qualified-dual-eda-generator-v1"

COHERENT_DUAL_EDA_REQUIREMENTS = (
    Requirement.KICAD_SYMBOL,
    Requirement.KICAD_FOOTPRINT,
    Requirement.KICAD_MODEL,
    Requirement.ALTIUM_SYMBOL,
    Requirement.ALTIUM_FOOTPRINT,
)

_COHERENT_REQUIREMENT_SET = frozenset(COHERENT_DUAL_EDA_REQUIREMENTS)
_CANONICAL_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_NETWORK_GENERATION_EVIDENCE = frozenset(
    {"manufacturer_datasheet", "manufacturer_catalog"}
)
_MAX_DIRECT_DOWNLOADS = 16


def _canonical_key(value: object, label: str) -> str:
    if type(value) is not str or _CANONICAL_KEY.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical key")
    return value


def _https_url(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be canonical non-empty text")
    parsed = urlparse(value)
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{label} must be an HTTPS URL without embedded credentials")
    return value


def _safe_error(exc: BaseException) -> str:
    detail = sanitize_provider_reason(exc)
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


@dataclass(frozen=True, slots=True)
class DirectCadDownload:
    """One network file in an exact direct-CAD offer.

    The object deliberately has no path field.  Bytes can enter only through the task-bound
    :class:`DownloadBroker`, and the suggested name is a leaf name rather than a destination.
    """

    url: str
    suggested_filename: str

    def __post_init__(self) -> None:
        _https_url(self.url, "direct CAD download URL")
        name = self.suggested_filename
        if (
            type(name) is not str
            or not name
            or name != name.strip()
            or Path(name).name != name
            or len(name) > 255
        ):
            raise ValueError("direct CAD suggested filename must be one portable leaf name")


@dataclass(frozen=True, slots=True)
class DirectCadOffer:
    """An immutable, exact-identity set of HTTPS downloads from one admitted route."""

    identity: ExactPartIdentity
    provider_key: str
    author_key: str
    detail_url: str
    downloads: tuple[DirectCadDownload, ...]

    def __post_init__(self) -> None:
        if type(self.identity) is not ExactPartIdentity:
            raise TypeError("direct CAD offer identity must be ExactPartIdentity")
        _canonical_key(self.provider_key, "direct CAD provider key")
        _canonical_key(self.author_key, "direct CAD author key")
        _https_url(self.detail_url, "direct CAD detail URL")
        if (
            type(self.downloads) is not tuple
            or not 1 <= len(self.downloads) <= _MAX_DIRECT_DOWNLOADS
            or any(type(item) is not DirectCadDownload for item in self.downloads)
        ):
            raise ValueError(
                f"direct CAD offer must contain 1 to {_MAX_DIRECT_DOWNLOADS} downloads"
            )
        urls = [item.url for item in self.downloads]
        names = [item.suggested_filename.casefold() for item in self.downloads]
        if len(set(urls)) != len(urls) or len(set(names)) != len(names):
            raise ValueError("direct CAD offer downloads must have unique URLs and filenames")

    @property
    def route_id(self) -> str:
        return f"{self.provider_key}:{self.author_key}"


@dataclass(frozen=True, slots=True)
class CoherentCadActivation:
    """One evidence-bound atomic activation returned by an ingest or generator adapter."""

    identity: ExactPartIdentity
    manifest_digest: str
    updated_record: object

    def __post_init__(self) -> None:
        if type(self.identity) is not ExactPartIdentity:
            raise TypeError("CAD activation identity must be ExactPartIdentity")
        if type(self.manifest_digest) is not str or _DIGEST.fullmatch(
            self.manifest_digest
        ) is None:
            raise ValueError("CAD activation manifest digest must be canonical SHA-256")
        if self.updated_record is None:
            raise ValueError("CAD activation must carry the atomically updated record")


@dataclass(frozen=True, slots=True)
class CadIngestDecline:
    """Why inspected or generated bytes could not form one coherent active pair."""

    reason: str

    def __post_init__(self) -> None:
        reason = sanitize_provider_reason(self.reason)
        if not reason:
            raise ValueError("CAD ingest decline reason must be non-empty")
        object.__setattr__(self, "reason", reason)


class DirectOfferResolver(Protocol):
    """Resolve one already-admitted route without opening a commercial browser."""

    def __call__(
        self,
        record: object,
        identity: ExactPartIdentity,
        /,
    ) -> DirectCadOffer | None: ...


class DirectCadIngestor(Protocol):
    """Inspect, evidence, cross-verify, and atomically attach one direct download set."""

    def __call__(
        self,
        record: object,
        offer: DirectCadOffer,
        receipts: tuple[DownloadReceipt, ...],
        /,
    ) -> CoherentCadActivation | CadIngestDecline: ...


class SupplementaryEvidenceStore(Protocol):
    def record_supplementary_artifacts(
        self,
        *,
        identity: ExactPartIdentity,
        surface_key: str,
        provider_key: str,
        adapter_version: str,
        receipts: tuple[DownloadReceipt, ...],
    ) -> str: ...


class ActivationVerifier(Protocol):
    """Reverify the active pointers and exact manifest after an atomic attach."""

    def __call__(self, record: object, manifest_digest: str, /) -> bool: ...


class DownloadBrokerFactory(Protocol):
    def __call__(self, task: DownloadTask, /) -> DownloadBroker: ...


class BrokeredDirectSource:
    """Download one policy-admitted direct route and activate only a coherent dual-EDA set."""

    key = "direct-network"
    name = "direct-network"

    def __init__(
        self,
        *,
        provider_key: str,
        author_key: str,
        report_label: str,
        admitted_route_ids: frozenset[str],
        staging_root: Path,
        resolve_offer: DirectOfferResolver,
        ingest: DirectCadIngestor,
        evidence_store: SupplementaryEvidenceStore,
        verify_activation: ActivationVerifier,
        broker_factory: DownloadBrokerFactory = DownloadBroker,
        task_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.provider_key = _canonical_key(provider_key, "direct source provider key")
        self.author_key = _canonical_key(author_key, "direct source author key")
        self.report_label = sanitize_provider_reason(report_label)
        if not self.report_label:
            raise ValueError("direct source report label must be non-empty")
        route_id = f"{self.provider_key}:{self.author_key}"
        if (
            type(admitted_route_ids) is not frozenset
            or any(
                type(item) is not str
                or ":" not in item
                or any(
                    _CANONICAL_KEY.fullmatch(part) is None
                    for part in item.split(":", maxsplit=1)
                )
                for item in admitted_route_ids
            )
        ):
            raise ValueError("admitted direct routes must be canonical immutable route IDs")
        if route_id not in admitted_route_ids:
            raise ValueError(f"direct route {route_id!r} is not policy-admitted")

        root = Path(staging_root)
        if not root.is_dir() or root.is_symlink():
            raise ValueError("direct download staging root must be an existing non-linked directory")
        for name, callback in (
            ("offer resolver", resolve_offer),
            ("CAD ingestor", ingest),
            ("activation verifier", verify_activation),
            ("download broker factory", broker_factory),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")
        if not callable(getattr(evidence_store, "record_supplementary_artifacts", None)):
            raise TypeError("direct source requires an immutable supplementary evidence store")

        self._route_id = route_id
        self._staging_root = root.resolve(strict=True)
        self._resolve_offer = resolve_offer
        self._ingest = ingest
        self._evidence_store = evidence_store
        self._verify_activation = verify_activation
        self._broker_factory = broker_factory
        self._task_id_factory = task_id_factory or (
            lambda: f"direct-{uuid.uuid4().hex}"
        )

    def provider_route_ids(self) -> tuple[str, ...]:
        return (self._route_id,)

    def provides(self) -> frozenset[Requirement]:
        return _COHERENT_REQUIREMENT_SET

    def _finish(
        self,
        outcome: SourceOutcome,
        *,
        attempted: bool = True,
        status: ProviderOutcomeStatus | None = None,
    ) -> SourceOutcome:
        provider_outcome = provider_outcome_from_source(
            outcome,
            provider_key=self.provider_key,
            author_key=self.author_key,
            label=self.report_label,
            attempted=attempted,
            status=status,
        )
        return SourceOutcome(
            satisfied=outcome.satisfied,
            retained=outcome.retained,
            error=outcome.error,
            skipped=outcome.skipped,
            blocked=outcome.blocked,
            provider_outcomes=(provider_outcome,),
        )

    def _retain(
        self,
        identity: ExactPartIdentity,
        receipts: tuple[DownloadReceipt, ...],
        reason: str,
        *,
        error: bool,
    ) -> SourceOutcome:
        safe_reason = sanitize_provider_reason(reason)
        if not receipts:
            return self._finish(SourceOutcome(error=safe_reason) if error else SourceOutcome(
                skipped=safe_reason
            ))
        try:
            self._evidence_store.record_supplementary_artifacts(
                identity=identity,
                surface_key=self.provider_key,
                provider_key=self.author_key,
                adapter_version=DIRECT_SOURCE_ADAPTER_VERSION,
                receipts=receipts,
            )
        except Exception as exc:  # noqa: BLE001 - retention must never be rounded up
            detail = f"{safe_reason}; supplementary evidence retention failed ({_safe_error(exc)})"
            return self._finish(SourceOutcome(error=detail))
        count = len(receipts)
        noun = "file" if count == 1 else "files"
        retained_detail = (
            f"{safe_reason}; retained {count} exact supplementary {noun}; "
            "no incomplete CAD bundle was activated"
        )
        if error:
            return self._finish(SourceOutcome(retained=count, error=retained_detail))
        return self._finish(SourceOutcome(retained=count, skipped=retained_detail))

    def _receipt_issue(
        self,
        receipt: DownloadReceipt,
        *,
        task: DownloadTask,
    ) -> str:
        if type(receipt) is not DownloadReceipt:
            return "direct download broker returned an invalid receipt"
        if (
            receipt.task_id != task.task_id
            or receipt.manufacturer_key != task.manufacturer_key
            or receipt.mpn_canonical != task.mpn_canonical
            or receipt.surface_key != self.provider_key
            or receipt.evidence_provider_key != self.author_key
        ):
            return "direct download receipt escaped its exact task or provider route"
        path = receipt.path
        if not path.is_file() or path.is_symlink():
            return "direct download receipt does not point at one staged regular file"
        try:
            path.resolve(strict=True).relative_to(self._staging_root)
        except ValueError:
            return "direct download receipt escaped the source staging root"
        return ""

    def _activation_issue(
        self,
        activation: CoherentCadActivation,
        *,
        identity: ExactPartIdentity,
        part_class: PartClass,
    ) -> str:
        if type(activation) is not CoherentCadActivation:
            return "direct CAD ingestor returned an unsupported result"
        if activation.identity != identity:
            return "direct CAD activation identity does not match the offer"
        try:
            updated_identity = exact_identity(activation.updated_record)
            updated_class = parse_part_class(
                getattr(activation.updated_record, "part_class", None)
            )
            remaining = set(capture_needs(activation.updated_record))
        except Exception as exc:  # noqa: BLE001 - malformed output is never an activation
            return f"direct CAD activation record is invalid ({_safe_error(exc)})"
        if updated_identity != identity or updated_class is not part_class:
            return "direct CAD activation changed the part identity or class"
        missing = remaining & _COHERENT_REQUIREMENT_SET
        if missing:
            labels = ", ".join(sorted(item.value for item in missing))
            return f"direct CAD activation is incomplete: {labels}"
        try:
            verified = self._verify_activation(
                activation.updated_record,
                activation.manifest_digest,
            )
        except Exception as exc:  # noqa: BLE001 - a verifier failure is not success
            return f"direct CAD activation revalidation failed ({_safe_error(exc)})"
        if verified is not True:
            return "direct CAD activation was not reverified from its exact evidence manifest"
        return ""

    def supply(self, record: object) -> SourceOutcome:
        try:
            identity = exact_identity(record)
            part_class = parse_part_class(getattr(record, "part_class", None))
        except (TypeError, ValueError) as exc:
            return self._finish(
                SourceOutcome(skipped=_safe_error(exc)),
                attempted=False,
                status="not-attempted",
            )
        if part_class is not PartClass.COMPONENT:
            return self._finish(
                SourceOutcome(
                    skipped="direct dual-EDA CAD applies only to the component part class"
                ),
                attempted=False,
                status="not-attempted",
            )

        try:
            offer = self._resolve_offer(record, identity)
        except Exception as exc:  # noqa: BLE001 - resolver failure is one route failure
            return self._finish(
                SourceOutcome(error=f"direct CAD offer resolution failed ({_safe_error(exc)})")
            )
        if offer is None:
            return self._finish(
                SourceOutcome(skipped="no admitted exact direct-CAD offer is available")
            )
        if type(offer) is not DirectCadOffer:
            return self._finish(SourceOutcome(error="direct CAD resolver returned an invalid offer"))
        if offer.identity != identity:
            return self._finish(
                SourceOutcome(error="direct CAD offer identity does not match the requested part")
            )
        if offer.route_id != self._route_id:
            return self._finish(
                SourceOutcome(error="direct CAD offer does not belong to this admitted route")
            )

        try:
            task = DownloadTask(
                task_id=self._task_id_factory(),
                manufacturer_key=identity.authoritative_manufacturer_key,
                mpn_canonical=identity.mpn_canonical,
                staging_root=self._staging_root,
                surface_key=self.provider_key,
                evidence_provider_key=self.author_key,
            )
            broker = self._broker_factory(task)
        except Exception as exc:  # noqa: BLE001 - source construction is one route failure
            return self._finish(
                SourceOutcome(error=f"direct download task could not start ({_safe_error(exc)})")
            )

        receipts: list[DownloadReceipt] = []
        for download in offer.downloads:
            try:
                receipt = broker.download_http(
                    download.url,
                    suggested_filename=download.suggested_filename,
                )
            except Exception as exc:  # noqa: BLE001 - keep any earlier exact bytes
                return self._retain(
                    identity,
                    tuple(receipts),
                    f"direct HTTPS download failed ({_safe_error(exc)})",
                    error=True,
                )
            issue = self._receipt_issue(receipt, task=task)
            if issue:
                return self._retain(
                    identity,
                    tuple(receipts),
                    issue,
                    error=True,
                )
            receipts.append(receipt)

        landed = tuple(receipts)
        try:
            result = self._ingest(record, offer, landed)
        except Exception as exc:  # noqa: BLE001 - exact bytes remain useful supplementary evidence
            return self._retain(
                identity,
                landed,
                f"direct CAD ingest failed ({_safe_error(exc)})",
                error=True,
            )
        if type(result) is CadIngestDecline:
            return self._retain(identity, landed, result.reason, error=False)
        if type(result) is not CoherentCadActivation:
            return self._retain(
                identity,
                landed,
                "direct CAD ingestor returned an unsupported result",
                error=True,
            )
        issue = self._activation_issue(result, identity=identity, part_class=part_class)
        if issue:
            return self._retain(identity, landed, issue, error=True)
        return self._finish(SourceOutcome(satisfied=COHERENT_DUAL_EDA_REQUIREMENTS))


@dataclass(frozen=True, slots=True)
class GenerationQualification:
    """One exact part admitted to one deterministic generator profile.

    Evidence is the existing immutable canonical evidence model.  Fixtures are intentionally
    rejected here: production generation may be selected only from a network manufacturer
    datasheet or catalogue whose digest the caller can prove exists.
    """

    identity: ExactPartIdentity
    part_class: PartClass
    profile_key: str
    evidence: tuple[AuthoritativeEvidence, ...]

    def __post_init__(self) -> None:
        if type(self.identity) is not ExactPartIdentity:
            raise TypeError("generation qualification identity must be ExactPartIdentity")
        if type(self.part_class) is not PartClass:
            raise TypeError("generation qualification part_class must be PartClass")
        _canonical_key(self.profile_key, "generation profile key")
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(type(item) is not AuthoritativeEvidence for item in self.evidence)
        ):
            raise ValueError("generation qualification requires immutable authoritative evidence")
        for item in self.evidence:
            if item.source_kind not in _NETWORK_GENERATION_EVIDENCE:
                raise ValueError(
                    "generation qualification accepts only network manufacturer evidence"
                )
            _https_url(item.source_locator, "generation evidence locator")
        digests = [item.content_digest for item in self.evidence]
        if len(set(digests)) != len(digests):
            raise ValueError("generation qualification evidence digests must be unique")


class QualifiedCadGenerator(Protocol):
    def __call__(
        self,
        record: object,
        qualification: GenerationQualification,
        /,
    ) -> CoherentCadActivation | CadIngestDecline: ...


class GenerationEvidenceVerifier(Protocol):
    def __call__(self, evidence: AuthoritativeEvidence, /) -> bool: ...


class QualifiedDualEdaGeneratorSource:
    """Generate only explicitly qualified exact identities, then reverify the active pair."""

    key = "deterministic-generation"
    name = "deterministic-generation"
    report_label = "Qualified Deterministic Generation"
    provider_key = "deterministic-generation"
    author_key = "deterministic-generation"

    def __init__(
        self,
        *,
        qualifications: tuple[GenerationQualification, ...],
        supported_part_classes: frozenset[PartClass],
        supported_profiles: frozenset[str],
        supported_evidence_classes: frozenset[str],
        verify_evidence: GenerationEvidenceVerifier,
        generate: QualifiedCadGenerator,
        verify_activation: ActivationVerifier,
    ) -> None:
        if (
            type(qualifications) is not tuple
            or any(type(item) is not GenerationQualification for item in qualifications)
        ):
            raise TypeError("generator qualifications must be an immutable tuple")
        if (
            type(supported_part_classes) is not frozenset
            or not supported_part_classes
            or any(type(item) is not PartClass for item in supported_part_classes)
        ):
            raise ValueError("generator must explicitly support at least one PartClass")
        if (
            type(supported_profiles) is not frozenset
            or not supported_profiles
            or any(
                type(item) is not str or _CANONICAL_KEY.fullmatch(item) is None
                for item in supported_profiles
            )
        ):
            raise ValueError("generator must explicitly support canonical profile keys")
        if (
            type(supported_evidence_classes) is not frozenset
            or not supported_evidence_classes
            or not supported_evidence_classes <= _NETWORK_GENERATION_EVIDENCE
        ):
            raise ValueError(
                "generator evidence support must be an explicit non-empty network subset"
            )
        for name, callback in (
            ("generation evidence verifier", verify_evidence),
            ("qualified CAD generator", generate),
            ("generation activation verifier", verify_activation),
        ):
            if not callable(callback):
                raise TypeError(f"{name} must be callable")

        by_identity: dict[ExactPartIdentity, GenerationQualification] = {}
        for qualification in qualifications:
            if qualification.identity in by_identity:
                raise ValueError("generator has duplicate qualifications for one exact identity")
            if qualification.part_class not in supported_part_classes:
                raise ValueError("generation qualification uses an unsupported part class")
            if qualification.profile_key not in supported_profiles:
                raise ValueError("generation qualification uses an unsupported profile")
            evidence_classes = {item.source_kind for item in qualification.evidence}
            if not evidence_classes <= supported_evidence_classes:
                raise ValueError("generation qualification uses an unsupported evidence class")
            by_identity[qualification.identity] = qualification

        self._qualifications = by_identity
        self._verify_evidence = verify_evidence
        self._generate = generate
        self._verify_activation = verify_activation

    def provider_route_ids(self) -> tuple[str, ...]:
        return (f"{self.provider_key}:{self.author_key}",)

    def provides(self) -> frozenset[Requirement]:
        return _COHERENT_REQUIREMENT_SET

    def _finish(
        self,
        outcome: SourceOutcome,
        *,
        attempted: bool = True,
        status: ProviderOutcomeStatus | None = None,
    ) -> SourceOutcome:
        provider_outcome = provider_outcome_from_source(
            outcome,
            provider_key=self.provider_key,
            author_key=self.author_key,
            label=self.report_label,
            attempted=attempted,
            status=status,
        )
        return SourceOutcome(
            satisfied=outcome.satisfied,
            retained=outcome.retained,
            error=outcome.error,
            skipped=outcome.skipped,
            blocked=outcome.blocked,
            provider_outcomes=(provider_outcome,),
        )

    def supply(self, record: object) -> SourceOutcome:
        try:
            identity = exact_identity(record)
            part_class = parse_part_class(getattr(record, "part_class", None))
        except (TypeError, ValueError) as exc:
            return self._finish(
                SourceOutcome(skipped=_safe_error(exc)),
                attempted=False,
                status="not-attempted",
            )
        qualification = self._qualifications.get(identity)
        if qualification is None:
            return self._finish(
                SourceOutcome(
                    skipped="this exact identity has no qualified deterministic generator profile"
                ),
                attempted=False,
                status="not-attempted",
            )
        if qualification.part_class is not part_class:
            return self._finish(
                SourceOutcome(
                    error="generation qualification no longer matches the record part class"
                )
            )

        for evidence in qualification.evidence:
            try:
                verified = self._verify_evidence(evidence)
            except Exception as exc:  # noqa: BLE001 - evidence failure cannot start generation
                return self._finish(
                    SourceOutcome(
                        error=f"generation evidence revalidation failed ({_safe_error(exc)})"
                    )
                )
            if verified is not True:
                return self._finish(
                    SourceOutcome(
                        error=(
                            "generation evidence is not present and digest-verified in the "
                            "immutable store"
                        )
                    )
                )

        try:
            result = self._generate(record, qualification)
        except Exception as exc:  # noqa: BLE001 - unsupported/native failures remain one row
            return self._finish(
                SourceOutcome(error=f"qualified CAD generation failed ({_safe_error(exc)})")
            )
        if type(result) is CadIngestDecline:
            return self._finish(SourceOutcome(skipped=result.reason))
        if type(result) is not CoherentCadActivation:
            return self._finish(
                SourceOutcome(error="qualified CAD generator returned an unsupported result")
            )
        issue = _qualified_activation_issue(
            result,
            identity=identity,
            part_class=part_class,
            verify_activation=self._verify_activation,
        )
        if issue:
            return self._finish(SourceOutcome(error=issue))
        return self._finish(SourceOutcome(satisfied=COHERENT_DUAL_EDA_REQUIREMENTS))


def _qualified_activation_issue(
    activation: CoherentCadActivation,
    *,
    identity: ExactPartIdentity,
    part_class: PartClass,
    verify_activation: ActivationVerifier,
) -> str:
    if activation.identity != identity:
        return "generated CAD activation identity does not match its qualification"
    try:
        updated_identity = exact_identity(activation.updated_record)
        updated_class = parse_part_class(getattr(activation.updated_record, "part_class", None))
        remaining = set(capture_needs(activation.updated_record))
    except Exception as exc:  # noqa: BLE001 - malformed generated output is never success
        return f"generated CAD activation record is invalid ({_safe_error(exc)})"
    if updated_identity != identity or updated_class is not part_class:
        return "generated CAD activation changed the qualified identity or part class"
    missing = remaining & _COHERENT_REQUIREMENT_SET
    if missing:
        labels = ", ".join(sorted(item.value for item in missing))
        return f"generated CAD activation is incomplete: {labels}"
    try:
        verified = verify_activation(activation.updated_record, activation.manifest_digest)
    except Exception as exc:  # noqa: BLE001 - verifier failure cannot be success
        return f"generated CAD activation revalidation failed ({_safe_error(exc)})"
    if verified is not True:
        return "generated CAD activation was not reverified from its exact evidence manifest"
    return ""


__all__ = [
    "COHERENT_DUAL_EDA_REQUIREMENTS",
    "DIRECT_SOURCE_ADAPTER_VERSION",
    "GENERATOR_SOURCE_ADAPTER_VERSION",
    "ActivationVerifier",
    "BrokeredDirectSource",
    "CadIngestDecline",
    "CoherentCadActivation",
    "DirectCadDownload",
    "DirectCadIngestor",
    "DirectCadOffer",
    "DirectOfferResolver",
    "GenerationEvidenceVerifier",
    "GenerationQualification",
    "QualifiedCadGenerator",
    "QualifiedDualEdaGeneratorSource",
    "SupplementaryEvidenceStore",
]
