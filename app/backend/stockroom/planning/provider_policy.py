"""Executable, deterministic provider policy for the vNext workflow.

This module deliberately does not import the legacy enrichment, importer, or
guided-capture orchestrators.  It binds advertised operations to executable
adapters, filters them through explicit policy/runtime facts, and performs
remaining-set fallback without weakening exact component identity.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from stockroom.workflow.identifiers import authoritative_text
from stockroom.workflow.model import canonical_json

_PROVIDER_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,63}", re.ASCII)
_SEMANTIC_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
_PROVIDER_PLAN_DIGEST_DOMAIN = b"stockroom.provider-plan.v1\0"
_PROVIDER_POLICY_DIGEST_DOMAIN = b"stockroom.provider-policy.v1\0"
_MAX_PROVIDERS = 256
_MAX_REQUESTS = 1_000
_MAX_PROVIDER_CONCURRENCY = 64


class ProviderPolicyError(ValueError):
    """A registry, policy input, or adapter violated the provider contract."""


class ProviderAdapterExecutionError(ProviderPolicyError):
    """An adapter failed outside the sanitized outcome contract."""


class UnexecutableProviderPlan(ProviderPolicyError):
    """One or more required outcomes have no executable eligible provider."""

    def __init__(
        self,
        unmet_operations: tuple[ProviderOperation, ...],
        exclusions: tuple[ProviderExclusion, ...],
    ):
        self.unmet_operations = unmet_operations
        self.exclusions = exclusions
        names = ", ".join(operation.label for operation in unmet_operations)
        super().__init__(f"no executable provider route for: {names}")


class CapabilityKind(StrEnum):
    METADATA = "metadata"
    DATASHEET = "datasheet"
    CAD = "cad"


class EdaTarget(StrEnum):
    KICAD = "kicad"
    ALTIUM = "altium"


class TrustDecision(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    BLOCKED = "blocked"
    UNREVIEWED = "unreviewed"


class LicenseDecision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class AuthenticationState(StrEnum):
    NOT_REQUIRED = "not_required"
    AVAILABLE = "available"
    MISSING = "missing"
    EXPIRED = "expired"
    INVALID = "invalid"


class ProviderHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    CIRCUIT_OPEN = "circuit_open"


class FailureClassification(StrEnum):
    ADAPTER_FAULT = "adapter_fault"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    AUTH_MISSING = "auth_missing"
    AUTH_EXPIRED = "auth_expired"
    AUTH_INVALID = "auth_invalid"
    UNSUPPORTED_FORMAT = "unsupported_format"
    NOT_FOUND_EXACT = "not_found_exact"
    NEAR_MATCH_REJECTED = "near_match_rejected"
    TRUST_BLOCKED = "trust_blocked"
    LICENSE_BLOCKED = "license_blocked"


class AdapterOutcomeStatus(StrEnum):
    SUCCESS = "success"


_ADAPTER_FAILURES = frozenset(
    {
        FailureClassification.UNAVAILABLE,
        FailureClassification.RATE_LIMITED,
        FailureClassification.AUTH_MISSING,
        FailureClassification.AUTH_EXPIRED,
        FailureClassification.AUTH_INVALID,
        FailureClassification.UNSUPPORTED_FORMAT,
        FailureClassification.NOT_FOUND_EXACT,
    }
)


@dataclass(frozen=True, slots=True)
class ExactPartIdentity:
    """Already-authoritative identity; no aliasing or MPN-only query is allowed."""

    authoritative_manufacturer_key: str
    mpn_canonical: str

    def __post_init__(self) -> None:
        authoritative_text(
            self.authoritative_manufacturer_key,
            "authoritative_manufacturer_key",
        )
        authoritative_text(self.mpn_canonical, "mpn_canonical")


@dataclass(frozen=True, slots=True)
class ProviderOperation:
    """One independently executable provider operation."""

    capability: CapabilityKind
    eda_target: EdaTarget | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.capability, CapabilityKind):
            raise TypeError("capability must be CapabilityKind")
        if self.capability is CapabilityKind.CAD:
            if not isinstance(self.eda_target, EdaTarget):
                raise ProviderPolicyError("CAD capability requires an explicit EDA target")
        elif self.eda_target is not None:
            raise ProviderPolicyError("only CAD capability may declare an EDA target")

    @property
    def label(self) -> str:
        if self.eda_target is None:
            return self.capability.value
        return f"{self.capability.value}:{self.eda_target.value}"

    @property
    def sort_key(self) -> tuple[int, int]:
        capability_order = {
            CapabilityKind.METADATA: 0,
            CapabilityKind.DATASHEET: 1,
            CapabilityKind.CAD: 2,
        }
        target_order = {
            None: 0,
            EdaTarget.KICAD: 1,
            EdaTarget.ALTIUM: 2,
        }
        return capability_order[self.capability], target_order[self.eda_target]


METADATA_OPERATION = ProviderOperation(CapabilityKind.METADATA)
DATASHEET_OPERATION = ProviderOperation(CapabilityKind.DATASHEET)
KICAD_CAD_OPERATION = ProviderOperation(CapabilityKind.CAD, EdaTarget.KICAD)
ALTIUM_CAD_OPERATION = ProviderOperation(CapabilityKind.CAD, EdaTarget.ALTIUM)
ORDINARY_COMPONENT_OPERATIONS = (
    METADATA_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    ALTIUM_CAD_OPERATION,
)


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    identity: ExactPartIdentity
    operations: tuple[ProviderOperation, ...] = ORDINARY_COMPONENT_OPERATIONS

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ExactPartIdentity):
            raise TypeError("identity must be ExactPartIdentity")
        if (
            type(self.operations) is not tuple
            or not self.operations
            or any(type(operation) is not ProviderOperation for operation in self.operations)
            or len(set(self.operations)) != len(self.operations)
        ):
            raise ProviderPolicyError("operations must be a non-empty duplicate-free tuple")
        cad_targets = {
            operation.eda_target
            for operation in self.operations
            if operation.capability is CapabilityKind.CAD
        }
        if cad_targets and cad_targets != {EdaTarget.KICAD, EdaTarget.ALTIUM}:
            raise ProviderPolicyError(
                "CAD planning must require both KiCad and Altium executable outcomes"
            )


@dataclass(frozen=True, slots=True)
class ProviderDeclaration:
    """Public, credential-free provider capability declaration."""

    key: str
    adapter_version: str
    operations: tuple[ProviderOperation, ...]
    max_concurrency: int

    def __post_init__(self) -> None:
        if type(self.key) is not str or _PROVIDER_KEY_PATTERN.fullmatch(self.key) is None:
            raise ProviderPolicyError("provider key is not canonical")
        if (
            type(self.adapter_version) is not str
            or not self.adapter_version
            or self.adapter_version != self.adapter_version.strip()
            or any(ord(character) < 32 for character in self.adapter_version)
            or len(self.adapter_version) > 128
        ):
            raise ProviderPolicyError("adapter version is not canonical")
        if (
            type(self.operations) is not tuple
            or not self.operations
            or any(type(operation) is not ProviderOperation for operation in self.operations)
            or len(set(self.operations)) != len(self.operations)
        ):
            raise ProviderPolicyError(
                "advertised operations must be a non-empty duplicate-free tuple"
            )
        if (
            type(self.max_concurrency) is not int
            or not 1 <= self.max_concurrency <= _MAX_PROVIDER_CONCURRENCY
        ):
            raise ProviderPolicyError(
                f"max_concurrency must be between 1 and {_MAX_PROVIDER_CONCURRENCY}"
            )


class ExecutableProviderAdapter(Protocol):
    """Credential-owning behavior kept behind a redacted registration seam."""

    provider_key: str
    executable_operations: frozenset[ProviderOperation]

    def execute(
        self,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
    ) -> AdapterOutcome: ...


@dataclass(frozen=True, slots=True)
class AdapterOutcome:
    """Sanitized provider result; arbitrary provider text never enters the model."""

    status: AdapterOutcomeStatus | FailureClassification
    authoritative_manufacturer_key: str | None = None
    mpn_canonical: str | None = None
    retry_after_seconds: float | None = None
    evidence_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.evidence_digests) is not tuple
            or len(set(self.evidence_digests)) != len(self.evidence_digests)
            or self.evidence_digests != tuple(sorted(self.evidence_digests))
            or any(
                type(digest) is not str or _SEMANTIC_DIGEST_PATTERN.fullmatch(digest) is None
                for digest in self.evidence_digests
            )
        ):
            raise ProviderPolicyError(
                "evidence_digests must be a canonical duplicate-free digest tuple"
            )
        if self.status is AdapterOutcomeStatus.SUCCESS:
            if (
                self.authoritative_manufacturer_key is None
                or self.mpn_canonical is None
                or self.retry_after_seconds is not None
            ):
                raise ProviderPolicyError("successful adapter outcome requires exact identity only")
            authoritative_text(
                self.authoritative_manufacturer_key,
                "authoritative_manufacturer_key",
            )
            authoritative_text(self.mpn_canonical, "mpn_canonical")
            return
        if type(self.status) is not FailureClassification or self.status not in _ADAPTER_FAILURES:
            raise ProviderPolicyError(
                "adapter outcome requires success or an executable failure classification"
            )
        if (
            self.authoritative_manufacturer_key is not None
            or self.mpn_canonical is not None
            or self.evidence_digests
        ):
            raise ProviderPolicyError("failed adapter outcome cannot claim an exact identity")
        if self.retry_after_seconds is not None and (
            self.status is not FailureClassification.RATE_LIMITED
            or isinstance(self.retry_after_seconds, bool)
            or not isinstance(self.retry_after_seconds, (int, float))
            or not math.isfinite(float(self.retry_after_seconds))
            or self.retry_after_seconds <= 0
        ):
            raise ProviderPolicyError("retry_after_seconds is valid only for a positive rate limit")

    @classmethod
    def success(
        cls,
        identity: ExactPartIdentity,
        *,
        evidence_digests: tuple[str, ...] = (),
    ) -> AdapterOutcome:
        return cls(
            AdapterOutcomeStatus.SUCCESS,
            authoritative_manufacturer_key=identity.authoritative_manufacturer_key,
            mpn_canonical=identity.mpn_canonical,
            evidence_digests=evidence_digests,
        )

    @classmethod
    def failure(
        cls,
        status: FailureClassification,
        *,
        retry_after_seconds: float | None = None,
    ) -> AdapterOutcome:
        if type(status) is not FailureClassification or status not in _ADAPTER_FAILURES:
            raise ProviderPolicyError(
                "failure outcome requires an executable failure classification"
            )
        return cls(status, retry_after_seconds=retry_after_seconds)


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    declaration: ProviderDeclaration
    adapter: ExecutableProviderAdapter = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.declaration, ProviderDeclaration):
            raise TypeError("declaration must be ProviderDeclaration")
        execute = getattr(self.adapter, "execute", None)
        adapter_key = getattr(self.adapter, "provider_key", None)
        executable = getattr(self.adapter, "executable_operations", None)
        if (
            not callable(execute)
            or adapter_key != self.declaration.key
            or type(executable) is not frozenset
            or executable != frozenset(self.declaration.operations)
        ):
            raise ProviderPolicyError(
                "every advertised operation requires one matching executable adapter"
            )


@dataclass(frozen=True, slots=True)
class ProviderPolicyInput:
    """Explicit eligibility facts for one provider operation."""

    provider_key: str
    operation: ProviderOperation
    trust: TrustDecision
    license: LicenseDecision
    authentication: AuthenticationState
    health: ProviderHealth
    priority: int

    def __post_init__(self) -> None:
        if (
            type(self.provider_key) is not str
            or _PROVIDER_KEY_PATTERN.fullmatch(self.provider_key) is None
        ):
            raise ProviderPolicyError("provider key is not canonical")
        if type(self.operation) is not ProviderOperation:
            raise TypeError("operation must be ProviderOperation")
        if not isinstance(self.trust, TrustDecision):
            raise TypeError("trust must be TrustDecision")
        if not isinstance(self.license, LicenseDecision):
            raise TypeError("license must be LicenseDecision")
        if not isinstance(self.authentication, AuthenticationState):
            raise TypeError("authentication must be AuthenticationState")
        if not isinstance(self.health, ProviderHealth):
            raise TypeError("health must be ProviderHealth")
        if type(self.priority) is not int or not 0 <= self.priority <= 1_000_000:
            raise ProviderPolicyError("priority must be between 0 and 1000000")


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider_key: str
    adapter_version: str
    operation: ProviderOperation
    max_concurrency: int


@dataclass(frozen=True, slots=True)
class ProviderExclusion:
    provider_key: str
    operation: ProviderOperation
    classification: FailureClassification


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    operation: ProviderOperation
    attempts: tuple[ProviderAttempt, ...]
    exclusions: tuple[ProviderExclusion, ...]


@dataclass(frozen=True, slots=True)
class ProviderPlan:
    identity: ExactPartIdentity
    routes: tuple[ProviderRoute, ...]
    semantic_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.semantic_digest) is not str
            or _SEMANTIC_DIGEST_PATTERN.fullmatch(self.semantic_digest) is None
        ):
            raise ProviderPolicyError("provider plan semantic digest is not canonical")


def _operation_document(operation: ProviderOperation) -> dict[str, str | None]:
    return {
        "capability": operation.capability.value,
        "eda_target": None if operation.eda_target is None else operation.eda_target.value,
    }


def _provider_policy_document(
    registrations: Sequence[ProviderRegistration],
    policies: Sequence[ProviderPolicyInput],
) -> dict[str, object]:
    return {
        "planner_contract_version": 1,
        "policy": [
            {
                "authentication": policy.authentication.value,
                "health": policy.health.value,
                "license": policy.license.value,
                "operation": _operation_document(policy.operation),
                "priority": policy.priority,
                "provider_key": policy.provider_key,
                "trust": policy.trust.value,
            }
            for policy in sorted(
                policies,
                key=lambda value: (
                    value.provider_key,
                    value.operation.sort_key,
                ),
            )
        ],
        "registrations": [
            {
                "adapter_version": registration.declaration.adapter_version,
                "max_concurrency": registration.declaration.max_concurrency,
                "operations": [
                    _operation_document(operation)
                    for operation in sorted(
                        registration.declaration.operations,
                        key=lambda value: value.sort_key,
                    )
                ],
                "provider_key": registration.declaration.key,
            }
            for registration in sorted(
                registrations,
                key=lambda value: (
                    value.declaration.key,
                    value.declaration.adapter_version,
                ),
            )
        ],
    }


def _provider_policy_semantic_digest(
    registrations: Sequence[ProviderRegistration],
    policies: Sequence[ProviderPolicyInput],
) -> str:
    encoded = _PROVIDER_POLICY_DIGEST_DOMAIN + canonical_json(
        _provider_policy_document(registrations, policies)
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _provider_plan_semantic_digest(
    identity: ExactPartIdentity,
    routes: tuple[ProviderRoute, ...],
    registrations: Sequence[ProviderRegistration],
    policies: Sequence[ProviderPolicyInput],
) -> str:
    """Bind one plan to every credential-free execution-relevant input."""

    policy_snapshot = _provider_policy_document(registrations, policies)
    document = {
        "identity": {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        },
        # Preserve the v1 plan document shape while reusing the same complete
        # registry/policy projection for the independent policy checkpoint.
        "planner_contract_version": policy_snapshot["planner_contract_version"],
        "policy": policy_snapshot["policy"],
        "registrations": policy_snapshot["registrations"],
        "routes": [
            {
                "attempts": [
                    {
                        "adapter_version": attempt.adapter_version,
                        "max_concurrency": attempt.max_concurrency,
                        "operation": _operation_document(attempt.operation),
                        "provider_key": attempt.provider_key,
                    }
                    for attempt in route.attempts
                ],
                "exclusions": [
                    {
                        "classification": exclusion.classification.value,
                        "operation": _operation_document(exclusion.operation),
                        "provider_key": exclusion.provider_key,
                    }
                    for exclusion in route.exclusions
                ],
                "operation": _operation_document(route.operation),
            }
            for route in routes
        ],
    }
    encoded = _PROVIDER_PLAN_DIGEST_DOMAIN + canonical_json(document).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ProviderAttemptRecord:
    attempt: ProviderAttempt
    status: AdapterOutcomeStatus | FailureClassification
    retry_after_seconds: float | None = None
    evidence_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    operation: ProviderOperation
    winner: ProviderAttempt | None
    attempts: tuple[ProviderAttemptRecord, ...]

    @property
    def satisfied(self) -> bool:
        return self.winner is not None


@dataclass(frozen=True, slots=True)
class ProviderExecutionReport:
    identity: ExactPartIdentity
    resolutions: tuple[ProviderResolution, ...]

    @property
    def complete(self) -> bool:
        return all(resolution.satisfied for resolution in self.resolutions)

    @property
    def unmet_operations(self) -> tuple[ProviderOperation, ...]:
        return tuple(
            resolution.operation for resolution in self.resolutions if not resolution.satisfied
        )


def _policy_exclusion(policy: ProviderPolicyInput) -> FailureClassification | None:
    if policy.trust in {TrustDecision.BLOCKED, TrustDecision.UNREVIEWED}:
        return FailureClassification.TRUST_BLOCKED
    if policy.license in {LicenseDecision.BLOCKED, LicenseDecision.UNKNOWN}:
        return FailureClassification.LICENSE_BLOCKED
    if policy.authentication is AuthenticationState.MISSING:
        return FailureClassification.AUTH_MISSING
    if policy.authentication is AuthenticationState.EXPIRED:
        return FailureClassification.AUTH_EXPIRED
    if policy.authentication is AuthenticationState.INVALID:
        return FailureClassification.AUTH_INVALID
    if policy.health is ProviderHealth.RATE_LIMITED:
        return FailureClassification.RATE_LIMITED
    if policy.health in {
        ProviderHealth.UNAVAILABLE,
        ProviderHealth.CIRCUIT_OPEN,
    }:
        return FailureClassification.UNAVAILABLE
    return None


def _candidate_sort_key(
    registration: ProviderRegistration,
    policy: ProviderPolicyInput,
) -> tuple[int, int, int, str, str]:
    trust_rank = {
        TrustDecision.PRIMARY: 0,
        TrustDecision.SECONDARY: 1,
        TrustDecision.BLOCKED: 2,
        TrustDecision.UNREVIEWED: 3,
    }
    health_rank = {
        ProviderHealth.HEALTHY: 0,
        ProviderHealth.DEGRADED: 1,
        ProviderHealth.RATE_LIMITED: 2,
        ProviderHealth.UNAVAILABLE: 3,
        ProviderHealth.CIRCUIT_OPEN: 4,
    }
    return (
        policy.priority,
        trust_rank[policy.trust],
        health_rank[policy.health],
        registration.declaration.key,
        registration.declaration.adapter_version,
    )


class ProviderPlanner:
    """Validate, plan, and execute deterministic provider fallback routes.

    ``max_concurrency`` is a scheduler declaration carried in every attempt;
    this narrow executor is deliberately sequential and does not claim to be
    the durable resource governor.
    """

    def __init__(self, registrations: Iterable[ProviderRegistration]):
        values = tuple(registrations)
        if not 1 <= len(values) <= _MAX_PROVIDERS:
            raise ProviderPolicyError(
                f"provider registry must contain between 1 and {_MAX_PROVIDERS} providers"
            )
        if any(type(value) is not ProviderRegistration for value in values):
            raise TypeError("registry entries must be ProviderRegistration values")
        keys = [registration.declaration.key for registration in values]
        if len(keys) != len(set(keys)):
            raise ProviderPolicyError("provider registry contains duplicate keys")
        self._registrations = {
            registration.declaration.key: registration
            for registration in sorted(
                values,
                key=lambda value: (
                    value.declaration.key,
                    value.declaration.adapter_version,
                ),
            )
        }

    @property
    def concurrency_limits(self) -> dict[str, int]:
        """Return declarations a durable scheduler must enforce."""

        return {
            key: registration.declaration.max_concurrency
            for key, registration in self._registrations.items()
        }

    def policy_semantic_digest(
        self,
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> str:
        """Hash the complete credential-free current registry and policy snapshot."""

        policies = self._policy_index(policy_inputs)
        return _provider_policy_semantic_digest(
            tuple(self._registrations.values()),
            tuple(policies.values()),
        )

    def _policy_index(
        self,
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> dict[tuple[str, ProviderOperation], ProviderPolicyInput]:
        policies = tuple(policy_inputs)
        index: dict[tuple[str, ProviderOperation], ProviderPolicyInput] = {}
        for policy in policies:
            if type(policy) is not ProviderPolicyInput:
                raise TypeError("policy inputs must be ProviderPolicyInput values")
            registration = self._registrations.get(policy.provider_key)
            if registration is None or policy.operation not in registration.declaration.operations:
                raise ProviderPolicyError("policy input names an unregistered provider operation")
            key = (policy.provider_key, policy.operation)
            if key in index:
                raise ProviderPolicyError("policy inputs contain a duplicate provider operation")
            index[key] = policy

        expected = {
            (registration.declaration.key, operation)
            for registration in self._registrations.values()
            for operation in registration.declaration.operations
        }
        if set(index) != expected:
            raise ProviderPolicyError(
                "every registered provider operation requires explicit policy input"
            )
        return index

    def _route(
        self,
        operation: ProviderOperation,
        policies: dict[tuple[str, ProviderOperation], ProviderPolicyInput],
    ) -> ProviderRoute:
        eligible: list[tuple[ProviderRegistration, ProviderPolicyInput]] = []
        exclusions: list[ProviderExclusion] = []
        for registration in self._registrations.values():
            if operation not in registration.declaration.operations:
                continue
            policy = policies[(registration.declaration.key, operation)]
            classification = _policy_exclusion(policy)
            if classification is not None:
                exclusions.append(
                    ProviderExclusion(
                        provider_key=registration.declaration.key,
                        operation=operation,
                        classification=classification,
                    )
                )
                continue
            eligible.append((registration, policy))

        eligible.sort(key=lambda value: _candidate_sort_key(*value))
        attempts = tuple(
            ProviderAttempt(
                provider_key=registration.declaration.key,
                adapter_version=registration.declaration.adapter_version,
                operation=operation,
                max_concurrency=registration.declaration.max_concurrency,
            )
            for registration, _policy in eligible
        )
        return ProviderRoute(
            operation=operation,
            attempts=attempts,
            exclusions=tuple(
                sorted(
                    exclusions,
                    key=lambda exclusion: (
                        exclusion.provider_key,
                        exclusion.classification.value,
                    ),
                )
            ),
        )

    def plan(
        self,
        requests: Sequence[ProviderRequest],
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> tuple[ProviderPlan, ...]:
        """Plan one through one thousand requests through the identical code path."""

        planned_requests = tuple(requests)
        if not 1 <= len(planned_requests) <= _MAX_REQUESTS:
            raise ProviderPolicyError(f"planner accepts between 1 and {_MAX_REQUESTS} requests")
        if any(type(request) is not ProviderRequest for request in planned_requests):
            raise TypeError("requests must be ProviderRequest values")
        policies = self._policy_index(policy_inputs)
        required_operations = tuple(
            sorted(
                {operation for request in planned_requests for operation in request.operations},
                key=lambda operation: operation.sort_key,
            )
        )
        routes = {operation: self._route(operation, policies) for operation in required_operations}
        unmet = tuple(
            operation for operation in required_operations if not routes[operation].attempts
        )
        if unmet:
            raise UnexecutableProviderPlan(
                unmet,
                tuple(
                    exclusion for operation in unmet for exclusion in routes[operation].exclusions
                ),
            )
        registrations = tuple(self._registrations.values())
        policy_values = tuple(policies.values())
        plans: list[ProviderPlan] = []
        for request in planned_requests:
            request_routes = tuple(
                routes[operation]
                for operation in sorted(
                    request.operations,
                    key=lambda value: value.sort_key,
                )
            )
            plans.append(
                ProviderPlan(
                    identity=request.identity,
                    routes=request_routes,
                    semantic_digest=_provider_plan_semantic_digest(
                        request.identity,
                        request_routes,
                        registrations,
                        policy_values,
                    ),
                )
            )
        return tuple(plans)

    def validate_plans(
        self,
        plans: Sequence[ProviderPlan],
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> None:
        """Effect-free validation of saved plans against current policy and adapters."""

        saved_plans = tuple(plans)
        if not 1 <= len(saved_plans) <= _MAX_REQUESTS:
            raise ProviderPolicyError(
                f"plan validation accepts between 1 and {_MAX_REQUESTS} plans"
            )
        if any(type(plan) is not ProviderPlan for plan in saved_plans):
            raise TypeError("plans must contain ProviderPlan values")
        policies = self._policy_index(policy_inputs)
        registrations = tuple(self._registrations.values())
        policy_values = tuple(policies.values())
        for registration in registrations:
            self._validate_registration_capability(registration)

        for plan in saved_plans:
            if type(plan.identity) is not ExactPartIdentity:
                raise TypeError("plan identity must be ExactPartIdentity")
            if (
                type(plan.routes) is not tuple
                or not plan.routes
                or any(type(route) is not ProviderRoute for route in plan.routes)
            ):
                raise ProviderPolicyError("saved provider plan requires immutable routes")
            operations = tuple(route.operation for route in plan.routes)
            if (
                any(type(operation) is not ProviderOperation for operation in operations)
                or len(set(operations)) != len(operations)
                or operations != tuple(sorted(operations, key=lambda operation: operation.sort_key))
            ):
                raise ProviderPolicyError(
                    "saved provider plan operations must be unique and canonical"
                )
            cad_targets = {
                operation.eda_target
                for operation in operations
                if operation.capability is CapabilityKind.CAD
            }
            if cad_targets and cad_targets != {EdaTarget.KICAD, EdaTarget.ALTIUM}:
                raise ProviderPolicyError(
                    "saved provider plan must retain both KiCad and Altium CAD routes"
                )
            for route in plan.routes:
                if (
                    type(route.attempts) is not tuple
                    or not route.attempts
                    or any(type(attempt) is not ProviderAttempt for attempt in route.attempts)
                    or any(attempt.operation != route.operation for attempt in route.attempts)
                    or len({attempt.provider_key for attempt in route.attempts})
                    != len(route.attempts)
                    or type(route.exclusions) is not tuple
                    or any(
                        type(exclusion) is not ProviderExclusion
                        or exclusion.operation != route.operation
                        for exclusion in route.exclusions
                    )
                    or len({exclusion.provider_key for exclusion in route.exclusions})
                    != len(route.exclusions)
                ):
                    raise ProviderPolicyError("saved provider route is not canonical")

            expected_routes = tuple(self._route(operation, policies) for operation in operations)
            if plan.routes != expected_routes:
                raise ProviderPolicyError(
                    "saved provider plan no longer matches current policy or registry"
                )
            expected_digest = _provider_plan_semantic_digest(
                plan.identity,
                expected_routes,
                registrations,
                policy_values,
            )
            if plan.semantic_digest != expected_digest:
                raise ProviderPolicyError(
                    "saved provider plan semantic digest does not match current policy or registry"
                )

    def execute(
        self,
        plan: ProviderPlan,
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> ProviderExecutionReport:
        if type(plan) is not ProviderPlan:
            raise TypeError("plan must be ProviderPlan")
        self.validate_plans((plan,), policy_inputs)
        resolutions: list[ProviderResolution] = []
        for route in plan.routes:
            records: list[ProviderAttemptRecord] = []
            winner: ProviderAttempt | None = None
            for attempt in route.attempts:
                record = self.execute_attempt(plan.identity, attempt)
                records.append(record)
                if record.status is AdapterOutcomeStatus.SUCCESS:
                    winner = attempt
                    break
            resolutions.append(
                ProviderResolution(
                    operation=route.operation,
                    winner=winner,
                    attempts=tuple(records),
                )
            )
        return ProviderExecutionReport(
            identity=plan.identity,
            resolutions=tuple(resolutions),
        )

    @staticmethod
    def _validate_registration_capability(
        registration: ProviderRegistration,
    ) -> None:
        adapter = registration.adapter
        try:
            adapter_key = getattr(adapter, "provider_key", None)
            executable_operations = getattr(adapter, "executable_operations", None)
            execute = getattr(adapter, "execute", None)
        except Exception:
            raise ProviderPolicyError(
                "provider adapter capability changed after plan validation"
            ) from None
        if (
            adapter_key != registration.declaration.key
            or type(executable_operations) is not frozenset
            or executable_operations != frozenset(registration.declaration.operations)
            or not callable(execute)
        ):
            raise ProviderPolicyError("provider adapter capability changed after plan validation")

    def _validated_registration(
        self,
        attempt: ProviderAttempt,
    ) -> ProviderRegistration:
        if type(attempt) is not ProviderAttempt:
            raise TypeError("attempt must be ProviderAttempt")
        registration = self._registrations.get(attempt.provider_key)
        if (
            registration is None
            or attempt.operation not in registration.declaration.operations
            or attempt.adapter_version != registration.declaration.adapter_version
            or attempt.max_concurrency != registration.declaration.max_concurrency
        ):
            raise ProviderPolicyError("provider plan no longer matches its executable registry")
        self._validate_registration_capability(registration)
        return registration

    def validate_attempt(self, attempt: ProviderAttempt) -> None:
        """Validate current registry and callable capability without invoking an adapter."""

        self._validated_registration(attempt)

    def execute_attempt(
        self,
        identity: ExactPartIdentity,
        attempt: ProviderAttempt,
    ) -> ProviderAttemptRecord:
        """Invoke one validated adapter without exposing its raw exception surface."""

        if type(identity) is not ExactPartIdentity:
            raise TypeError("identity must be ExactPartIdentity")
        registration = self._validated_registration(attempt)
        adapter = registration.adapter
        try:
            outcome = adapter.execute(
                identity,
                attempt.operation,
            )
        except Exception:
            raise ProviderAdapterExecutionError(
                "provider adapter raised outside its sanitized outcome contract"
            ) from None
        if type(outcome) is not AdapterOutcome:
            raise ProviderAdapterExecutionError("provider adapter returned an unsanitized outcome")
        if outcome.status is AdapterOutcomeStatus.SUCCESS:
            if (
                outcome.authoritative_manufacturer_key != identity.authoritative_manufacturer_key
                or outcome.mpn_canonical != identity.mpn_canonical
            ):
                return ProviderAttemptRecord(
                    attempt,
                    FailureClassification.NEAR_MATCH_REJECTED,
                )
            return ProviderAttemptRecord(
                attempt,
                AdapterOutcomeStatus.SUCCESS,
                evidence_digests=outcome.evidence_digests,
            )
        return ProviderAttemptRecord(
            attempt,
            outcome.status,
            retry_after_seconds=outcome.retry_after_seconds,
        )


__all__ = [
    "ALTIUM_CAD_OPERATION",
    "AdapterOutcome",
    "AdapterOutcomeStatus",
    "AuthenticationState",
    "CapabilityKind",
    "DATASHEET_OPERATION",
    "EdaTarget",
    "ExactPartIdentity",
    "ExecutableProviderAdapter",
    "FailureClassification",
    "KICAD_CAD_OPERATION",
    "LicenseDecision",
    "METADATA_OPERATION",
    "ORDINARY_COMPONENT_OPERATIONS",
    "ProviderAttempt",
    "ProviderAttemptRecord",
    "ProviderAdapterExecutionError",
    "ProviderDeclaration",
    "ProviderExecutionReport",
    "ProviderExclusion",
    "ProviderHealth",
    "ProviderOperation",
    "ProviderPlan",
    "ProviderPlanner",
    "ProviderPolicyError",
    "ProviderPolicyInput",
    "ProviderRegistration",
    "ProviderRequest",
    "ProviderResolution",
    "ProviderRoute",
    "TrustDecision",
    "UnexecutableProviderPlan",
]
