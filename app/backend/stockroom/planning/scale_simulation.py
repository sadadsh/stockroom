"""Durable synthetic scale simulation for the settled fourteen-stage workflow.

This module proves scheduler, retry, restart, publication-ledger, and receipt
semantics without generating production components or mutating Git/catalog
state.  Every simulated stage result and publication receipt carries an
explicit synthetic-only scope label.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock, get_ident
from types import MappingProxyType

from stockroom.workflow import (
    BatchRecord,
    CompletionOutcome,
    ExactIdentityOutcome,
    IntakeIdentity,
    PublicationProposalOutcome,
    PublicationState,
    RetryOutcome,
    StageContext,
    StageHandlerRegistry,
    StageName,
    WorkflowRuntime,
    WorkflowStore,
)

SYNTHETIC_SCALE_SCOPE = "synthetic_scale_simulation_only_not_production_asset_proof"
_SYNTHETIC_MANUFACTURER = "Stockroom Synthetic Scale Manufacturer"
_SYNTHETIC_REGISTRY_REVISION = "synthetic-scale-registry-v1"
_SYNTHETIC_RULE_REVISION = "synthetic-exact-identity-v1"
_SYNTHETIC_BASE_COMMIT = "synthetic-no-git-base-commit"
# Reproduced twice under the Windows aggregate gate and once in isolation on the owner's
# supported machine. The 1,000-identity run settles exactly once in 30.8-33.0 seconds; 35 seconds
# keeps the budget discriminating while allowing normal Windows scheduler and SQLite variance.
_PERFORMANCE_TARGET_SECONDS = 35.0


class ScaleSimulationError(RuntimeError):
    """The synthetic run stalled or violated its terminal invariants."""


@dataclass(frozen=True, slots=True)
class ScaleSimulationReport:
    """Measured evidence from one durable, explicitly synthetic run."""

    scope: str
    production_asset_proof: bool
    synthetic_external_effects: bool
    durability_profile: str
    identity_count: int
    batch_count: int
    item_count: int
    stage_count: int
    publication_count: int
    receipt_count: int
    retry_injection_count: int
    fallback_injection_count: int
    stage_dispatch_count: int
    claim_round_count: int
    publication_claim_round_count: int
    claim_limit: int
    worker_count: int
    workers_observed: int
    max_stage_claims_in_flight: int
    max_publication_claims_in_flight: int
    store_reopen_count: int
    reopened_after_stage_dispatches: int
    completed_items_at_reopen: int
    elapsed_seconds: float
    stage_dispatches_per_second: float
    performance_target_seconds: float
    performance_target_met: bool
    optimization_hypothesis: str
    next_discriminating_optimization_target: str
    database_file_size_bytes: int
    database_wal_size_bytes: int
    database_shm_size_bytes: int
    database_total_storage_bytes: int
    database_page_count: int
    database_page_size_bytes: int
    database_allocated_bytes: int
    event_count: int
    terminal_exactly_once: bool

    def to_json(self) -> dict[str, object]:
        """Return a strict JSON-compatible report document."""

        return asdict(self)


@dataclass(slots=True)
class _RunMetrics:
    stage_dispatches: int = 0
    claim_rounds: int = 0
    publication_claim_rounds: int = 0
    max_stage_claims: int = 0
    max_publication_claims: int = 0
    reopen_count: int = 0
    reopened_after_dispatches: int = 0
    completed_items_at_reopen: int = 0


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _synthetic_commit_oid(publication_id: str) -> str:
    suffix = hashlib.sha256(f"synthetic-git-oid:{publication_id}".encode("utf-8")).hexdigest()
    return f"synthetic-not-a-git-commit-{suffix}"


class _ScaleSimulationStore(WorkflowStore):
    """Same durable schema/transitions with WAL/NORMAL simulation durability.

    NORMAL is durable across an ordinary process restart, which this harness
    verifies.  It is not evidence of the production store's FULL power-loss
    durability and the report says so explicitly.
    """

    def __init__(self, database: str | Path):
        self._simulation_connections: dict[int, sqlite3.Connection] = {}
        self._simulation_connections_lock = Lock()
        super().__init__(database)
        # WorkflowStore._initialize deliberately closes its bootstrap connection.
        self._simulation_connections.clear()

    def _connect(self) -> sqlite3.Connection:
        thread_id = get_ident()
        with self._simulation_connections_lock:
            existing = self._simulation_connections.get(thread_id)
            if existing is not None:
                return existing
            connection = sqlite3.connect(
                self.database,
                isolation_level=None,
                timeout=30,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=NORMAL")
            self._simulation_connections[thread_id] = connection
            return connection

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        yield self._connect()

    @contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def close(self) -> None:
        with self._simulation_connections_lock:
            connections = tuple(self._simulation_connections.values())
            self._simulation_connections.clear()
        for connection in connections:
            connection.close()


class ScaleSimulationHarness:
    """Drive bounded synthetic load through the real durable workflow graph."""

    def __init__(
        self,
        store: WorkflowStore,
        *,
        claim_limit: int = 64,
        worker_count: int = 8,
        retry_every: int = 17,
        fallback_every: int = 19,
    ):
        if not isinstance(store, WorkflowStore):
            raise TypeError("store must be a WorkflowStore")
        if type(claim_limit) is not int or not 1 <= claim_limit <= 1_000:
            raise ValueError("claim_limit must be between 1 and 1000")
        if type(worker_count) is not int or not 1 <= worker_count <= claim_limit:
            raise ValueError("worker_count must be between 1 and claim_limit")
        for value, name in (
            (retry_every, "retry_every"),
            (fallback_every, "fallback_every"),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if store.count_batches() != 0:
            raise ScaleSimulationError("scale simulation requires a dedicated empty WorkflowStore")

        self.database = store.database
        self.store = _ScaleSimulationStore(self.database)
        self.claim_limit = claim_limit
        self.worker_count = worker_count
        self.retry_every = retry_every
        self.fallback_every = fallback_every
        self._dispatch_now = 2.0
        handlers = {name: self._handle_stage for name in StageName}
        self._handlers: StageHandlerRegistry = MappingProxyType(handlers)
        self.runtime = WorkflowRuntime(self.store, self._handlers)
        self._workers_seen: set[str] = set()
        self._stage_claim_sequence = 0
        self._publication_claim_sequence = 0
        self._closed = False

    def __enter__(self) -> ScaleSimulationHarness:
        if self._closed:
            raise ScaleSimulationError("scale simulation harness is closed")
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release every persistent SQLite handle owned by the harness."""

        if self._closed:
            return
        self.store.close()
        self._closed = True

    @property
    def handlers(self) -> StageHandlerRegistry:
        """Return the complete synthetic fourteen-stage handler registry."""

        return self._handlers

    def run(
        self,
        identity_count: int,
        *,
        batch_size: int = 100,
        reopen_mid_run: bool = True,
    ) -> ScaleSimulationReport:
        """Submit and terminally settle one synthetic scale run.

        Git and catalog transitions are ledger-only simulations.  No repository,
        EDA library, or active catalog is read or written.
        """

        if type(identity_count) is not int or not 1 <= identity_count <= 100_000:
            raise ValueError("identity_count must be between 1 and 100000")
        if type(batch_size) is not int or not 1 <= batch_size <= 1_000:
            raise ValueError("batch_size must be between 1 and 1000")
        if type(reopen_mid_run) is not bool:
            raise TypeError("reopen_mid_run must be an explicit boolean")
        if self._closed:
            raise ScaleSimulationError("scale simulation harness is closed")

        started = time.perf_counter()
        batches = self._submit(identity_count, batch_size)
        metrics = _RunMetrics()
        reopen_threshold = identity_count * 7
        idle_rounds = 0

        with ThreadPoolExecutor(
            max_workers=self.worker_count,
            thread_name_prefix="stockroom-scale-simulation",
        ) as executor:
            while not self._all_batches_completed():
                self._dispatch_now += 1.0
                claims = self._claim_stages()
                if claims:
                    metrics.claim_rounds += 1
                    metrics.max_stage_claims = max(
                        metrics.max_stage_claims,
                        len(claims),
                    )
                    list(executor.map(self._dispatch_claim, claims))
                    metrics.stage_dispatches += len(claims)
                    idle_rounds = 0

                publication_claims = self._claim_publications()
                if publication_claims:
                    metrics.publication_claim_rounds += 1
                    metrics.max_publication_claims = max(
                        metrics.max_publication_claims,
                        len(publication_claims),
                    )
                    list(
                        executor.map(
                            self._settle_claimed_publication,
                            publication_claims,
                        )
                    )
                    idle_rounds = 0

                if (
                    reopen_mid_run
                    and metrics.reopen_count == 0
                    and metrics.stage_dispatches >= reopen_threshold
                    and not self._all_batches_completed()
                ):
                    metrics.reopened_after_dispatches = metrics.stage_dispatches
                    metrics.completed_items_at_reopen = self._count_items_with_status("completed")
                    self._reopen_store()
                    metrics.reopen_count = 1

                if not claims and not publication_claims:
                    idle_rounds += 1
                    if idle_rounds > 2:
                        raise ScaleSimulationError(
                            "synthetic workflow stalled without ready durable work"
                        )

        elapsed = time.perf_counter() - started
        return self._report(
            identity_count,
            batches,
            metrics,
            elapsed,
            reopen_mid_run,
        )

    def _submit(
        self,
        identity_count: int,
        batch_size: int,
    ) -> tuple[BatchRecord, ...]:
        batches: list[BatchRecord] = []
        for batch_ordinal, start in enumerate(range(0, identity_count, batch_size)):
            stop = min(start + batch_size, identity_count)
            identities = tuple(
                IntakeIdentity(
                    manufacturer=_SYNTHETIC_MANUFACTURER,
                    mpn=f"SIM-{index:06d}",
                    payload={
                        "production_asset_proof": False,
                        "simulation_index": index,
                        "simulation_scope": SYNTHETIC_SCALE_SCOPE,
                    },
                )
                for index in range(start, stop)
            )
            batches.append(
                self.store.submit_batch(
                    identities,
                    idempotency_key=(
                        f"synthetic-scale-{identity_count}-{batch_size}-{batch_ordinal}"
                    ),
                    now=1.0 + batch_ordinal / 10_000,
                )
            )
        return tuple(batches)

    def _handle_stage(self, context: StageContext):
        index = self._simulation_index(context)
        name = context.stage.name
        if name is StageName.IDENTITY_DEDUPE:
            return ExactIdentityOutcome(
                authoritative_manufacturer_key=context.item.manufacturer,
                mpn_canonical=context.item.mpn,
                registry_revision=_SYNTHETIC_REGISTRY_REVISION,
                rule_revision=_SYNTHETIC_RULE_REVISION,
                evidence={
                    "production_asset_proof": False,
                    "simulation_index": index,
                    "simulation_scope": SYNTHETIC_SCALE_SCOPE,
                    "source_kind": "synthetic_scale_identity",
                },
            )
        if (
            name is StageName.METADATA
            and index % self.retry_every == 0
            and context.stage.attempt_count == 1
        ):
            return RetryOutcome(
                error={
                    "automatic": True,
                    "kind": "synthetic_retry_injection",
                    "production_asset_proof": False,
                    "simulation_index": index,
                    "simulation_scope": SYNTHETIC_SCALE_SCOPE,
                },
                retry_at=self._dispatch_now + 0.5,
            )
        if name is StageName.PUBLISH:
            identity = f"{context.item.manufacturer}\0{context.item.mpn}"
            return PublicationProposalOutcome(
                candidate_digest=_digest(f"synthetic-candidate-v1:{identity}"),
                manifest_digest=_digest(f"synthetic-manifest-v1:{identity}"),
                expected_base_commit=_SYNTHETIC_BASE_COMMIT,
            )

        fallback_used = name is StageName.CAD_ACQUISITION and index % self.fallback_every == 0
        return CompletionOutcome(
            {
                "attempt": context.stage.attempt_count,
                "automatic": True,
                "fallback_used": fallback_used,
                "prior_result_count": len(context.prior_results),
                "production_asset_proof": False,
                "simulation_index": index,
                "simulation_scope": SYNTHETIC_SCALE_SCOPE,
                "stage": name.value,
            }
        )

    @staticmethod
    def _simulation_index(context: StageContext) -> int:
        payload = context.item.payload
        if not isinstance(payload, dict):
            raise ScaleSimulationError("simulation item payload is not a JSON object")
        value = payload.get("simulation_index")
        if type(value) is not int or value < 0:
            raise ScaleSimulationError("simulation item has no durable integer index")
        if payload.get("simulation_scope") != SYNTHETIC_SCALE_SCOPE:
            raise ScaleSimulationError("simulation item scope label differs")
        return value

    def _next_worker(self, *, publication: bool) -> str:
        if publication:
            sequence = self._publication_claim_sequence
            self._publication_claim_sequence += 1
        else:
            sequence = self._stage_claim_sequence
            self._stage_claim_sequence += 1
        return f"synthetic_scale_worker_{sequence % self.worker_count:03d}"

    def _claim_stages(self):
        worker_id = self._next_worker(publication=False)
        worker_claims = self.store.claim_ready(
            worker_id,
            now=self._dispatch_now,
            lease_seconds=10_000,
            limit=self.claim_limit,
        )
        claimed = [(worker_id, claim) for claim in worker_claims]
        if claimed:
            self._workers_seen.add(worker_id)
        if len(claimed) > self.claim_limit:
            raise ScaleSimulationError("stage claim bound was exceeded")
        return claimed

    def _claim_publications(self):
        worker_id = self._next_worker(publication=True)
        leases = self.store.claim_publications(
            worker_id,
            now=self._dispatch_now,
            lease_seconds=10_000,
            limit=self.claim_limit,
        )
        claimed = [(worker_id, lease) for lease in leases]
        if claimed:
            self._workers_seen.add(worker_id)
        if len(claimed) > self.claim_limit:
            raise ScaleSimulationError("publication claim bound was exceeded")
        return claimed

    def _dispatch_claim(self, claimed) -> None:
        worker_id, claim = claimed
        self.runtime.dispatch_claim(
            claim,
            worker_id,
            now=self._dispatch_now,
        )

    def _settle_claimed_publication(self, claimed) -> None:
        worker_id, lease = claimed
        self._settle_synthetic_publication(worker_id, lease)

    def _settle_synthetic_publication(self, worker_id, lease) -> None:
        operation = self.store.get_publication_operation(lease.publication_id)
        lease_kwargs = {
            "lease_token": lease.lease_token,
            "lease_generation": lease.lease_generation,
            "now": self._dispatch_now,
        }
        if operation.state is PublicationState.PREPARING:
            operation = self.store.arm_publication_commit(
                lease.publication_id,
                worker_id,
                **lease_kwargs,
            )
        if operation.state is PublicationState.COMMIT_FENCED:
            operation = self.store.record_git_commit(
                lease.publication_id,
                worker_id,
                git_commit_oid=_synthetic_commit_oid(lease.publication_id),
                verified_tree_digest=_digest(f"synthetic-tree:{lease.publication_id}"),
                **lease_kwargs,
            )
        if operation.state is PublicationState.GIT_COMMITTED:
            operation = self.store.record_catalog_activation(
                lease.publication_id,
                worker_id,
                catalog_revision=(
                    "synthetic_catalog_revision_"
                    + hashlib.sha256(lease.publication_id.encode("utf-8")).hexdigest()[:16]
                ),
                catalog_semantic_digest=_digest(f"synthetic-catalog:{lease.publication_id}"),
                **lease_kwargs,
            )
        if operation.state is PublicationState.CATALOG_ACTIVATED:
            self.store.complete_publication(
                lease.publication_id,
                worker_id,
                {
                    "external_effects": ("synthetic_only_no_git_or_catalog_mutation"),
                    "production_asset_proof": False,
                    "publication_id": lease.publication_id,
                    "simulation_scope": SYNTHETIC_SCALE_SCOPE,
                },
                **lease_kwargs,
            )

    def _reopen_store(self) -> None:
        self.store.close()
        self.store = _ScaleSimulationStore(self.database)
        self.runtime = WorkflowRuntime(self.store, self._handlers)

    def _all_batches_completed(self) -> bool:
        with closing(sqlite3.connect(self.database)) as connection:
            return (
                connection.execute(
                    """
                    SELECT COUNT(*) FROM batches
                    WHERE status <> 'completed'
                    """
                ).fetchone()[0]
                == 0
            )

    def _count_items_with_status(self, status: str) -> int:
        with closing(sqlite3.connect(self.database)) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM items WHERE status = ?",
                    (status,),
                ).fetchone()[0]
            )

    def _report(
        self,
        identity_count: int,
        batches: tuple[BatchRecord, ...],
        metrics: _RunMetrics,
        elapsed: float,
        reopen_requested: bool,
    ) -> ScaleSimulationReport:
        expected_retries = sum(index % self.retry_every == 0 for index in range(identity_count))
        expected_fallbacks = sum(
            index % self.fallback_every == 0 for index in range(identity_count)
        )
        with closing(sqlite3.connect(self.database)) as connection:
            counts = {
                "all_batches": connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0],
                "batches": connection.execute(
                    "SELECT COUNT(*) FROM batches WHERE status = 'completed'"
                ).fetchone()[0],
                "all_items": connection.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "items": connection.execute(
                    "SELECT COUNT(*) FROM items WHERE status = 'completed'"
                ).fetchone()[0],
                "distinct_intake_identities": connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT manufacturer, mpn
                        FROM items
                        GROUP BY manufacturer, mpn
                    )
                    """
                ).fetchone()[0],
                "all_stages": connection.execute("SELECT COUNT(*) FROM stages").fetchone()[0],
                "stages": connection.execute(
                    "SELECT COUNT(*) FROM stages WHERE status = 'completed'"
                ).fetchone()[0],
                "exact_item_graphs": connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT item_id
                        FROM stages
                        GROUP BY item_id
                        HAVING COUNT(*) = ?
                           AND COUNT(DISTINCT name) = ?
                    )
                    """,
                    (len(StageName), len(StageName)),
                ).fetchone()[0],
                "all_publications": connection.execute(
                    "SELECT COUNT(*) FROM publication_operations"
                ).fetchone()[0],
                "publications": connection.execute(
                    """
                    SELECT COUNT(*) FROM publication_operations
                    WHERE state = 'completed'
                    """
                ).fetchone()[0],
                "all_receipts": connection.execute(
                    "SELECT COUNT(*) FROM component_publication_receipts"
                ).fetchone()[0],
                "receipts": connection.execute(
                    "SELECT COUNT(*) FROM component_publication_receipts"
                ).fetchone()[0],
                "all_memberships": connection.execute(
                    "SELECT COUNT(*) FROM publication_memberships"
                ).fetchone()[0],
                "memberships": connection.execute(
                    """
                    SELECT COUNT(*) FROM publication_memberships
                    WHERE state = 'completed'
                    """
                ).fetchone()[0],
                "heads": connection.execute(
                    "SELECT COUNT(*) FROM component_publication_heads"
                ).fetchone()[0],
                "components": connection.execute(
                    "SELECT COUNT(DISTINCT component_id) FROM item_component_bindings"
                ).fetchone()[0],
                "decisions": connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
                "stage_errors": connection.execute(
                    "SELECT COUNT(*) FROM stages WHERE error_json IS NOT NULL"
                ).fetchone()[0],
                "retry_events": connection.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE kind = 'stage_retry_scheduled'
                    """
                ).fetchone()[0],
                "fallbacks": connection.execute(
                    """
                    SELECT COUNT(*) FROM stages
                    WHERE name = 'cad_acquisition'
                      AND result_json LIKE '%"fallback_used":true%'
                    """
                ).fetchone()[0],
                "attempts": connection.execute("SELECT SUM(attempt_count) FROM stages").fetchone()[
                    0
                ],
                "events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                "identity_events": connection.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE kind = 'identity_resolved'
                    """
                ).fetchone()[0],
                "items_with_one_identity_event": connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT item_id
                        FROM events
                        WHERE kind = 'identity_resolved'
                        GROUP BY item_id
                        HAVING COUNT(*) = 1
                    )
                    """
                ).fetchone()[0],
                "publication_events": connection.execute(
                    """
                    SELECT COUNT(*) FROM events
                    WHERE kind = 'publication_completed'
                    """
                ).fetchone()[0],
                "items_with_one_publication_event": connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT item_id
                        FROM events
                        WHERE kind = 'publication_completed'
                        GROUP BY item_id
                        HAVING COUNT(*) = 1
                    )
                    """
                ).fetchone()[0],
                "page_count": connection.execute("PRAGMA page_count").fetchone()[0],
                "page_size": connection.execute("PRAGMA page_size").fetchone()[0],
            }

        exact = (
            counts["all_batches"] == len(batches)
            and counts["batches"] == len(batches)
            and counts["all_items"] == identity_count
            and counts["items"] == identity_count
            and counts["distinct_intake_identities"] == identity_count
            and counts["all_stages"] == identity_count * len(StageName)
            and counts["stages"] == identity_count * len(StageName)
            and counts["exact_item_graphs"] == identity_count
            and counts["all_publications"] == identity_count
            and counts["publications"] == identity_count
            and counts["all_receipts"] == identity_count
            and counts["receipts"] == identity_count
            and counts["all_memberships"] == identity_count
            and counts["memberships"] == identity_count
            and counts["heads"] == identity_count
            and counts["components"] == identity_count
            and counts["decisions"] == 0
            and counts["stage_errors"] == 0
            and counts["retry_events"] == expected_retries
            and counts["fallbacks"] == expected_fallbacks
            and counts["attempts"] == identity_count * len(StageName) + expected_retries
            and counts["identity_events"] == identity_count
            and counts["items_with_one_identity_event"] == identity_count
            and counts["publication_events"] == identity_count
            and counts["items_with_one_publication_event"] == identity_count
            and (not reopen_requested or metrics.reopen_count == 1)
        )
        if not exact:
            raise ScaleSimulationError(f"synthetic terminal invariant mismatch: {counts!r}")
        if elapsed <= 0:
            raise ScaleSimulationError("scale timing evidence is invalid")

        database_size = self.database.stat().st_size
        wal_path = self.database.with_name(self.database.name + "-wal")
        shm_path = self.database.with_name(self.database.name + "-shm")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0
        shm_size = shm_path.stat().st_size if shm_path.exists() else 0
        page_count = int(counts["page_count"])
        page_size = int(counts["page_size"])
        performance_target_seconds = _PERFORMANCE_TARGET_SECONDS
        return ScaleSimulationReport(
            scope=SYNTHETIC_SCALE_SCOPE,
            production_asset_proof=False,
            synthetic_external_effects=True,
            durability_profile=(
                "sqlite_wal_normal_process_reopen_simulation_not_production_power_loss_proof"
            ),
            identity_count=identity_count,
            batch_count=len(batches),
            item_count=identity_count,
            stage_count=identity_count * len(StageName),
            publication_count=identity_count,
            receipt_count=identity_count,
            retry_injection_count=expected_retries,
            fallback_injection_count=expected_fallbacks,
            stage_dispatch_count=metrics.stage_dispatches,
            claim_round_count=metrics.claim_rounds,
            publication_claim_round_count=metrics.publication_claim_rounds,
            claim_limit=self.claim_limit,
            worker_count=self.worker_count,
            workers_observed=len(self._workers_seen),
            max_stage_claims_in_flight=metrics.max_stage_claims,
            max_publication_claims_in_flight=metrics.max_publication_claims,
            store_reopen_count=metrics.reopen_count,
            reopened_after_stage_dispatches=metrics.reopened_after_dispatches,
            completed_items_at_reopen=metrics.completed_items_at_reopen,
            elapsed_seconds=elapsed,
            stage_dispatches_per_second=metrics.stage_dispatches / elapsed,
            performance_target_seconds=performance_target_seconds,
            performance_target_met=elapsed <= performance_target_seconds,
            optimization_hypothesis=(
                "indexed lease-expiry probes, atomic dependency-result reads, "
                "and aggregate status refreshes bound repeated ledger work"
            ),
            next_discriminating_optimization_target=(
                "profile transaction commit latency and claim-ready scheduling "
                "before weakening any durability invariant"
            ),
            database_file_size_bytes=database_size,
            database_wal_size_bytes=wal_size,
            database_shm_size_bytes=shm_size,
            database_total_storage_bytes=database_size + wal_size + shm_size,
            database_page_count=page_count,
            database_page_size_bytes=page_size,
            database_allocated_bytes=page_count * page_size,
            event_count=int(counts["events"]),
            terminal_exactly_once=True,
        )


__all__ = [
    "SYNTHETIC_SCALE_SCOPE",
    "ScaleSimulationError",
    "ScaleSimulationHarness",
    "ScaleSimulationReport",
]
