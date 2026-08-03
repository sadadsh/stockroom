"""Strict JSON workflow handlers for provider-backed acquisition stages.

The seam deliberately owns no queue, workflow persistence, credentials, or
provider transport.  It translates one exact identity and the existing
provider planner/runtime into ordinary durable workflow outcomes.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from stockroom.workflow import (
    CompletionOutcome,
    DecisionKind,
    DecisionOutcome,
    PermanentFailureOutcome,
    RetryOutcome,
    StageContext,
    StageHandler,
    StageHandlerRegistry,
    StageName,
    StageOutcome,
)
from stockroom.workflow.model import canonical_json

from .provider_policy import (
    ALTIUM_CAD_OPERATION,
    DATASHEET_OPERATION,
    KICAD_CAD_OPERATION,
    METADATA_OPERATION,
    AdapterOutcomeStatus,
    AuthenticationState,
    ExactPartIdentity,
    FailureClassification,
    LicenseDecision,
    ProviderExclusion,
    ProviderHealth,
    ProviderOperation,
    ProviderPlanner,
    ProviderPolicyInput,
    ProviderRequest,
    TrustDecision,
    UnexecutableProviderPlan,
)
from .provider_runtime import (
    ProviderExecutionReceipt,
    ProviderExecutionRuntime,
    ProviderSelectionReceipt,
)

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}", re.ASCII)
_SCHEMA_VERSION = 1

PROVIDER_WORKFLOW_STAGES = (
    StageName.METADATA,
    StageName.DATASHEET,
    StageName.CAD_ACQUISITION,
)

_STAGE_OPERATIONS: Mapping[StageName, tuple[ProviderOperation, ...]] = MappingProxyType(
    {
        StageName.METADATA: (METADATA_OPERATION,),
        StageName.DATASHEET: (DATASHEET_OPERATION,),
        StageName.CAD_ACQUISITION: (
            KICAD_CAD_OPERATION,
            ALTIUM_CAD_OPERATION,
        ),
    }
)

_RETRYABLE_FAILURES = frozenset(
    {
        FailureClassification.ADAPTER_FAULT,
        FailureClassification.RATE_LIMITED,
        FailureClassification.UNAVAILABLE,
    }
)
_SETUP_FAILURES = frozenset(
    {
        FailureClassification.AUTH_MISSING,
        FailureClassification.AUTH_EXPIRED,
        FailureClassification.AUTH_INVALID,
    }
)
_EVIDENCE_FAILURES = frozenset(
    {
        FailureClassification.NEAR_MATCH_REJECTED,
        FailureClassification.NOT_FOUND_EXACT,
        FailureClassification.UNSUPPORTED_FORMAT,
    }
)


class ProviderWorkflowError(ValueError):
    """The provider workflow handler factory was configured inconsistently."""


class ExactIdentityResolver(Protocol):
    """Resolve the authoritative identity already proven for this workflow item."""

    def __call__(self, context: StageContext, /) -> ExactPartIdentity: ...


@dataclass(frozen=True, slots=True)
class ProviderRetryBounds:
    """Deterministic workflow retry bounds; the coordinator owns richer policy."""

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
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not math.isfinite(float(delay))
            or delay <= 0
            for delay in delays
        ):
            raise ProviderWorkflowError("retry delays must be positive finite numbers")
        if not (
            self.minimum_delay_seconds <= self.default_delay_seconds <= self.maximum_delay_seconds
        ):
            raise ProviderWorkflowError("default retry delay must lie inside its bounds")
        if type(self.maximum_attempts) is not int or not 1 <= self.maximum_attempts <= 100:
            raise ProviderWorkflowError("maximum_attempts must be between 1 and 100")

    def clamp(self, requested_seconds: float | None) -> float:
        delay = (
            float(self.default_delay_seconds)
            if requested_seconds is None
            else float(requested_seconds)
        )
        return min(
            float(self.maximum_delay_seconds),
            max(float(self.minimum_delay_seconds), delay),
        )


def _strict(document: dict[str, object]) -> dict[str, object]:
    canonical_json(document)
    return document


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST_PATTERN.fullmatch(value) is not None


def _identity_reference(context: StageContext) -> dict[str, object]:
    raw = context.prior_results.get(StageName.IDENTITY_DEDUPE)
    if not isinstance(raw, Mapping):
        raise ProviderWorkflowError("identity dependency result is missing")
    component_id = raw.get("component_id")
    identity_digest = raw.get("identity_digest")
    manufacturer_id = raw.get("manufacturer_id")
    if (
        type(component_id) is not str
        or not component_id
        or len(component_id) > 256
        or not _valid_digest(identity_digest)
        or type(manufacturer_id) is not str
        or not manufacturer_id
        or len(manufacturer_id) > 256
    ):
        raise ProviderWorkflowError("identity dependency result is malformed")
    return {
        "component_id": component_id,
        "identity_digest": identity_digest,
        "manufacturer_id": manufacturer_id,
    }


def _attempt_evidence(selection: ProviderSelectionReceipt) -> list[dict[str, object]]:
    return [
        {
            "adapter_version": receipt.attempt.adapter_version,
            "evidence_digests": list(receipt.evidence_digests),
            "provider_key": receipt.attempt.provider_key,
            "status": receipt.status.value,
        }
        for receipt in selection.attempts
    ]


def _selected_evidence(selection: ProviderSelectionReceipt) -> dict[str, object] | None:
    selected = selection.selected_attempt
    if selected is None:
        return None
    receipt = next(attempt for attempt in selection.attempts if attempt.attempt == selected)
    return {
        "adapter_version": selected.adapter_version,
        "evidence_digests": list(receipt.evidence_digests),
        "provider_key": selected.provider_key,
        "status": AdapterOutcomeStatus.SUCCESS.value,
    }


def _receipt_document(
    *,
    stage: StageName,
    identity_reference: dict[str, object],
    policy_semantic_digest: str,
    plan_semantic_digest: str,
    receipt: ProviderExecutionReceipt,
) -> dict[str, object]:
    return _strict(
        {
            "identity": identity_reference,
            "kind": "provider_stage_receipt",
            "operations": [
                {
                    "attempts": _attempt_evidence(selection),
                    "operation": selection.operation.label,
                    "selected": _selected_evidence(selection),
                }
                for selection in receipt.selections
            ],
            "plan_semantic_digest": plan_semantic_digest,
            "policy_semantic_digest": policy_semantic_digest,
            "receipt_semantic_digest": receipt.semantic_digest,
            "schema_version": _SCHEMA_VERSION,
            "stage": stage.value,
        }
    )


def _group_exclusions(
    exclusions: tuple[ProviderExclusion, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for exclusion in exclusions:
        key = (exclusion.operation.label, exclusion.classification.value)
        grouped.setdefault(key, []).append(exclusion.provider_key)
    return [
        {
            "classification": classification,
            "operation": operation,
            "providers": sorted(providers),
        }
        for (operation, classification), providers in sorted(grouped.items())
    ]


def _failure(
    kind: str,
    *,
    stage: StageName,
    policy_semantic_digest: str | None = None,
    plan_semantic_digest: str | None = None,
    receipt_semantic_digest: str | None = None,
    details: dict[str, object] | None = None,
) -> PermanentFailureOutcome:
    document: dict[str, object] = {
        "kind": kind,
        "plan_semantic_digest": plan_semantic_digest,
        "policy_semantic_digest": policy_semantic_digest,
        "receipt_semantic_digest": receipt_semantic_digest,
        "schema_version": _SCHEMA_VERSION,
        "stage": stage.value,
    }
    if details is not None:
        document["details"] = details
    return PermanentFailureOutcome(_strict(document))


def _decision(
    kind: str,
    question: str,
    *,
    stage: StageName,
    policy_semantic_digest: str,
    plan_semantic_digest: str | None,
    receipt_semantic_digest: str | None,
    details: dict[str, object],
) -> DecisionOutcome:
    return DecisionOutcome(
        DecisionKind.SAFETY,
        _strict(
            {
                "details": details,
                "kind": kind,
                "plan_semantic_digest": plan_semantic_digest,
                "policy_semantic_digest": policy_semantic_digest,
                "question": question,
                "receipt_semantic_digest": receipt_semantic_digest,
                "schema_version": _SCHEMA_VERSION,
                "stage": stage.value,
            }
        ),
    )


@dataclass(frozen=True, slots=True)
class _RetryCheckpoint:
    policy_semantic_digest: str
    plan_semantic_digest: str | None


def _retry_checkpoint(context: StageContext) -> _RetryCheckpoint | None:
    if context.stage.attempt_count <= 1:
        return None
    error = context.stage.error
    # Attempt numbers advance for both deliberate provider retries and recovered worker leases.
    # A worker that exits while a provider page is open leaves no provider outcome/checkpoint;
    # the replacement worker must safely re-plan from the exact identity and retained evidence.
    # Only a document that explicitly identifies itself as a provider retry is a checkpoint.
    if not isinstance(error, dict) or error.get("kind") != "provider_stage_retry":
        return None
    policy_digest = error.get("policy_semantic_digest")
    plan_digest = error.get("plan_semantic_digest")
    if (
        type(policy_digest) is not str
        or not _valid_digest(policy_digest)
        or (
            plan_digest is not None
            and (type(plan_digest) is not str or not _valid_digest(plan_digest))
        )
    ):
        raise ProviderWorkflowError("retry provider plan checkpoint is malformed")
    return _RetryCheckpoint(
        policy_semantic_digest=policy_digest,
        plan_semantic_digest=plan_digest,
    )


@dataclass(frozen=True, slots=True)
class _ProviderStageExecutor:
    exact_identity: ExactIdentityResolver
    planner: ProviderPlanner
    runtime: ProviderExecutionRuntime
    policy_inputs: tuple[ProviderPolicyInput, ...]
    clock: Callable[[], float]
    retry_bounds: ProviderRetryBounds

    def handler(self, stage: StageName) -> StageHandler:
        def handle(context: StageContext) -> StageOutcome:
            return self.execute(stage, context)

        return handle

    def execute(self, stage: StageName, context: StageContext) -> StageOutcome:
        if context.stage.name is not stage:
            return _failure("provider_handler_stage_mismatch", stage=stage)
        try:
            identity_reference = _identity_reference(context)
            identity = self.exact_identity(context)
            if type(identity) is not ExactPartIdentity:
                raise ProviderWorkflowError("exact identity resolver must return ExactPartIdentity")
            checkpoint = _retry_checkpoint(context)
            policy_digest = self.planner.policy_semantic_digest(self.policy_inputs)
        except Exception:
            return _failure("provider_identity_or_checkpoint_invalid", stage=stage)

        if checkpoint is not None and checkpoint.policy_semantic_digest != policy_digest:
            return _failure(
                "provider_policy_drift",
                stage=stage,
                policy_semantic_digest=policy_digest,
                plan_semantic_digest=checkpoint.plan_semantic_digest,
                details={
                    "expected_policy_semantic_digest": (checkpoint.policy_semantic_digest),
                },
            )

        operations = _STAGE_OPERATIONS[stage]
        try:
            plan = self.planner.plan(
                (ProviderRequest(identity, operations),),
                self.policy_inputs,
            )[0]
        except UnexecutableProviderPlan as exc:
            return self._unexecutable(
                stage,
                context,
                policy_digest,
                exc,
            )
        except Exception:
            return _failure(
                "provider_plan_invalid",
                stage=stage,
                policy_semantic_digest=policy_digest,
            )

        if (
            checkpoint is not None
            and checkpoint.plan_semantic_digest is not None
            and checkpoint.plan_semantic_digest != plan.semantic_digest
        ):
            return _failure(
                "provider_plan_drift",
                stage=stage,
                policy_semantic_digest=policy_digest,
                plan_semantic_digest=plan.semantic_digest,
                details={
                    "expected_plan_semantic_digest": (checkpoint.plan_semantic_digest),
                },
            )

        try:
            receipt = self.runtime.execute((plan,), self.policy_inputs)[0]
        except Exception:
            return _failure(
                "provider_contract_drift",
                stage=stage,
                policy_semantic_digest=policy_digest,
                plan_semantic_digest=plan.semantic_digest,
            )

        evidence = _receipt_document(
            stage=stage,
            identity_reference=identity_reference,
            policy_semantic_digest=policy_digest,
            plan_semantic_digest=plan.semantic_digest,
            receipt=receipt,
        )
        if receipt.complete:
            missing_evidence = [
                selection.operation.label
                for selection in receipt.selections
                if not any(
                    attempt.evidence_digests
                    for attempt in selection.attempts
                    if attempt.status is AdapterOutcomeStatus.SUCCESS
                )
            ]
            if missing_evidence:
                return _failure(
                    "provider_success_without_evidence",
                    stage=stage,
                    policy_semantic_digest=policy_digest,
                    plan_semantic_digest=plan.semantic_digest,
                    receipt_semantic_digest=receipt.semantic_digest,
                    details={"operations": missing_evidence},
                )
            return CompletionOutcome(evidence)
        return self._incomplete(
            stage,
            context,
            policy_digest,
            plan.semantic_digest,
            receipt,
            evidence,
        )

    def _retry(
        self,
        *,
        stage: StageName,
        context: StageContext,
        policy_semantic_digest: str,
        plan_semantic_digest: str | None,
        receipt_semantic_digest: str | None,
        evidence: dict[str, object],
        requested_seconds: float | None,
    ) -> StageOutcome:
        if context.stage.attempt_count >= self.retry_bounds.maximum_attempts:
            return _failure(
                "provider_retry_exhausted",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=plan_semantic_digest,
                receipt_semantic_digest=receipt_semantic_digest,
                details={"attempt_count": context.stage.attempt_count},
            )
        try:
            now = float(self.clock())
            if not math.isfinite(now):
                raise ValueError
            retry_at = now + self.retry_bounds.clamp(requested_seconds)
            if not math.isfinite(retry_at):
                raise ValueError
        except Exception:
            return _failure(
                "provider_retry_clock_invalid",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=plan_semantic_digest,
                receipt_semantic_digest=receipt_semantic_digest,
            )
        return RetryOutcome(
            _strict(
                {
                    "evidence": evidence,
                    "kind": "provider_stage_retry",
                    "plan_semantic_digest": plan_semantic_digest,
                    "policy_semantic_digest": policy_semantic_digest,
                    "receipt_semantic_digest": receipt_semantic_digest,
                    "schema_version": _SCHEMA_VERSION,
                    "stage": stage.value,
                }
            ),
            retry_at,
        )

    def _unexecutable(
        self,
        stage: StageName,
        context: StageContext,
        policy_semantic_digest: str,
        error: UnexecutableProviderPlan,
    ) -> StageOutcome:
        blockers = _group_exclusions(error.exclusions)
        relevant = tuple(
            policy for policy in self.policy_inputs if policy.operation in error.unmet_operations
        )
        details = {
            "blockers": blockers,
            "unmet_operations": [operation.label for operation in error.unmet_operations],
        }
        if any(
            policy.authentication
            in {
                AuthenticationState.MISSING,
                AuthenticationState.EXPIRED,
                AuthenticationState.INVALID,
            }
            for policy in relevant
        ):
            return _failure(
                "provider_setup_required",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                details=details,
            )
        if any(
            policy.trust is TrustDecision.UNREVIEWED or policy.license is LicenseDecision.UNKNOWN
            for policy in relevant
        ):
            return _decision(
                "provider_policy_exception",
                "Is this provider policy acceptable for this exact acquisition?",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=None,
                receipt_semantic_digest=None,
                details=details,
            )
        if any(
            policy.health
            in {
                ProviderHealth.RATE_LIMITED,
                ProviderHealth.UNAVAILABLE,
                ProviderHealth.CIRCUIT_OPEN,
            }
            for policy in relevant
        ):
            return self._retry(
                stage=stage,
                context=context,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=None,
                receipt_semantic_digest=None,
                evidence=_strict(
                    {
                        "blockers": blockers,
                        "kind": "provider_plan_unmet",
                        "schema_version": _SCHEMA_VERSION,
                        "stage": stage.value,
                    }
                ),
                requested_seconds=None,
            )
        return _failure(
            "provider_plan_unmet",
            stage=stage,
            policy_semantic_digest=policy_semantic_digest,
            details=details,
        )

    def _incomplete(
        self,
        stage: StageName,
        context: StageContext,
        policy_semantic_digest: str,
        plan_semantic_digest: str,
        receipt: ProviderExecutionReceipt,
        evidence: dict[str, object],
    ) -> StageOutcome:
        unmet = tuple(selection for selection in receipt.selections if not selection.satisfied)
        statuses = {
            attempt.status
            for selection in unmet
            for attempt in selection.attempts
            if isinstance(attempt.status, FailureClassification)
        }
        details = {
            "evidence": evidence,
            "unmet_operations": [selection.operation.label for selection in unmet],
        }
        if statuses & _SETUP_FAILURES:
            return _failure(
                "provider_setup_required",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=plan_semantic_digest,
                receipt_semantic_digest=receipt.semantic_digest,
                details=details,
            )
        if statuses & _RETRYABLE_FAILURES:
            retry_delays = [
                attempt.retry_after_seconds
                for selection in unmet
                for attempt in selection.attempts
                if attempt.status is FailureClassification.RATE_LIMITED
                and attempt.retry_after_seconds is not None
            ]
            return self._retry(
                stage=stage,
                context=context,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=plan_semantic_digest,
                receipt_semantic_digest=receipt.semantic_digest,
                evidence=evidence,
                requested_seconds=min(retry_delays) if retry_delays else None,
            )
        if statuses and statuses <= _EVIDENCE_FAILURES:
            return _decision(
                "provider_evidence_exception",
                "Which evidence can prove the unmet provider outcomes?",
                stage=stage,
                policy_semantic_digest=policy_semantic_digest,
                plan_semantic_digest=plan_semantic_digest,
                receipt_semantic_digest=receipt.semantic_digest,
                details=details,
            )
        return _failure(
            "provider_stage_unmet",
            stage=stage,
            policy_semantic_digest=policy_semantic_digest,
            plan_semantic_digest=plan_semantic_digest,
            receipt_semantic_digest=receipt.semantic_digest,
            details=details,
        )


def build_provider_stage_handlers(
    *,
    exact_identity: ExactIdentityResolver,
    planner: ProviderPlanner,
    runtime: ProviderExecutionRuntime,
    policy_inputs: tuple[ProviderPolicyInput, ...],
    clock: Callable[[], float] = time.time,
    retry_bounds: ProviderRetryBounds = ProviderRetryBounds(),
) -> StageHandlerRegistry:
    """Build the three immutable provider-backed workflow handlers."""

    if not callable(exact_identity):
        raise TypeError("exact_identity must be callable")
    if type(planner) is not ProviderPlanner:
        raise TypeError("planner must be ProviderPlanner")
    if type(runtime) is not ProviderExecutionRuntime:
        raise TypeError("runtime must be ProviderExecutionRuntime")
    if runtime.planner is not planner:
        raise ProviderWorkflowError("runtime and handlers must share one planner")
    if (
        type(policy_inputs) is not tuple
        or not policy_inputs
        or any(type(policy) is not ProviderPolicyInput for policy in policy_inputs)
    ):
        raise ProviderWorkflowError("policy_inputs must be an explicit immutable non-empty tuple")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if type(retry_bounds) is not ProviderRetryBounds:
        raise TypeError("retry_bounds must be ProviderRetryBounds")

    executor = _ProviderStageExecutor(
        exact_identity=exact_identity,
        planner=planner,
        runtime=runtime,
        policy_inputs=policy_inputs,
        clock=clock,
        retry_bounds=retry_bounds,
    )
    return MappingProxyType({stage: executor.handler(stage) for stage in PROVIDER_WORKFLOW_STAGES})


__all__ = [
    "ExactIdentityResolver",
    "PROVIDER_WORKFLOW_STAGES",
    "ProviderRetryBounds",
    "ProviderWorkflowError",
    "build_provider_stage_handlers",
]
