"""Bounded concurrent execution for deterministic provider plans.

The runtime owns resource admission and sanitized receipts only.  Provider
eligibility, exact identity, route order, and dual-EDA requirements remain
authoritative in :mod:`stockroom.planning.provider_policy`.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from .provider_policy import (
    AdapterOutcomeStatus,
    CapabilityKind,
    EdaTarget,
    ExactPartIdentity,
    FailureClassification,
    ProviderAdapterExecutionError,
    ProviderAttempt,
    ProviderAttemptRecord,
    ProviderOperation,
    ProviderPlan,
    ProviderPlanner,
    ProviderPolicyError,
    ProviderPolicyInput,
    ProviderRoute,
)

_MAX_REQUESTS = 1_000
_MAX_RUNTIME_WORKERS = 256
_DEFAULT_RUNTIME_WORKERS = 64


class ProviderRuntimeError(RuntimeError):
    """The concurrent runtime or a supplied saved plan violated its contract."""


class ProviderEvidenceVerifier(Protocol):
    """Verify that claimed evidence exists and binds the exact provider attempt."""

    def verify_provider_success(
        self,
        digest: str,
        *,
        identity: ExactPartIdentity,
        operation: ProviderOperation,
        provider_key: str,
        adapter_version: str,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ProviderAttemptReceipt:
    """Sanitized immutable observation of one adapter invocation."""

    attempt: ProviderAttempt
    status: AdapterOutcomeStatus | FailureClassification
    retry_after_seconds: float | None
    queue_wait_ns: int
    execution_ns: int
    evidence_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.attempt) is not ProviderAttempt:
            raise TypeError("attempt must be ProviderAttempt")
        if not (
            type(self.status) is AdapterOutcomeStatus or type(self.status) is FailureClassification
        ):
            raise TypeError("status must be a sanitized provider status")
        if self.retry_after_seconds is not None and (
            self.status is not FailureClassification.RATE_LIMITED
            or isinstance(self.retry_after_seconds, bool)
            or not isinstance(self.retry_after_seconds, (int, float))
            or not math.isfinite(float(self.retry_after_seconds))
            or self.retry_after_seconds <= 0
        ):
            raise ProviderRuntimeError("retry_after_seconds must be positive")
        if (
            type(self.queue_wait_ns) is not int
            or self.queue_wait_ns < 0
            or type(self.execution_ns) is not int
            or self.execution_ns < 0
        ):
            raise ProviderRuntimeError("attempt timing must be non-negative nanoseconds")
        if (
            type(self.evidence_digests) is not tuple
            or len(set(self.evidence_digests)) != len(self.evidence_digests)
            or self.evidence_digests != tuple(sorted(self.evidence_digests))
            or any(
                type(digest) is not str
                or not digest.startswith("sha256:")
                or len(digest) != 71
                or any(character not in "0123456789abcdef" for character in digest[7:])
                for digest in self.evidence_digests
            )
        ):
            raise ProviderRuntimeError("attempt evidence digests must be canonical")
        if self.status is not AdapterOutcomeStatus.SUCCESS and self.evidence_digests:
            raise ProviderRuntimeError("failed attempts cannot claim evidence digests")


@dataclass(frozen=True, slots=True)
class ProviderSelectionReceipt:
    """Ordered fallback evidence and the exact selected provider, if any."""

    operation: ProviderOperation
    selected_attempt: ProviderAttempt | None
    attempts: tuple[ProviderAttemptReceipt, ...]

    def __post_init__(self) -> None:
        if type(self.operation) is not ProviderOperation:
            raise TypeError("operation must be ProviderOperation")
        if (
            type(self.attempts) is not tuple
            or not self.attempts
            or any(
                type(receipt) is not ProviderAttemptReceipt
                or receipt.attempt.operation != self.operation
                for receipt in self.attempts
            )
        ):
            raise ProviderRuntimeError(
                "selection receipt requires ordered attempts for one operation"
            )
        successful = tuple(
            receipt.attempt
            for receipt in self.attempts
            if receipt.status is AdapterOutcomeStatus.SUCCESS
        )
        if self.selected_attempt is None:
            if successful:
                raise ProviderRuntimeError("selection receipt omits its successful provider")
        elif (
            type(self.selected_attempt) is not ProviderAttempt
            or successful != (self.selected_attempt,)
            or self.attempts[-1].attempt != self.selected_attempt
        ):
            raise ProviderRuntimeError(
                "selected provider must be the sole final successful attempt"
            )

    @property
    def satisfied(self) -> bool:
        return self.selected_attempt is not None


@dataclass(frozen=True, slots=True)
class ProviderExecutionReceipt:
    """Complete sanitized result for one exact-identity provider plan."""

    identity: ExactPartIdentity
    selections: tuple[ProviderSelectionReceipt, ...]
    semantic_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.identity) is not ExactPartIdentity:
            raise TypeError("identity must be ExactPartIdentity")
        if (
            type(self.selections) is not tuple
            or not self.selections
            or any(type(selection) is not ProviderSelectionReceipt for selection in self.selections)
        ):
            raise ProviderRuntimeError("execution receipt requires immutable selection receipts")
        operations = tuple(selection.operation for selection in self.selections)
        if len(set(operations)) != len(operations) or operations != tuple(
            sorted(operations, key=lambda operation: operation.sort_key)
        ):
            raise ProviderRuntimeError("execution receipt operations must be unique and canonical")
        object.__setattr__(
            self,
            "semantic_digest",
            _receipt_digest(self.identity, self.selections),
        )

    @property
    def complete(self) -> bool:
        return all(selection.satisfied for selection in self.selections)

    @property
    def unmet_operations(self) -> tuple[ProviderOperation, ...]:
        return tuple(
            selection.operation for selection in self.selections if not selection.satisfied
        )


def _receipt_digest(
    identity: ExactPartIdentity,
    selections: tuple[ProviderSelectionReceipt, ...],
) -> str:
    """Hash sanitized semantic evidence; intentionally exclude local timing."""

    document = {
        "identity": {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        },
        "selections": [
            {
                "attempts": [
                    {
                        "adapter_version": receipt.attempt.adapter_version,
                        "evidence_digests": list(receipt.evidence_digests),
                        "max_concurrency": receipt.attempt.max_concurrency,
                        "provider_key": receipt.attempt.provider_key,
                        "status": receipt.status.value,
                    }
                    for receipt in selection.attempts
                ],
                "operation": selection.operation.label,
                "selected_provider_key": (
                    None
                    if selection.selected_attempt is None
                    else selection.selected_attempt.provider_key
                ),
            }
            for selection in selections
        ],
        "version": 2,
    }
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ProviderExecutionRuntime:
    """Execute saved provider plans with shared per-provider admission limits."""

    def __init__(
        self,
        planner: ProviderPlanner,
        *,
        max_workers: int | None = None,
        evidence_verifier: ProviderEvidenceVerifier | None = None,
    ):
        if type(planner) is not ProviderPlanner:
            raise TypeError("planner must be ProviderPlanner")
        concurrency_limits = planner.concurrency_limits
        if not concurrency_limits:
            raise ProviderRuntimeError("provider runtime requires executable providers")
        if max_workers is None:
            worker_count = min(
                _DEFAULT_RUNTIME_WORKERS,
                max(1, sum(concurrency_limits.values())),
            )
        else:
            if type(max_workers) is not int or not 1 <= max_workers <= _MAX_RUNTIME_WORKERS:
                raise ProviderRuntimeError(
                    f"max_workers must be between 1 and {_MAX_RUNTIME_WORKERS}"
                )
            worker_count = max_workers

        self._planner = planner
        self._worker_count = worker_count
        self._limits = dict(concurrency_limits)
        self._evidence_verifier = evidence_verifier
        self._admission = {
            provider_key: threading.BoundedSemaphore(limit)
            for provider_key, limit in concurrency_limits.items()
        }

    @property
    def concurrency_limits(self) -> dict[str, int]:
        return dict(self._limits)

    @property
    def max_workers(self) -> int:
        return self._worker_count

    @property
    def planner(self) -> ProviderPlanner:
        return self._planner

    def _validate_plan(self, plan: ProviderPlan) -> None:
        if type(plan) is not ProviderPlan:
            raise TypeError("plans must contain ProviderPlan values")
        if type(plan.identity) is not ExactPartIdentity:
            raise TypeError("plan identity must be ExactPartIdentity")
        if (
            type(plan.routes) is not tuple
            or not plan.routes
            or any(type(route) is not ProviderRoute for route in plan.routes)
        ):
            raise ProviderRuntimeError("provider plan requires immutable routes")
        operations = tuple(route.operation for route in plan.routes)
        if len(set(operations)) != len(operations) or operations != tuple(
            sorted(operations, key=lambda operation: operation.sort_key)
        ):
            raise ProviderRuntimeError("provider plan operations must be unique and canonical")
        cad_targets = {
            operation.eda_target
            for operation in operations
            if operation.capability is CapabilityKind.CAD
        }
        if cad_targets and cad_targets != {EdaTarget.KICAD, EdaTarget.ALTIUM}:
            raise ProviderRuntimeError(
                "runtime refuses a plan without both KiCad and Altium CAD routes"
            )
        for route in plan.routes:
            if (
                type(route.attempts) is not tuple
                or not route.attempts
                or any(type(attempt) is not ProviderAttempt for attempt in route.attempts)
                or any(
                    attempt.operation != route.operation
                    or attempt.provider_key not in self._limits
                    or attempt.max_concurrency != self._limits[attempt.provider_key]
                    for attempt in route.attempts
                )
            ):
                raise ProviderRuntimeError(
                    "provider plan route does not match runtime admission declarations"
                )

    def _execute_route(
        self,
        identity: ExactPartIdentity,
        route: ProviderRoute,
    ) -> ProviderSelectionReceipt:
        receipts: list[ProviderAttemptReceipt] = []
        selected: ProviderAttempt | None = None
        for attempt in route.attempts:
            queued_at = time.perf_counter_ns()
            admission = self._admission[attempt.provider_key]
            with admission:
                started_at = time.perf_counter_ns()
                try:
                    record = self._planner.execute_attempt(identity, attempt)
                except ProviderAdapterExecutionError:
                    record = ProviderAttemptRecord(
                        attempt,
                        FailureClassification.ADAPTER_FAULT,
                    )
                if (
                    record.status is AdapterOutcomeStatus.SUCCESS
                    and self._evidence_verifier is not None
                ):
                    try:
                        if not record.evidence_digests:
                            raise ProviderRuntimeError(
                                "successful provider attempt omitted immutable evidence"
                            )
                        for digest in record.evidence_digests:
                            self._evidence_verifier.verify_provider_success(
                                digest,
                                identity=identity,
                                operation=attempt.operation,
                                provider_key=attempt.provider_key,
                                adapter_version=attempt.adapter_version,
                            )
                    except Exception:
                        record = ProviderAttemptRecord(
                            attempt,
                            FailureClassification.ADAPTER_FAULT,
                        )
                completed_at = time.perf_counter_ns()
            receipts.append(
                ProviderAttemptReceipt(
                    attempt=attempt,
                    status=record.status,
                    retry_after_seconds=record.retry_after_seconds,
                    queue_wait_ns=max(0, started_at - queued_at),
                    execution_ns=max(0, completed_at - started_at),
                    evidence_digests=record.evidence_digests,
                )
            )
            if record.status is AdapterOutcomeStatus.SUCCESS:
                selected = attempt
                break
        return ProviderSelectionReceipt(
            operation=route.operation,
            selected_attempt=selected,
            attempts=tuple(receipts),
        )

    def execute(
        self,
        plans: Sequence[ProviderPlan],
        policy_inputs: Sequence[ProviderPolicyInput],
    ) -> tuple[ProviderExecutionReceipt, ...]:
        """Preflight, then execute one through one thousand plans identically."""

        requested = tuple(plans)
        if not 1 <= len(requested) <= _MAX_REQUESTS:
            raise ProviderRuntimeError(f"runtime accepts between 1 and {_MAX_REQUESTS} plans")
        for plan in requested:
            self._validate_plan(plan)
        self._planner.validate_plans(requested, policy_inputs)

        results: list[list[ProviderSelectionReceipt | None]] = [
            [None] * len(plan.routes) for plan in requested
        ]
        executor = ThreadPoolExecutor(
            max_workers=min(
                self._worker_count,
                sum(len(plan.routes) for plan in requested),
            ),
            thread_name_prefix="stockroom-provider",
        )
        futures: list[tuple[int, int, Future[ProviderSelectionReceipt]]] = []
        try:
            for plan_index, plan in enumerate(requested):
                for route_index, route in enumerate(plan.routes):
                    futures.append(
                        (
                            plan_index,
                            route_index,
                            executor.submit(
                                self._execute_route,
                                plan.identity,
                                route,
                            ),
                        )
                    )
            for plan_index, route_index, future in futures:
                results[plan_index][route_index] = future.result()
        except BaseException:
            for _plan_index, _route_index, future in futures:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

        receipts: list[ProviderExecutionReceipt] = []
        for plan, selections in zip(requested, results, strict=True):
            if any(selection is None for selection in selections):
                raise ProviderRuntimeError("provider runtime lost a completed route receipt")
            receipts.append(
                ProviderExecutionReceipt(
                    identity=plan.identity,
                    selections=tuple(
                        selection for selection in selections if selection is not None
                    ),
                )
            )
        return tuple(receipts)


__all__ = [
    "ProviderAttemptReceipt",
    "ProviderExecutionReceipt",
    "ProviderExecutionRuntime",
    "ProviderEvidenceVerifier",
    "ProviderRuntimeError",
    "ProviderSelectionReceipt",
]
