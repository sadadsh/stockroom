"""Versioned SQLite persistence for Stockroom's isolated workflow state machine.

Design choices kept intentionally small and reversible:

* The database is a durable operational journal, never the published library.
* Every public mutation is one ``BEGIN IMMEDIATE`` transaction.
* Optional idempotency keys bind to a canonical request digest, so concurrent
  client retries collapse to the first batch or fail on request mismatch.
* A fresh SQLite connection is used per operation, and a process-local writer
  lock avoids making worker threads contend inside SQLite for its single writer.
* Pausing stops new claims but lets an already leased worker finish.  Cancelling
  is immediate and invalidates every non-completed lease.  Long provider and CAD
  stages renew an owned, unexpired lease with explicit heartbeats.
* One blocked item never stalls the other items in its batch.  A batch reports
  ``blocked`` only when no remaining item can advance automatically.
* Provider misses and timeouts use persisted retries or terminal failures.  The
  only durable human decisions are exact identity and explicit safety questions.
* Publication completion and its receipt share one transaction.  Actual library
  mutation belongs to a later adapter and must happen before supplying that
  receipt.

The first migration is deliberately normalized and append-friendly.  Future
schema changes must add a numbered migration rather than rewriting existing rows.
"""

from __future__ import annotations

import hashlib
import math
import secrets
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from .identifiers import (
    authoritative_text,
    derive_component_identity,
    derive_publication_identity,
    digest_text,
    opaque_text,
    parse_sha256,
)
from .model import (
    BatchCancellationRecord,
    BatchCancellationState,
    BatchRecord,
    BatchStatus,
    ComponentPublicationReceipt,
    DecisionKind,
    DecisionRecord,
    DecisionStatus,
    IntakeIdentity,
    ItemComponentBinding,
    ItemRecord,
    ItemStatus,
    JsonValue,
    PublicationCompletionDisposition,
    PublicationLease,
    PublicationMembership,
    PublicationMembershipState,
    PublicationOperation,
    PublicationReceipt,
    PublicationState,
    ResolvedComponent,
    StageRecord,
    StageStatus,
    WorkflowConflict,
    WorkflowDataCorruption,
    WorkflowEvent,
    canonical_json,
    decode_json,
    new_opaque_id,
)
from .planner import WORKFLOW_GRAPH_VERSION, StageName, default_stage_plan
from .publication import RECONCILABLE_PUBLICATION_STATES, is_post_commit_fence

SCHEMA_VERSION = 4
BUSY_TIMEOUT_MS = 5000
MAX_BATCH_SIZE = 1000
MAX_CLAIM_LIMIT = 1000

_MIGRATION_1 = (
    """
    CREATE TABLE batches (
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK (
            status IN ('queued', 'running', 'blocked', 'paused',
                       'completed', 'failed', 'cancelled')
        ),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE items (
        id TEXT PRIMARY KEY,
        entry_id TEXT NOT NULL UNIQUE,
        batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        manufacturer TEXT NOT NULL,
        mpn TEXT NOT NULL,
        manufacturer_key TEXT NOT NULL,
        mpn_key TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        status TEXT NOT NULL CHECK (
            status IN ('queued', 'running', 'blocked',
                       'completed', 'failed', 'cancelled')
        ),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE (batch_id, ordinal)
    )
    """,
    """
    CREATE TABLE stages (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'ready', 'running', 'waiting_retry',
                       'blocked', 'completed', 'failed', 'cancelled')
        ),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        next_attempt_at REAL,
        lease_owner TEXT,
        lease_expires_at REAL,
        result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
        error_json TEXT CHECK (error_json IS NULL OR json_valid(error_json)),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE (item_id, name),
        UNIQUE (item_id, ordinal),
        CHECK (
            (status = 'running' AND lease_owner IS NOT NULL
                                AND lease_expires_at IS NOT NULL)
            OR
            (status <> 'running')
        )
    )
    """,
    """
    CREATE TABLE stage_dependencies (
        stage_id TEXT NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
        depends_on_stage_id TEXT NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
        PRIMARY KEY (stage_id, depends_on_stage_id),
        CHECK (stage_id <> depends_on_stage_id)
    )
    """,
    """
    CREATE TABLE events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
        item_id TEXT REFERENCES items(id) ON DELETE CASCADE,
        stage_id TEXT REFERENCES stages(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE decisions (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
        stage_id TEXT NOT NULL REFERENCES stages(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK (kind IN ('identity', 'safety')),
        status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'cancelled')),
        prompt_json TEXT NOT NULL CHECK (json_valid(prompt_json)),
        resolution_json TEXT CHECK (
            resolution_json IS NULL OR json_valid(resolution_json)
        ),
        created_at REAL NOT NULL,
        resolved_at REAL
    )
    """,
    """
    CREATE TABLE publication_receipts (
        id TEXT PRIMARY KEY,
        item_id TEXT NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
        stage_id TEXT NOT NULL UNIQUE REFERENCES stages(id) ON DELETE CASCADE,
        entry_id TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        created_at REAL NOT NULL
    )
    """,
    "CREATE INDEX idx_items_batch_status ON items(batch_id, status, ordinal)",
    "CREATE INDEX idx_stages_item_status ON stages(item_id, status, ordinal)",
    "CREATE INDEX idx_stages_claim ON stages(status, next_attempt_at, ordinal)",
    """
    CREATE INDEX idx_stage_dependencies_parent
    ON stage_dependencies(depends_on_stage_id, stage_id)
    """,
    "CREATE INDEX idx_events_batch_sequence ON events(batch_id, sequence)",
    "CREATE INDEX idx_decisions_item_status ON decisions(item_id, status)",
    """
    CREATE UNIQUE INDEX idx_one_open_decision_per_stage
    ON decisions(stage_id) WHERE status = 'open'
    """,
)

_MIGRATION_2 = (
    "ALTER TABLE batches ADD COLUMN idempotency_key TEXT",
    "ALTER TABLE batches ADD COLUMN request_digest TEXT",
    """
    CREATE UNIQUE INDEX idx_batches_idempotency_key
    ON batches(idempotency_key)
    WHERE idempotency_key IS NOT NULL
    """,
)

_MIGRATION_3 = (
    "ALTER TABLE stages ADD COLUMN lease_token TEXT",
    """
    ALTER TABLE stages
    ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
        CHECK (lease_generation >= 0)
    """,
    "UPDATE stages SET lease_generation = attempt_count",
    """
    UPDATE stages
    SET status = 'ready',
        lease_owner = NULL,
        lease_expires_at = NULL,
        next_attempt_at = NULL
    WHERE status = 'running'
    """,
    """
    CREATE UNIQUE INDEX idx_stages_lease_token
    ON stages(lease_token)
    WHERE lease_token IS NOT NULL
    """,
    """
    CREATE TRIGGER trg_stages_running_fence_insert
    BEFORE INSERT ON stages
    WHEN NEW.status = 'running'
         AND (NEW.lease_token IS NULL OR NEW.lease_generation <= 0)
    BEGIN
        SELECT RAISE(ABORT, 'running stage requires a lease fence');
    END
    """,
    """
    CREATE TRIGGER trg_stages_running_fence_update
    BEFORE UPDATE ON stages
    WHEN NEW.status = 'running'
         AND (NEW.lease_token IS NULL OR NEW.lease_generation <= 0)
    BEGIN
        SELECT RAISE(ABORT, 'running stage requires a lease fence');
    END
    """,
)

_MIGRATION_4 = (
    """
    ALTER TABLE items
    ADD COLUMN workflow_graph_version INTEGER NOT NULL DEFAULT 1
        CHECK (workflow_graph_version = 1)
    """,
    """
    CREATE TABLE resolved_manufacturers (
        manufacturer_id TEXT PRIMARY KEY,
        manufacturer_digest BLOB NOT NULL UNIQUE
            CHECK (typeof(manufacturer_digest) = 'blob'
                   AND length(manufacturer_digest) = 32),
        authoritative_key TEXT NOT NULL UNIQUE COLLATE BINARY
            CHECK (length(authoritative_key) > 0),
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE resolved_components (
        component_id TEXT PRIMARY KEY,
        identity_digest BLOB NOT NULL UNIQUE
            CHECK (typeof(identity_digest) = 'blob'
                   AND length(identity_digest) = 32),
        manufacturer_id TEXT NOT NULL
            REFERENCES resolved_manufacturers(manufacturer_id),
        mpn_canonical TEXT NOT NULL COLLATE BINARY
            CHECK (length(mpn_canonical) > 0),
        created_at REAL NOT NULL,
        UNIQUE (manufacturer_id, mpn_canonical)
    )
    """,
    """
    CREATE TABLE item_component_bindings (
        item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
        identity_stage_id TEXT NOT NULL UNIQUE
            REFERENCES stages(id) ON DELETE CASCADE,
        component_id TEXT NOT NULL REFERENCES resolved_components(component_id),
        resolution_json TEXT NOT NULL CHECK (json_valid(resolution_json)),
        resolved_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE publication_operations (
        publication_id TEXT PRIMARY KEY,
        publication_digest BLOB NOT NULL UNIQUE
            CHECK (typeof(publication_digest) = 'blob'
                   AND length(publication_digest) = 32),
        component_id TEXT NOT NULL REFERENCES resolved_components(component_id),
        candidate_digest BLOB NOT NULL
            CHECK (typeof(candidate_digest) = 'blob'
                   AND length(candidate_digest) = 32),
        manifest_digest BLOB NOT NULL
            CHECK (typeof(manifest_digest) = 'blob'
                   AND length(manifest_digest) = 32),
        expected_head_publication_id TEXT
            REFERENCES publication_operations(publication_id),
        expected_base_commit TEXT NOT NULL CHECK (length(expected_base_commit) > 0),
        state TEXT NOT NULL CHECK (
            state IN (
                'preparing', 'conflicted', 'commit_fenced', 'git_committed',
                'catalog_activated', 'completed', 'aborted'
            )
        ),
        lease_generation INTEGER NOT NULL DEFAULT 0
            CHECK (lease_generation >= 0),
        lease_owner TEXT,
        lease_expires_at REAL,
        lease_token TEXT,
        commit_fenced_at REAL,
        git_commit_oid TEXT,
        verified_tree_digest BLOB CHECK (
            verified_tree_digest IS NULL
            OR (
                typeof(verified_tree_digest) = 'blob'
                AND length(verified_tree_digest) = 32
            )
        ),
        catalog_revision TEXT,
        catalog_semantic_digest BLOB CHECK (
            catalog_semantic_digest IS NULL
            OR (
                typeof(catalog_semantic_digest) = 'blob'
                AND length(catalog_semantic_digest) = 32
            )
        ),
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        UNIQUE (component_id, candidate_digest),
        CHECK (
            (
                lease_owner IS NULL
                AND lease_expires_at IS NULL
                AND lease_token IS NULL
            )
            OR
            (
                lease_owner IS NOT NULL
                AND lease_expires_at IS NOT NULL
                AND lease_token IS NOT NULL
                AND lease_generation > 0
            )
        ),
        CHECK (
            (
                state IN ('preparing', 'conflicted', 'aborted')
                AND commit_fenced_at IS NULL
                AND git_commit_oid IS NULL
                AND verified_tree_digest IS NULL
                AND catalog_revision IS NULL
                AND catalog_semantic_digest IS NULL
            )
            OR
            (
                state = 'commit_fenced'
                AND commit_fenced_at IS NOT NULL
                AND git_commit_oid IS NULL
                AND verified_tree_digest IS NULL
                AND catalog_revision IS NULL
                AND catalog_semantic_digest IS NULL
            )
            OR
            (
                state = 'git_committed'
                AND commit_fenced_at IS NOT NULL
                AND git_commit_oid IS NOT NULL
                AND verified_tree_digest IS NOT NULL
                AND catalog_revision IS NULL
                AND catalog_semantic_digest IS NULL
            )
            OR
            (
                state IN ('catalog_activated', 'completed')
                AND commit_fenced_at IS NOT NULL
                AND git_commit_oid IS NOT NULL
                AND verified_tree_digest IS NOT NULL
                AND catalog_revision IS NOT NULL
                AND catalog_semantic_digest IS NOT NULL
            )
        )
    )
    """,
    """
    CREATE TABLE publication_memberships (
        item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
        publish_stage_id TEXT NOT NULL UNIQUE
            REFERENCES stages(id) ON DELETE CASCADE,
        publication_id TEXT NOT NULL
            REFERENCES publication_operations(publication_id),
        state TEXT NOT NULL CHECK (
            state IN ('waiting', 'cancelled', 'completed', 'conflict')
        ),
        cancel_after_fence INTEGER NOT NULL DEFAULT 0
            CHECK (cancel_after_fence IN (0, 1)),
        completion_disposition TEXT CHECK (
            completion_disposition IS NULL
            OR completion_disposition IN ('normal', 'completed_before_cancel')
        ),
        joined_at REAL NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE component_publication_heads (
        component_id TEXT PRIMARY KEY REFERENCES resolved_components(component_id),
        publication_id TEXT NOT NULL UNIQUE
            REFERENCES publication_operations(publication_id),
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE component_publication_receipts (
        publication_id TEXT PRIMARY KEY
            REFERENCES publication_operations(publication_id),
        component_id TEXT NOT NULL REFERENCES resolved_components(component_id),
        git_commit_oid TEXT NOT NULL CHECK (length(git_commit_oid) > 0),
        verified_tree_digest BLOB NOT NULL CHECK (
            typeof(verified_tree_digest) = 'blob'
            AND length(verified_tree_digest) = 32
        ),
        catalog_revision TEXT NOT NULL CHECK (length(catalog_revision) > 0),
        catalog_semantic_digest BLOB NOT NULL CHECK (
            typeof(catalog_semantic_digest) = 'blob'
            AND length(catalog_semantic_digest) = 32
        ),
        payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE batch_cancellations (
        batch_id TEXT PRIMARY KEY REFERENCES batches(id) ON DELETE CASCADE,
        state TEXT NOT NULL CHECK (state IN ('requested', 'completed')),
        reason_json TEXT NOT NULL CHECK (json_valid(reason_json)),
        requested_at REAL NOT NULL,
        completed_at REAL
    )
    """,
    """
    CREATE INDEX idx_item_component_bindings_component
    ON item_component_bindings(component_id, item_id)
    """,
    """
    CREATE INDEX idx_publication_operations_component_state
    ON publication_operations(component_id, state, created_at)
    """,
    """
    CREATE INDEX idx_publication_operations_claim
    ON publication_operations(state, lease_expires_at, created_at)
    """,
    """
    CREATE UNIQUE INDEX idx_publication_operations_lease_token
    ON publication_operations(lease_token)
    WHERE lease_token IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX idx_one_active_publication_per_component
    ON publication_operations(component_id)
    WHERE state IN (
        'preparing', 'commit_fenced', 'git_committed', 'catalog_activated'
    )
    """,
    """
    CREATE INDEX idx_publication_memberships_publication_state
    ON publication_memberships(publication_id, state, item_id)
    """,
    """
    CREATE INDEX idx_component_publication_receipts_component
    ON component_publication_receipts(component_id, publication_id)
    """,
    """
    CREATE INDEX idx_batch_cancellations_state
    ON batch_cancellations(state, requested_at)
    """,
    """
    CREATE TRIGGER trg_publication_lease_fence_insert
    BEFORE INSERT ON publication_operations
    WHEN NEW.lease_owner IS NOT NULL
         AND (
             NEW.lease_token IS NULL
             OR NEW.lease_expires_at IS NULL
             OR NEW.lease_generation <= 0
         )
    BEGIN
        SELECT RAISE(ABORT, 'publication lease requires a fence');
    END
    """,
    """
    CREATE TRIGGER trg_publication_lease_fence_update
    BEFORE UPDATE ON publication_operations
    WHEN NEW.lease_owner IS NOT NULL
         AND (
             NEW.lease_token IS NULL
             OR NEW.lease_expires_at IS NULL
             OR NEW.lease_generation <= 0
         )
    BEGIN
        SELECT RAISE(ABORT, 'publication lease requires a fence');
    END
    """,
    """
    CREATE TRIGGER trg_publication_expected_head_insert
    BEFORE INSERT ON publication_operations
    WHEN NEW.expected_head_publication_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1
             FROM publication_operations AS head
             WHERE head.publication_id = NEW.expected_head_publication_id
               AND head.component_id = NEW.component_id
               AND head.state = 'completed'
         )
    BEGIN
        SELECT RAISE(ABORT, 'publication expected head is not completed');
    END
    """,
    """
    CREATE TRIGGER trg_publication_expected_head_update
    BEFORE UPDATE OF expected_head_publication_id ON publication_operations
    WHEN NEW.expected_head_publication_id IS NOT NULL
         AND NOT EXISTS (
             SELECT 1
             FROM publication_operations AS head
             WHERE head.publication_id = NEW.expected_head_publication_id
               AND head.component_id = NEW.component_id
               AND head.state = 'completed'
         )
    BEGIN
        SELECT RAISE(ABORT, 'publication expected head is not completed');
    END
    """,
    """
    CREATE TRIGGER trg_component_head_insert
    BEFORE INSERT ON component_publication_heads
    WHEN NOT EXISTS (
        SELECT 1
        FROM publication_operations AS operation
        WHERE operation.publication_id = NEW.publication_id
          AND operation.component_id = NEW.component_id
          AND operation.state = 'completed'
    )
    BEGIN
        SELECT RAISE(ABORT, 'component head must reference completed publication');
    END
    """,
    """
    CREATE TRIGGER trg_component_head_update
    BEFORE UPDATE ON component_publication_heads
    WHEN NOT EXISTS (
        SELECT 1
        FROM publication_operations AS operation
        WHERE operation.publication_id = NEW.publication_id
          AND operation.component_id = NEW.component_id
          AND operation.state = 'completed'
    )
    BEGIN
        SELECT RAISE(ABORT, 'component head must reference completed publication');
    END
    """,
)

_MIGRATIONS = {
    1: _MIGRATION_1,
    2: _MIGRATION_2,
    3: _MIGRATION_3,
    4: _MIGRATION_4,
}

_BASE_TABLE_COLUMNS = {
    "schema_migrations": {"version", "applied_at"},
    "batches": {"id", "status", "created_at", "updated_at"},
    "items": {
        "id",
        "entry_id",
        "batch_id",
        "ordinal",
        "manufacturer",
        "mpn",
        "manufacturer_key",
        "mpn_key",
        "payload_json",
        "status",
        "created_at",
        "updated_at",
    },
    "stages": {
        "id",
        "item_id",
        "ordinal",
        "name",
        "status",
        "attempt_count",
        "next_attempt_at",
        "lease_owner",
        "lease_expires_at",
        "result_json",
        "error_json",
        "created_at",
        "updated_at",
    },
    "stage_dependencies": {"stage_id", "depends_on_stage_id"},
    "events": {
        "sequence",
        "batch_id",
        "item_id",
        "stage_id",
        "kind",
        "payload_json",
        "created_at",
    },
    "decisions": {
        "id",
        "item_id",
        "stage_id",
        "kind",
        "status",
        "prompt_json",
        "resolution_json",
        "created_at",
        "resolved_at",
    },
    "publication_receipts": {
        "id",
        "item_id",
        "stage_id",
        "entry_id",
        "payload_json",
        "created_at",
    },
}

_V4_TABLE_COLUMNS = {
    "resolved_manufacturers": {
        "manufacturer_id",
        "manufacturer_digest",
        "authoritative_key",
        "created_at",
    },
    "resolved_components": {
        "component_id",
        "identity_digest",
        "manufacturer_id",
        "mpn_canonical",
        "created_at",
    },
    "item_component_bindings": {
        "item_id",
        "identity_stage_id",
        "component_id",
        "resolution_json",
        "resolved_at",
    },
    "publication_operations": {
        "publication_id",
        "publication_digest",
        "component_id",
        "candidate_digest",
        "manifest_digest",
        "expected_head_publication_id",
        "expected_base_commit",
        "state",
        "lease_generation",
        "lease_owner",
        "lease_expires_at",
        "lease_token",
        "commit_fenced_at",
        "git_commit_oid",
        "verified_tree_digest",
        "catalog_revision",
        "catalog_semantic_digest",
        "created_at",
        "updated_at",
    },
    "publication_memberships": {
        "item_id",
        "publish_stage_id",
        "publication_id",
        "state",
        "cancel_after_fence",
        "completion_disposition",
        "joined_at",
        "updated_at",
    },
    "component_publication_heads": {
        "component_id",
        "publication_id",
        "updated_at",
    },
    "component_publication_receipts": {
        "publication_id",
        "component_id",
        "git_commit_oid",
        "verified_tree_digest",
        "catalog_revision",
        "catalog_semantic_digest",
        "payload_json",
        "created_at",
    },
    "batch_cancellations": {
        "batch_id",
        "state",
        "reason_json",
        "requested_at",
        "completed_at",
    },
}

# table, ordered columns, unique, partial
_INDEX_SPECS = {
    1: {
        "idx_items_batch_status": (
            "items",
            ("batch_id", "status", "ordinal"),
            False,
            False,
        ),
        "idx_stages_item_status": (
            "stages",
            ("item_id", "status", "ordinal"),
            False,
            False,
        ),
        "idx_stages_claim": (
            "stages",
            ("status", "next_attempt_at", "ordinal"),
            False,
            False,
        ),
        "idx_stage_dependencies_parent": (
            "stage_dependencies",
            ("depends_on_stage_id", "stage_id"),
            False,
            False,
        ),
        "idx_events_batch_sequence": (
            "events",
            ("batch_id", "sequence"),
            False,
            False,
        ),
        "idx_decisions_item_status": (
            "decisions",
            ("item_id", "status"),
            False,
            False,
        ),
        "idx_one_open_decision_per_stage": (
            "decisions",
            ("stage_id",),
            True,
            True,
        ),
    },
    2: {
        "idx_batches_idempotency_key": (
            "batches",
            ("idempotency_key",),
            True,
            True,
        ),
    },
    3: {
        "idx_stages_lease_token": (
            "stages",
            ("lease_token",),
            True,
            True,
        ),
    },
    4: {
        "idx_item_component_bindings_component": (
            "item_component_bindings",
            ("component_id", "item_id"),
            False,
            False,
        ),
        "idx_publication_operations_component_state": (
            "publication_operations",
            ("component_id", "state", "created_at"),
            False,
            False,
        ),
        "idx_publication_operations_claim": (
            "publication_operations",
            ("state", "lease_expires_at", "created_at"),
            False,
            False,
        ),
        "idx_publication_operations_lease_token": (
            "publication_operations",
            ("lease_token",),
            True,
            True,
        ),
        "idx_one_active_publication_per_component": (
            "publication_operations",
            ("component_id",),
            True,
            True,
        ),
        "idx_publication_memberships_publication_state": (
            "publication_memberships",
            ("publication_id", "state", "item_id"),
            False,
            False,
        ),
        "idx_component_publication_receipts_component": (
            "component_publication_receipts",
            ("component_id", "publication_id"),
            False,
            False,
        ),
        "idx_batch_cancellations_state": (
            "batch_cancellations",
            ("state", "requested_at"),
            False,
            False,
        ),
    },
}

_TRIGGERS_BY_VERSION = {
    3: {
        "trg_stages_running_fence_insert",
        "trg_stages_running_fence_update",
    },
    4: {
        "trg_component_head_insert",
        "trg_component_head_update",
        "trg_publication_expected_head_insert",
        "trg_publication_expected_head_update",
        "trg_publication_lease_fence_insert",
        "trg_publication_lease_fence_update",
    },
}

_STAGE_SELECT = """
    SELECT
        s.id,
        s.item_id,
        i.batch_id,
        i.entry_id,
        s.ordinal,
        s.name,
        s.status,
        s.attempt_count,
        s.next_attempt_at,
        s.lease_owner,
        s.lease_expires_at,
        s.lease_token,
        s.lease_generation,
        s.result_json,
        s.error_json,
        s.created_at,
        s.updated_at
    FROM stages AS s
    JOIN items AS i ON i.id = s.item_id
"""

_DECISION_SELECT = """
    SELECT
        d.id,
        d.item_id,
        d.stage_id,
        d.kind,
        d.status,
        d.prompt_json,
        d.resolution_json,
        d.created_at,
        d.resolved_at
    FROM decisions AS d
"""

_PERSISTED_DEPENDENCY_SELECT = """
    SELECT
        child.name AS child_name,
        parent.name AS parent_name,
        child.item_id AS child_item_id,
        parent.item_id AS parent_item_id
    FROM stage_dependencies AS dependency
    JOIN stages AS child ON child.id = dependency.stage_id
    JOIN stages AS parent ON parent.id = dependency.depends_on_stage_id
    WHERE child.item_id = ?
"""


class WorkflowStore:
    """Durable batch, item, stage, event, decision, and receipt storage."""

    def __init__(self, database: str | Path):
        if str(database) == ":memory:":
            raise ValueError("WorkflowStore requires a durable filesystem database")
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._writer_lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            isolation_level=None,
            timeout=BUSY_TIMEOUT_MS / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

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
        finally:
            connection.close()

    @contextmanager
    def _serialized_writing(self) -> Iterator[sqlite3.Connection]:
        """Enter one process-local SQLite writer without busy-lock contention.

        SQLite remains the cross-process authority.  This narrow lock only
        prevents threads sharing a store from racing for SQLite's single writer
        slot; subclasses may still select a different qualified connection
        lifecycle through ``_writing``.
        """

        with self._writer_lock:
            with self._writing() as connection:
                yield connection

    @staticmethod
    def _schema_columns(
        connection: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{table}")')}

    @classmethod
    def _verify_schema(cls, connection: sqlite3.Connection, version: int) -> None:
        """Reject a ledger that claims schema objects which are absent or altered."""

        objects = {
            (str(row["type"]), str(row["name"])): str(row["tbl_name"])
            for row in connection.execute(
                """
                SELECT type, name, tbl_name
                FROM sqlite_master
                WHERE type IN ('table', 'index', 'trigger')
                """
            )
        }

        expected_columns = {table: set(columns) for table, columns in _BASE_TABLE_COLUMNS.items()}
        if version >= 2:
            expected_columns["batches"].update({"idempotency_key", "request_digest"})
        if version >= 3:
            expected_columns["stages"].update({"lease_token", "lease_generation"})
        if version >= 4:
            expected_columns["items"].add("workflow_graph_version")
            expected_columns.update(
                {table: set(columns) for table, columns in _V4_TABLE_COLUMNS.items()}
            )

        for table, expected in expected_columns.items():
            if ("table", table) not in objects:
                raise WorkflowDataCorruption(
                    f"workflow schema ledger is missing required table {table!r}"
                )
            actual = cls._schema_columns(connection, table)
            if actual != expected:
                raise WorkflowDataCorruption(
                    f"workflow schema ledger does not match table {table!r}"
                )

        required_indexes = {
            name: spec
            for migration_version, specs in _INDEX_SPECS.items()
            if migration_version <= version
            for name, spec in specs.items()
        }
        for name, (table, columns, unique, partial) in required_indexes.items():
            if objects.get(("index", name)) != table:
                raise WorkflowDataCorruption(
                    f"workflow schema ledger is missing required index {name!r}"
                )
            index_rows = {
                str(row["name"]): row for row in connection.execute(f'PRAGMA index_list("{table}")')
            }
            index_row = index_rows.get(name)
            actual_columns = tuple(
                str(row["name"]) for row in connection.execute(f'PRAGMA index_info("{name}")')
            )
            if (
                index_row is None
                or bool(index_row["unique"]) is not unique
                or bool(index_row["partial"]) is not partial
                or actual_columns != columns
            ):
                raise WorkflowDataCorruption(
                    f"workflow schema ledger does not match index {name!r}"
                )

        required_triggers = {
            trigger
            for migration_version, triggers in _TRIGGERS_BY_VERSION.items()
            if migration_version <= version
            for trigger in triggers
        }
        for trigger in required_triggers:
            if ("trigger", trigger) not in objects:
                raise WorkflowDataCorruption(
                    f"workflow schema ledger is missing required trigger {trigger!r}"
                )

    @staticmethod
    def _verify_persisted_stage_graph(connection: sqlite3.Connection) -> None:
        """Fail closed when persisted work is not the accepted fourteen-node DAG."""

        plan = default_stage_plan()
        expected_stages = tuple((spec.ordinal, spec.name.value) for spec in plan)
        expected_dependencies = {
            (spec.name.value, dependency.value) for spec in plan for dependency in spec.dependencies
        }
        item_ids = [
            str(row["id"]) for row in connection.execute("SELECT id FROM items ORDER BY id")
        ]
        for item_id in item_ids:
            item_columns = WorkflowStore._schema_columns(connection, "items")
            if "workflow_graph_version" in item_columns:
                version_row = connection.execute(
                    """
                    SELECT workflow_graph_version FROM items WHERE id = ?
                    """,
                    (item_id,),
                ).fetchone()
                if version_row["workflow_graph_version"] != WORKFLOW_GRAPH_VERSION:
                    raise WorkflowDataCorruption(
                        "persisted workflow uses an unsupported graph version"
                    )
            actual_stages = tuple(
                (int(row["ordinal"]), str(row["name"]))
                for row in connection.execute(
                    """
                    SELECT ordinal, name
                    FROM stages
                    WHERE item_id = ?
                    ORDER BY ordinal, id
                    """,
                    (item_id,),
                )
            )
            if actual_stages != expected_stages:
                raise WorkflowDataCorruption(
                    "persisted workflow uses an unsupported stage graph; "
                    f"item {item_id!r} was refused without migration"
                )

            dependency_rows = connection.execute(
                _PERSISTED_DEPENDENCY_SELECT,
                (item_id,),
            ).fetchall()
            if any(
                row["child_item_id"] != item_id or row["parent_item_id"] != item_id
                for row in dependency_rows
            ):
                raise WorkflowDataCorruption(
                    "persisted workflow contains a cross-item stage dependency"
                )
            actual_dependencies = {
                (str(row["child_name"]), str(row["parent_name"])) for row in dependency_rows
            }
            if actual_dependencies != expected_dependencies:
                raise WorkflowDataCorruption(
                    "persisted workflow uses unsupported stage dependencies; "
                    f"item {item_id!r} was refused without migration"
                )

    @classmethod
    def _read_schema_ledger(
        cls,
        connection: sqlite3.Connection,
    ) -> list[int]:
        if cls._schema_columns(connection, "schema_migrations") != {
            "version",
            "applied_at",
        }:
            raise WorkflowDataCorruption("workflow schema migration ledger has an invalid shape")
        rows = connection.execute(
            """
            SELECT version, applied_at
            FROM schema_migrations
            ORDER BY version
            """
        ).fetchall()
        versions = [int(row["version"]) for row in rows]
        if versions != list(range(1, len(versions) + 1)):
            raise WorkflowDataCorruption("workflow schema migration ledger is not contiguous")
        for row in rows:
            try:
                applied_at = float(row["applied_at"])
            except (TypeError, ValueError) as exc:
                raise WorkflowDataCorruption(
                    "workflow schema migration ledger has an invalid timestamp"
                ) from exc
            if not math.isfinite(applied_at):
                raise WorkflowDataCorruption(
                    "workflow schema migration ledger has an invalid timestamp"
                )
        return versions

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).casefold() != "wal":
                raise RuntimeError(f"SQLite refused WAL mode: {journal_mode!r}")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY CHECK (version > 0),
                    applied_at REAL NOT NULL
                )
                """
            )
            versions = self._read_schema_ledger(connection)
            current = versions[-1] if versions else 0
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"workflow schema {current} is newer than supported {SCHEMA_VERSION}"
                )

            if current:
                self._verify_schema(connection, current)
                self._verify_persisted_stage_graph(connection)
            for version in range(current + 1, SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS[version]:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, time.time()),
                )
                self._verify_schema(connection, version)
            if current < SCHEMA_VERSION:
                self._verify_persisted_stage_graph(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _finite_number(value: float, name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite number") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        return number

    @classmethod
    def _timestamp(cls, now: float | None) -> float:
        return cls._finite_number(
            time.time() if now is None else now,
            "timestamp",
        )

    @staticmethod
    def _lease_credentials(
        lease_token: str,
        lease_generation: int,
    ) -> tuple[str, int]:
        if not isinstance(lease_token, str) or not lease_token:
            raise ValueError("lease_token must not be blank")
        if (
            isinstance(lease_generation, bool)
            or not isinstance(lease_generation, int)
            or lease_generation <= 0
        ):
            raise ValueError("lease_generation must be a positive integer")
        return lease_token, lease_generation

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> BatchRecord:
        return BatchRecord(
            id=row["id"],
            status=BatchStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> ItemRecord:
        return ItemRecord(
            id=row["id"],
            entry_id=row["entry_id"],
            batch_id=row["batch_id"],
            ordinal=row["ordinal"],
            workflow_graph_version=(
                row["workflow_graph_version"]
                if "workflow_graph_version" in row.keys()
                else WORKFLOW_GRAPH_VERSION
            ),
            manufacturer=row["manufacturer"],
            mpn=row["mpn"],
            manufacturer_key=row["manufacturer_key"],
            mpn_key=row["mpn_key"],
            payload=decode_json(row["payload_json"]),
            status=ItemStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _stage_from_row(row: sqlite3.Row) -> StageRecord:
        return StageRecord(
            id=row["id"],
            item_id=row["item_id"],
            batch_id=row["batch_id"],
            entry_id=row["entry_id"],
            ordinal=row["ordinal"],
            name=StageName(row["name"]),
            status=StageStatus(row["status"]),
            attempt_count=row["attempt_count"],
            next_attempt_at=row["next_attempt_at"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            lease_token=row["lease_token"],
            lease_generation=row["lease_generation"],
            result=decode_json(row["result_json"]),
            error=decode_json(row["error_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> DecisionRecord:
        return DecisionRecord(
            id=row["id"],
            item_id=row["item_id"],
            stage_id=row["stage_id"],
            kind=DecisionKind(row["kind"]),
            status=DecisionStatus(row["status"]),
            prompt=decode_json(row["prompt_json"]),
            resolution=decode_json(row["resolution_json"]),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> PublicationReceipt:
        return PublicationReceipt(
            id=row["id"],
            item_id=row["item_id"],
            stage_id=row["stage_id"],
            entry_id=row["entry_id"],
            payload=decode_json(row["payload_json"]),
            created_at=row["created_at"],
        )

    @classmethod
    def _resolved_component_from_row(cls, row: sqlite3.Row) -> ResolvedComponent:
        return ResolvedComponent(
            component_id=row["component_id"],
            identity_digest=digest_text(bytes(row["identity_digest"])),
            manufacturer_id=row["manufacturer_id"],
            manufacturer_digest=digest_text(bytes(row["manufacturer_digest"])),
            authoritative_manufacturer_key=row["authoritative_key"],
            mpn_canonical=row["mpn_canonical"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _binding_from_row(row: sqlite3.Row) -> ItemComponentBinding:
        return ItemComponentBinding(
            item_id=row["item_id"],
            identity_stage_id=row["identity_stage_id"],
            component_id=row["component_id"],
            resolution=decode_json(row["resolution_json"]),
            resolved_at=row["resolved_at"],
        )

    @classmethod
    def _publication_from_row(cls, row: sqlite3.Row) -> PublicationOperation:
        return PublicationOperation(
            publication_id=row["publication_id"],
            component_id=row["component_id"],
            candidate_digest=digest_text(bytes(row["candidate_digest"])),
            manifest_digest=digest_text(bytes(row["manifest_digest"])),
            expected_head_publication_id=row["expected_head_publication_id"],
            expected_base_commit=row["expected_base_commit"],
            state=PublicationState(row["state"]),
            lease_generation=row["lease_generation"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            commit_fenced_at=row["commit_fenced_at"],
            git_commit_oid=row["git_commit_oid"],
            verified_tree_digest=(
                None
                if row["verified_tree_digest"] is None
                else digest_text(bytes(row["verified_tree_digest"]))
            ),
            catalog_revision=row["catalog_revision"],
            catalog_semantic_digest=(
                None
                if row["catalog_semantic_digest"] is None
                else digest_text(bytes(row["catalog_semantic_digest"]))
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _publication_lease_from_row(row: sqlite3.Row) -> PublicationLease:
        if (
            row["lease_owner"] is None
            or row["lease_token"] is None
            or row["lease_expires_at"] is None
        ):
            raise WorkflowDataCorruption("claimed publication is missing its lease fence")
        return PublicationLease(
            publication_id=row["publication_id"],
            component_id=row["component_id"],
            state=PublicationState(row["state"]),
            worker_id=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_generation=row["lease_generation"],
            lease_expires_at=row["lease_expires_at"],
        )

    @staticmethod
    def _membership_from_row(row: sqlite3.Row) -> PublicationMembership:
        disposition = row["completion_disposition"]
        return PublicationMembership(
            item_id=row["item_id"],
            publish_stage_id=row["publish_stage_id"],
            publication_id=row["publication_id"],
            state=PublicationMembershipState(row["state"]),
            cancel_after_fence=bool(row["cancel_after_fence"]),
            completion_disposition=(
                None if disposition is None else PublicationCompletionDisposition(disposition)
            ),
            joined_at=row["joined_at"],
            updated_at=row["updated_at"],
        )

    @classmethod
    def _component_receipt_from_row(
        cls,
        row: sqlite3.Row,
    ) -> ComponentPublicationReceipt:
        return ComponentPublicationReceipt(
            publication_id=row["publication_id"],
            component_id=row["component_id"],
            git_commit_oid=row["git_commit_oid"],
            verified_tree_digest=digest_text(bytes(row["verified_tree_digest"])),
            catalog_revision=row["catalog_revision"],
            catalog_semantic_digest=digest_text(bytes(row["catalog_semantic_digest"])),
            payload=decode_json(row["payload_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _batch_cancellation_from_row(
        row: sqlite3.Row,
    ) -> BatchCancellationRecord:
        return BatchCancellationRecord(
            batch_id=row["batch_id"],
            state=BatchCancellationState(row["state"]),
            reason=decode_json(row["reason_json"]),
            requested_at=row["requested_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _emit(
        connection: sqlite3.Connection,
        *,
        batch_id: str,
        kind: str,
        now: float,
        payload: object,
        item_id: str | None = None,
        stage_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(
                batch_id, item_id, stage_id, kind, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                item_id,
                stage_id,
                kind,
                canonical_json(payload),
                now,
            ),
        )

    @staticmethod
    def _require_batch_row(
        connection: sqlite3.Connection,
        batch_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM batches WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return row

    @staticmethod
    def _require_stage_row(
        connection: sqlite3.Connection,
        stage_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            f"{_STAGE_SELECT} WHERE s.id = ?",
            (stage_id,),
        ).fetchone()
        if row is None:
            raise KeyError(stage_id)
        return row

    @staticmethod
    def _require_decision_row(
        connection: sqlite3.Connection,
        decision_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            f"{_DECISION_SELECT} WHERE d.id = ?",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        return row

    @staticmethod
    def _require_resolved_component_row(
        connection: sqlite3.Connection,
        component_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT
                component.component_id,
                component.identity_digest,
                component.manufacturer_id,
                manufacturer.manufacturer_digest,
                manufacturer.authoritative_key,
                component.mpn_canonical,
                component.created_at
            FROM resolved_components AS component
            JOIN resolved_manufacturers AS manufacturer
              ON manufacturer.manufacturer_id = component.manufacturer_id
            WHERE component.component_id = ?
            """,
            (component_id,),
        ).fetchone()
        if row is None:
            raise KeyError(component_id)
        return row

    @staticmethod
    def _require_binding_row(
        connection: sqlite3.Connection,
        item_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM item_component_bindings WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return row

    @staticmethod
    def _require_publication_row(
        connection: sqlite3.Connection,
        publication_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM publication_operations WHERE publication_id = ?",
            (publication_id,),
        ).fetchone()
        if row is None:
            raise KeyError(publication_id)
        return row

    @staticmethod
    def _require_membership_row(
        connection: sqlite3.Connection,
        item_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM publication_memberships WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return row

    @staticmethod
    def _require_publication_lease(
        row: sqlite3.Row,
        worker_id: str,
        lease_token: str,
        lease_generation: int,
        now: float,
    ) -> None:
        if row["lease_owner"] != worker_id:
            raise WorkflowConflict("publication is leased by another worker")
        if row["lease_token"] != lease_token or row["lease_generation"] != lease_generation:
            raise WorkflowConflict("publication lease fence is stale")
        if row["lease_expires_at"] is None or row["lease_expires_at"] <= now:
            raise WorkflowConflict("publication lease has expired")

    @classmethod
    def _emit_to_publication_members(
        cls,
        connection: sqlite3.Connection,
        *,
        publication_id: str,
        kind: str,
        now: float,
        payload: object,
    ) -> None:
        rows = connection.execute(
            """
            SELECT
                membership.item_id,
                membership.publish_stage_id,
                item.batch_id
            FROM publication_memberships AS membership
            JOIN items AS item ON item.id = membership.item_id
            WHERE membership.publication_id = ?
            ORDER BY item.batch_id, item.ordinal
            """,
            (publication_id,),
        ).fetchall()
        for row in rows:
            cls._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=row["publish_stage_id"],
                kind=kind,
                now=now,
                payload=payload,
            )

    def submit_batch(
        self,
        identities: Sequence[IntakeIdentity],
        *,
        idempotency_key: str | None = None,
        now: float | None = None,
    ) -> BatchRecord:
        """Atomically persist a batch of one through one thousand identities.

        An optional opaque idempotency key makes client retries safe.  The key
        binds to a digest of the exact ordered request, including raw identity
        text and JSON payloads.  A retry returns the first batch without adding
        events; reusing the key for any different request is a conflict.
        """

        submitted = tuple(identities)
        if not 1 <= len(submitted) <= MAX_BATCH_SIZE:
            raise ValueError("a batch must contain between 1 and 1000 identities")
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str):
                raise TypeError("idempotency_key must be a string")
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be blank")

        encoded: list[tuple[IntakeIdentity, str]] = []
        for identity in submitted:
            if not isinstance(identity, IntakeIdentity):
                raise TypeError("batch entries must be IntakeIdentity values")
            if not identity.mpn_key:
                raise ValueError("MPN must not be blank")
            encoded.append((identity, canonical_json(dict(identity.payload))))

        request_document = {
            "format": "stockroom-intake-v1",
            "identities": [
                {
                    "manufacturer": identity.manufacturer,
                    "mpn": identity.mpn,
                    "payload": decode_json(payload_json),
                }
                for identity, payload_json in encoded
            ],
        }
        request_json = canonical_json(request_document)
        request_digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        timestamp = self._timestamp(now)
        batch_id = new_opaque_id()
        plan = default_stage_plan()

        with self._serialized_writing() as connection:
            if idempotency_key is not None:
                existing = connection.execute(
                    "SELECT * FROM batches WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["request_digest"] != request_digest:
                        raise WorkflowConflict(
                            "idempotency key was already used for a different request"
                        )
                    return self._batch_from_row(existing)

            connection.execute(
                """
                INSERT INTO batches(
                    id, status, created_at, updated_at,
                    idempotency_key, request_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    BatchStatus.QUEUED.value,
                    timestamp,
                    timestamp,
                    idempotency_key,
                    request_digest,
                ),
            )
            self._emit(
                connection,
                batch_id=batch_id,
                kind="batch_submitted",
                now=timestamp,
                payload={"item_count": len(encoded)},
            )

            for ordinal, (identity, payload_json) in enumerate(encoded):
                item_id = new_opaque_id()
                entry_id = new_opaque_id()
                connection.execute(
                    """
                    INSERT INTO items(
                        id, entry_id, batch_id, ordinal,
                        workflow_graph_version,
                        manufacturer, mpn, manufacturer_key, mpn_key,
                        payload_json, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        entry_id,
                        batch_id,
                        ordinal,
                        WORKFLOW_GRAPH_VERSION,
                        identity.manufacturer,
                        identity.mpn,
                        identity.manufacturer_key,
                        identity.mpn_key,
                        payload_json,
                        ItemStatus.QUEUED.value,
                        timestamp,
                        timestamp,
                    ),
                )
                self._emit(
                    connection,
                    batch_id=batch_id,
                    item_id=item_id,
                    kind="item_submitted",
                    now=timestamp,
                    payload={"entry_id": entry_id, "ordinal": ordinal},
                )

                stage_ids: dict[StageName, str] = {}
                for spec in plan:
                    stage_id = new_opaque_id()
                    stage_ids[spec.name] = stage_id
                    status = StageStatus.READY if not spec.dependencies else StageStatus.PENDING
                    connection.execute(
                        """
                        INSERT INTO stages(
                            id, item_id, ordinal, name, status,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stage_id,
                            item_id,
                            spec.ordinal,
                            spec.name.value,
                            status.value,
                            timestamp,
                            timestamp,
                        ),
                    )
                    if status is StageStatus.READY:
                        self._emit(
                            connection,
                            batch_id=batch_id,
                            item_id=item_id,
                            stage_id=stage_id,
                            kind="stage_ready",
                            now=timestamp,
                            payload={"stage": spec.name.value},
                        )

                for spec in plan:
                    for dependency in spec.dependencies:
                        connection.execute(
                            """
                            INSERT INTO stage_dependencies(
                                stage_id, depends_on_stage_id
                            ) VALUES (?, ?)
                            """,
                            (stage_ids[spec.name], stage_ids[dependency]),
                        )

            row = self._require_batch_row(connection, batch_id)
            return self._batch_from_row(row)

    def get_batch(self, batch_id: str) -> BatchRecord:
        with self._reading() as connection:
            return self._batch_from_row(self._require_batch_row(connection, batch_id))

    def count_batches(self) -> int:
        with self._reading() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0])

    def list_items(self, batch_id: str) -> list[ItemRecord]:
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            rows = connection.execute(
                "SELECT * FROM items WHERE batch_id = ? ORDER BY ordinal",
                (batch_id,),
            ).fetchall()
            return [self._item_from_row(row) for row in rows]

    def item_status_counts(self, batch_id: str) -> dict[ItemStatus, int]:
        """Return one bounded aggregate query for a batch's UI projection."""

        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM items
                WHERE batch_id = ?
                GROUP BY status
                """,
                (batch_id,),
            ).fetchall()
            return {ItemStatus(row["status"]): int(row["count"]) for row in rows}

    def get_item(self, item_id: str) -> ItemRecord:
        with self._reading() as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(item_id)
            return self._item_from_row(row)

    def resolve_exact_identity(
        self,
        stage_id: str,
        worker_id: str,
        *,
        authoritative_manufacturer_key: str,
        mpn_canonical: str,
        registry_revision: str,
        rule_revision: str,
        evidence: object,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> ItemComponentBinding:
        """Bind one intake membership to an exact deterministic Component ID."""

        manufacturer_key = authoritative_text(
            authoritative_manufacturer_key,
            "authoritative_manufacturer_key",
        )
        canonical_mpn = authoritative_text(mpn_canonical, "mpn_canonical")
        registry = opaque_text(registry_revision, "registry_revision")
        rule = opaque_text(rule_revision, "rule_revision")
        evidence_json = canonical_json(evidence)
        resolution_json = canonical_json(
            {
                "evidence": decode_json(evidence_json),
                "registry_revision": registry,
                "rule_revision": rule,
            }
        )
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        derived = derive_component_identity(manufacturer_key, canonical_mpn)
        result_json = canonical_json(
            {
                "component_id": derived.component_id,
                "identity_digest": digest_text(derived.component_digest),
                "manufacturer_id": derived.manufacturer_id,
            }
        )
        timestamp = self._timestamp(now)

        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            stage = self._require_stage_row(connection, stage_id)
            if StageName(stage["name"]) is not StageName.IDENTITY_DEDUPE:
                raise ValueError("exact identity resolution belongs to identity_dedupe")
            status = StageStatus(stage["status"])
            if status is StageStatus.COMPLETED:
                if stage["lease_token"] != token or stage["lease_generation"] != generation:
                    raise WorkflowConflict("stage lease fence is stale")
                if stage["result_json"] != result_json:
                    raise WorkflowDataCorruption(
                        "completed identity stage conflicts with its exact binding"
                    )
                binding = self._require_binding_row(
                    connection,
                    stage["item_id"],
                )
                if (
                    binding["component_id"] != derived.component_id
                    or binding["resolution_json"] != resolution_json
                ):
                    raise WorkflowDataCorruption(
                        "item identity replay conflicts with its persisted binding"
                    )
                return self._binding_from_row(binding)

            batch = self._require_batch_row(connection, stage["batch_id"])
            if BatchStatus(batch["status"]) is BatchStatus.CANCELLED:
                raise WorkflowConflict("stage or batch is cancelled")
            cancellation = connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (stage["batch_id"], BatchCancellationState.REQUESTED.value),
            ).fetchone()
            if cancellation is not None:
                raise WorkflowConflict("stage or batch is cancelled")
            self._require_running_lease(
                stage,
                worker_id,
                token,
                generation,
            )

            connection.execute(
                """
                INSERT OR IGNORE INTO resolved_manufacturers(
                    manufacturer_id, manufacturer_digest,
                    authoritative_key, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    derived.manufacturer_id,
                    derived.manufacturer_digest,
                    manufacturer_key,
                    timestamp,
                ),
            )
            manufacturer = connection.execute(
                """
                SELECT * FROM resolved_manufacturers
                WHERE manufacturer_id = ?
                """,
                (derived.manufacturer_id,),
            ).fetchone()
            if manufacturer is None or (
                bytes(manufacturer["manufacturer_digest"]) != derived.manufacturer_digest
                or manufacturer["authoritative_key"] != manufacturer_key
            ):
                raise WorkflowDataCorruption("deterministic manufacturer identity collision")

            connection.execute(
                """
                INSERT OR IGNORE INTO resolved_components(
                    component_id, identity_digest, manufacturer_id,
                    mpn_canonical, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    derived.component_id,
                    derived.component_digest,
                    derived.manufacturer_id,
                    canonical_mpn,
                    timestamp,
                ),
            )
            component = connection.execute(
                "SELECT * FROM resolved_components WHERE component_id = ?",
                (derived.component_id,),
            ).fetchone()
            if component is None or (
                bytes(component["identity_digest"]) != derived.component_digest
                or component["manufacturer_id"] != derived.manufacturer_id
                or component["mpn_canonical"] != canonical_mpn
            ):
                raise WorkflowDataCorruption("deterministic component identity collision")

            connection.execute(
                """
                INSERT OR IGNORE INTO item_component_bindings(
                    item_id, identity_stage_id, component_id,
                    resolution_json, resolved_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    stage["item_id"],
                    stage_id,
                    derived.component_id,
                    resolution_json,
                    timestamp,
                ),
            )
            binding = connection.execute(
                """
                SELECT * FROM item_component_bindings
                WHERE item_id = ?
                """,
                (stage["item_id"],),
            ).fetchone()
            if binding is None or (
                binding["identity_stage_id"] != stage_id
                or binding["component_id"] != derived.component_id
                or binding["resolution_json"] != resolution_json
            ):
                raise WorkflowDataCorruption(
                    "item is already bound to a conflicting component identity"
                )

            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, result_json = ?, error_json = NULL,
                    next_attempt_at = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.COMPLETED.value,
                    result_json,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=stage["batch_id"],
                item_id=stage["item_id"],
                stage_id=stage_id,
                kind="identity_resolved",
                now=timestamp,
                payload={
                    "component_id": derived.component_id,
                    "manufacturer_id": derived.manufacturer_id,
                },
            )
            self._emit(
                connection,
                batch_id=stage["batch_id"],
                item_id=stage["item_id"],
                stage_id=stage_id,
                kind="stage_completed",
                now=timestamp,
                payload={
                    "attempt": stage["attempt_count"],
                    "stage": stage["name"],
                },
            )
            self._promote_dependencies(
                connection,
                stage["item_id"],
                timestamp,
            )
            self._refresh_items_and_batches(
                connection,
                {stage["item_id"]},
                timestamp,
            )
            return self._binding_from_row(binding)

    def get_item_component(
        self,
        item_id: str,
    ) -> ItemComponentBinding | None:
        with self._reading() as connection:
            item = connection.execute(
                "SELECT 1 FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            row = connection.execute(
                "SELECT * FROM item_component_bindings WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            return None if row is None else self._binding_from_row(row)

    def get_resolved_component(self, component_id: str) -> ResolvedComponent:
        with self._reading() as connection:
            return self._resolved_component_from_row(
                self._require_resolved_component_row(connection, component_id)
            )

    def list_component_memberships(
        self,
        component_id: str,
    ) -> list[ItemComponentBinding]:
        with self._reading() as connection:
            self._require_resolved_component_row(connection, component_id)
            rows = connection.execute(
                """
                SELECT * FROM item_component_bindings
                WHERE component_id = ?
                ORDER BY resolved_at, item_id
                """,
                (component_id,),
            ).fetchall()
            return [self._binding_from_row(row) for row in rows]

    def list_stages(self, item_id: str) -> list[StageRecord]:
        with self._reading() as connection:
            rows = connection.execute(
                f"{_STAGE_SELECT} WHERE s.item_id = ? ORDER BY s.ordinal",
                (item_id,),
            ).fetchall()
            if not rows:
                item = connection.execute(
                    "SELECT 1 FROM items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                if item is None:
                    raise KeyError(item_id)
            return [self._stage_from_row(row) for row in rows]

    def join_publication(
        self,
        stage_id: str,
        worker_id: str,
        *,
        candidate_digest: str,
        manifest_digest: str,
        expected_base_commit: str,
        lease_token: str,
        lease_generation: int,
        expected_head_publication_id: str | None = None,
        now: float | None = None,
    ) -> PublicationMembership:
        """Join one publish stage to the component-global publication arbiter."""

        candidate = parse_sha256(candidate_digest, "candidate_digest")
        manifest = parse_sha256(manifest_digest, "manifest_digest")
        base_commit = opaque_text(expected_base_commit, "expected_base_commit")
        expected_head = (
            None
            if expected_head_publication_id is None
            else opaque_text(
                expected_head_publication_id,
                "expected_head_publication_id",
            )
        )
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)

        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            stage = self._require_stage_row(connection, stage_id)
            if StageName(stage["name"]) is not StageName.PUBLISH:
                raise ValueError("publication membership belongs to publish")

            existing_membership = connection.execute(
                """
                SELECT * FROM publication_memberships
                WHERE item_id = ?
                """,
                (stage["item_id"],),
            ).fetchone()
            if existing_membership is not None:
                if stage["lease_token"] != token or stage["lease_generation"] != generation:
                    raise WorkflowConflict("stage lease fence is stale")
                operation = self._require_publication_row(
                    connection,
                    existing_membership["publication_id"],
                )
                component = self._require_resolved_component_row(
                    connection,
                    operation["component_id"],
                )
                derived = derive_publication_identity(
                    bytes(component["identity_digest"]),
                    candidate,
                )
                if (
                    derived.publication_id != operation["publication_id"]
                    or bytes(operation["candidate_digest"]) != candidate
                ):
                    raise WorkflowDataCorruption("deterministic publication identity collision")
                if (
                    bytes(operation["manifest_digest"]) != manifest
                    or operation["expected_base_commit"] != base_commit
                    or operation["expected_head_publication_id"] != expected_head
                ):
                    raise WorkflowConflict("publish stage replay differs from its publication plan")
                return self._membership_from_row(existing_membership)

            batch = self._require_batch_row(connection, stage["batch_id"])
            if BatchStatus(batch["status"]) is BatchStatus.CANCELLED:
                raise WorkflowConflict("stage or batch is cancelled")
            if connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (stage["batch_id"], BatchCancellationState.REQUESTED.value),
            ).fetchone():
                raise WorkflowConflict("stage or batch is cancelled")
            self._require_running_lease(
                stage,
                worker_id,
                token,
                generation,
            )

            binding = connection.execute(
                """
                SELECT binding.*, component.identity_digest
                FROM item_component_bindings AS binding
                JOIN resolved_components AS component
                  ON component.component_id = binding.component_id
                WHERE binding.item_id = ?
                """,
                (stage["item_id"],),
            ).fetchone()
            if binding is None:
                raise WorkflowConflict("publish stage has no exact component identity binding")
            derived = derive_publication_identity(
                bytes(binding["identity_digest"]),
                candidate,
            )

            head = connection.execute(
                """
                SELECT head.publication_id, operation.candidate_digest
                FROM component_publication_heads AS head
                JOIN publication_operations AS operation
                  ON operation.publication_id = head.publication_id
                WHERE head.component_id = ?
                """,
                (binding["component_id"],),
            ).fetchone()
            if head is None and expected_head is not None:
                raise WorkflowConflict("component publication head does not exist")
            if head is not None:
                if (
                    head["publication_id"] == derived.publication_id
                    and bytes(head["candidate_digest"]) == candidate
                ):
                    pass
                elif expected_head != head["publication_id"]:
                    raise WorkflowConflict("component publication head changed; replan explicitly")

            operation = connection.execute(
                """
                SELECT * FROM publication_operations
                WHERE publication_id = ?
                """,
                (derived.publication_id,),
            ).fetchone()
            membership_state = PublicationMembershipState.WAITING
            if operation is None:
                active = connection.execute(
                    """
                    SELECT * FROM publication_operations
                    WHERE component_id = ?
                      AND state IN (
                          'preparing', 'commit_fenced',
                          'git_committed', 'catalog_activated'
                      )
                    """,
                    (binding["component_id"],),
                ).fetchone()
                operation_state = PublicationState.PREPARING
                if active is not None:
                    operation_state = PublicationState.CONFLICTED
                    membership_state = PublicationMembershipState.CONFLICT
                    if PublicationState(active["state"]) is PublicationState.PREPARING:
                        connection.execute(
                            """
                            UPDATE publication_operations
                            SET state = ?, lease_owner = NULL,
                                lease_expires_at = NULL, lease_token = NULL,
                                updated_at = ?
                            WHERE publication_id = ? AND state = ?
                            """,
                            (
                                PublicationState.CONFLICTED.value,
                                timestamp,
                                active["publication_id"],
                                PublicationState.PREPARING.value,
                            ),
                        )
                        connection.execute(
                            """
                            UPDATE publication_memberships
                            SET state = ?, updated_at = ?
                            WHERE publication_id = ? AND state = ?
                            """,
                            (
                                PublicationMembershipState.CONFLICT.value,
                                timestamp,
                                active["publication_id"],
                                PublicationMembershipState.WAITING.value,
                            ),
                        )

                connection.execute(
                    """
                    INSERT INTO publication_operations(
                        publication_id, publication_digest, component_id,
                        candidate_digest, manifest_digest,
                        expected_head_publication_id, expected_base_commit,
                        state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        derived.publication_id,
                        derived.publication_digest,
                        binding["component_id"],
                        candidate,
                        manifest,
                        expected_head,
                        base_commit,
                        operation_state.value,
                        timestamp,
                        timestamp,
                    ),
                )
                operation = self._require_publication_row(
                    connection,
                    derived.publication_id,
                )
            else:
                if (
                    operation["component_id"] != binding["component_id"]
                    or bytes(operation["publication_digest"]) != derived.publication_digest
                    or bytes(operation["candidate_digest"]) != candidate
                ):
                    raise WorkflowDataCorruption("deterministic publication identity collision")
                if (
                    bytes(operation["manifest_digest"]) != manifest
                    or operation["expected_head_publication_id"] != expected_head
                    or operation["expected_base_commit"] != base_commit
                ):
                    raise WorkflowConflict(
                        "publication plan differs; replan before the commit fence"
                    )
                if PublicationState(operation["state"]) is PublicationState.ABORTED:
                    raise WorkflowConflict("publication operation was aborted")
                if PublicationState(operation["state"]) is PublicationState.CONFLICTED:
                    membership_state = PublicationMembershipState.CONFLICT

            connection.execute(
                """
                INSERT INTO publication_memberships(
                    item_id, publish_stage_id, publication_id,
                    state, joined_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    stage["item_id"],
                    stage_id,
                    derived.publication_id,
                    membership_state.value,
                    timestamp,
                    timestamp,
                ),
            )

            if PublicationState(operation["state"]) is PublicationState.COMPLETED:
                receipt = connection.execute(
                    """
                    SELECT 1 FROM component_publication_receipts
                    WHERE publication_id = ?
                    """,
                    (derived.publication_id,),
                ).fetchone()
                if receipt is None:
                    raise WorkflowDataCorruption("completed publication has no global receipt")
                completed_head = connection.execute(
                    """
                    SELECT publication_id
                    FROM component_publication_heads
                    WHERE component_id = ?
                    """,
                    (binding["component_id"],),
                ).fetchone()
                if (
                    completed_head is None
                    or completed_head["publication_id"] != derived.publication_id
                ):
                    raise WorkflowDataCorruption("completed publication is not the component head")
                connection.execute(
                    """
                    UPDATE publication_memberships
                    SET state = ?, completion_disposition = ?, updated_at = ?
                    WHERE item_id = ?
                    """,
                    (
                        PublicationMembershipState.COMPLETED.value,
                        PublicationCompletionDisposition.NORMAL.value,
                        timestamp,
                        stage["item_id"],
                    ),
                )
                stage_status = StageStatus.COMPLETED
                stage_result = canonical_json(
                    {
                        "component_id": binding["component_id"],
                        "disposition": PublicationCompletionDisposition.NORMAL.value,
                        "publication_id": derived.publication_id,
                    }
                )
                stage_error = None
            else:
                stage_status = StageStatus.BLOCKED
                stage_result = None
                stage_error = (
                    canonical_json(
                        {
                            "kind": "publication_candidate_conflict",
                            "publication_id": derived.publication_id,
                        }
                    )
                    if membership_state is PublicationMembershipState.CONFLICT
                    else None
                )

            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, result_json = ?, error_json = ?,
                    next_attempt_at = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    stage_status.value,
                    stage_result,
                    stage_error,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=stage["batch_id"],
                item_id=stage["item_id"],
                stage_id=stage_id,
                kind=(
                    "publication_candidate_conflict"
                    if membership_state is PublicationMembershipState.CONFLICT
                    else "publication_joined"
                ),
                now=timestamp,
                payload={
                    "component_id": binding["component_id"],
                    "publication_id": derived.publication_id,
                },
            )
            self._refresh_items_and_batches(
                connection,
                {stage["item_id"]},
                timestamp,
            )
            return self._membership_from_row(
                self._require_membership_row(connection, stage["item_id"])
            )

    def get_publication_operation(
        self,
        publication_id: str,
    ) -> PublicationOperation:
        with self._reading() as connection:
            return self._publication_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def get_publication_membership(
        self,
        item_id: str,
    ) -> PublicationMembership | None:
        with self._reading() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM items WHERE id = ?",
                    (item_id,),
                ).fetchone()
                is None
            ):
                raise KeyError(item_id)
            row = connection.execute(
                "SELECT * FROM publication_memberships WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            return None if row is None else self._membership_from_row(row)

    def claim_publications(
        self,
        worker_id: str,
        *,
        now: float | None = None,
        lease_seconds: float = 60.0,
        limit: int = 1,
    ) -> list[PublicationLease]:
        """Claim component-global publication work with a generation fence."""

        opaque_text(worker_id, "worker_id")
        lease_duration = self._finite_number(lease_seconds, "lease_seconds")
        if lease_duration <= 0:
            raise ValueError("lease_seconds must be positive")
        if not 1 <= limit <= MAX_CLAIM_LIMIT:
            raise ValueError("claim limit must be between 1 and 1000")
        timestamp = self._timestamp(now)
        expires_at = self._finite_number(
            timestamp + lease_duration,
            "lease expiration",
        )
        claimed: list[PublicationLease] = []
        states = tuple(state.value for state in RECONCILABLE_PUBLICATION_STATES)

        with self._serialized_writing() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM publication_operations
                WHERE state IN ({",".join("?" for _ in states)})
                  AND (
                      lease_owner IS NULL
                      OR lease_expires_at IS NULL
                      OR lease_expires_at <= ?
                  )
                ORDER BY created_at, publication_id
                LIMIT ?
                """,
                (*states, timestamp, limit),
            ).fetchall()
            for row in rows:
                lease_token = secrets.token_urlsafe(32)
                updated = connection.execute(
                    """
                    UPDATE publication_operations
                    SET lease_owner = ?, lease_expires_at = ?,
                        lease_token = ?, lease_generation = lease_generation + 1,
                        updated_at = ?
                    WHERE publication_id = ?
                      AND state = ?
                      AND (
                          lease_owner IS NULL
                          OR lease_expires_at IS NULL
                          OR lease_expires_at <= ?
                      )
                    """,
                    (
                        worker_id,
                        expires_at,
                        lease_token,
                        timestamp,
                        row["publication_id"],
                        row["state"],
                        timestamp,
                    ),
                )
                if updated.rowcount != 1:
                    continue
                current = self._require_publication_row(
                    connection,
                    row["publication_id"],
                )
                claimed.append(self._publication_lease_from_row(current))
                self._emit_to_publication_members(
                    connection,
                    publication_id=row["publication_id"],
                    kind="publication_claimed",
                    now=timestamp,
                    payload={
                        "lease_generation": current["lease_generation"],
                        "publication_id": row["publication_id"],
                        "worker_id": worker_id,
                    },
                )
        return claimed

    def renew_publication_lease(
        self,
        publication_id: str,
        worker_id: str,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
        lease_seconds: float = 60.0,
    ) -> PublicationLease:
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        lease_duration = self._finite_number(lease_seconds, "lease_seconds")
        if lease_duration <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._timestamp(now)
        expires_at = self._finite_number(
            timestamp + lease_duration,
            "lease expiration",
        )
        with self._serialized_writing() as connection:
            row = self._require_publication_row(connection, publication_id)
            self._require_publication_lease(
                row,
                worker_id,
                token,
                generation,
                timestamp,
            )
            updated = connection.execute(
                """
                UPDATE publication_operations
                SET lease_expires_at = ?, updated_at = ?
                WHERE publication_id = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                  AND lease_expires_at > ?
                """,
                (
                    expires_at,
                    timestamp,
                    publication_id,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")
            return self._publication_lease_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def replan_publication(
        self,
        publication_id: str,
        worker_id: str,
        *,
        manifest_digest: str,
        expected_base_commit: str,
        expected_head_publication_id: str | None,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> PublicationOperation:
        """Change base/head/manifest only while the operation is pre-fence."""

        manifest = parse_sha256(manifest_digest, "manifest_digest")
        base_commit = opaque_text(expected_base_commit, "expected_base_commit")
        expected_head = (
            None
            if expected_head_publication_id is None
            else opaque_text(
                expected_head_publication_id,
                "expected_head_publication_id",
            )
        )
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_publication_row(connection, publication_id)
            self._require_publication_lease(
                row,
                worker_id,
                token,
                generation,
                timestamp,
            )
            exact = (
                bytes(row["manifest_digest"]) == manifest
                and row["expected_base_commit"] == base_commit
                and row["expected_head_publication_id"] == expected_head
            )
            state = PublicationState(row["state"])
            if state is not PublicationState.PREPARING:
                if exact:
                    return self._publication_from_row(row)
                raise WorkflowConflict("publication plan is immutable at or after the commit fence")

            head = connection.execute(
                """
                SELECT publication_id FROM component_publication_heads
                WHERE component_id = ?
                """,
                (row["component_id"],),
            ).fetchone()
            current_head = None if head is None else head["publication_id"]
            if current_head != expected_head:
                raise WorkflowConflict(
                    "expected publication head is not the current component head"
                )
            if exact:
                return self._publication_from_row(row)
            updated = connection.execute(
                """
                UPDATE publication_operations
                SET manifest_digest = ?, expected_base_commit = ?,
                    expected_head_publication_id = ?, updated_at = ?
                WHERE publication_id = ? AND state = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND lease_generation = ? AND lease_expires_at > ?
                """,
                (
                    manifest,
                    base_commit,
                    expected_head,
                    timestamp,
                    publication_id,
                    PublicationState.PREPARING.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")
            self._emit_to_publication_members(
                connection,
                publication_id=publication_id,
                kind="publication_replanned",
                now=timestamp,
                payload={
                    "expected_base_commit": base_commit,
                    "expected_head_publication_id": expected_head,
                    "publication_id": publication_id,
                },
            )
            return self._publication_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def arm_publication_commit(
        self,
        publication_id: str,
        worker_id: str,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> PublicationOperation:
        """Cross the durable point after which cancellation must reconcile."""

        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_publication_row(connection, publication_id)
            self._require_publication_lease(
                row,
                worker_id,
                token,
                generation,
                timestamp,
            )
            state = PublicationState(row["state"])
            if is_post_commit_fence(state):
                return self._publication_from_row(row)
            if state is not PublicationState.PREPARING:
                raise WorkflowConflict(f"publication is {state.value}, not preparing")
            live_member = connection.execute(
                """
                SELECT 1
                FROM publication_memberships AS membership
                JOIN items AS item ON item.id = membership.item_id
                LEFT JOIN batch_cancellations AS cancellation
                  ON cancellation.batch_id = item.batch_id
                 AND cancellation.state = ?
                WHERE membership.publication_id = ?
                  AND membership.state = ?
                  AND cancellation.batch_id IS NULL
                LIMIT 1
                """,
                (
                    BatchCancellationState.REQUESTED.value,
                    publication_id,
                    PublicationMembershipState.WAITING.value,
                ),
            ).fetchone()
            if live_member is None:
                raise WorkflowConflict(
                    "publication has no uncancelled membership at the commit fence"
                )
            updated = connection.execute(
                """
                UPDATE publication_operations
                SET state = ?, commit_fenced_at = ?, updated_at = ?
                WHERE publication_id = ? AND state = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND lease_generation = ? AND lease_expires_at > ?
                """,
                (
                    PublicationState.COMMIT_FENCED.value,
                    timestamp,
                    timestamp,
                    publication_id,
                    PublicationState.PREPARING.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")
            self._emit_to_publication_members(
                connection,
                publication_id=publication_id,
                kind="publication_commit_fenced",
                now=timestamp,
                payload={"publication_id": publication_id},
            )
            return self._publication_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def record_git_commit(
        self,
        publication_id: str,
        worker_id: str,
        *,
        git_commit_oid: str,
        verified_tree_digest: str,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> PublicationOperation:
        """Record a publisher-verified Git trailer/tree observation."""

        commit_oid = opaque_text(git_commit_oid, "git_commit_oid")
        tree_digest = parse_sha256(
            verified_tree_digest,
            "verified_tree_digest",
        )
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_publication_row(connection, publication_id)
            self._require_publication_lease(
                row,
                worker_id,
                token,
                generation,
                timestamp,
            )
            state = PublicationState(row["state"])
            if state in {
                PublicationState.GIT_COMMITTED,
                PublicationState.CATALOG_ACTIVATED,
            }:
                if (
                    row["git_commit_oid"] != commit_oid
                    or bytes(row["verified_tree_digest"]) != tree_digest
                ):
                    raise WorkflowConflict("publication already records a different Git proof")
                return self._publication_from_row(row)
            if state is not PublicationState.COMMIT_FENCED:
                raise WorkflowConflict(f"publication is {state.value}, not commit_fenced")
            updated = connection.execute(
                """
                UPDATE publication_operations
                SET state = ?, git_commit_oid = ?,
                    verified_tree_digest = ?, updated_at = ?
                WHERE publication_id = ? AND state = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND lease_generation = ? AND lease_expires_at > ?
                """,
                (
                    PublicationState.GIT_COMMITTED.value,
                    commit_oid,
                    tree_digest,
                    timestamp,
                    publication_id,
                    PublicationState.COMMIT_FENCED.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")
            self._emit_to_publication_members(
                connection,
                publication_id=publication_id,
                kind="publication_git_committed",
                now=timestamp,
                payload={
                    "git_commit_oid": commit_oid,
                    "publication_id": publication_id,
                },
            )
            return self._publication_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def record_catalog_activation(
        self,
        publication_id: str,
        worker_id: str,
        *,
        catalog_revision: str,
        catalog_semantic_digest: str,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> PublicationOperation:
        """Record an idempotent Catalog.sqlite activation proof."""

        revision = opaque_text(catalog_revision, "catalog_revision")
        semantic_digest = parse_sha256(
            catalog_semantic_digest,
            "catalog_semantic_digest",
        )
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_publication_row(connection, publication_id)
            self._require_publication_lease(
                row,
                worker_id,
                token,
                generation,
                timestamp,
            )
            state = PublicationState(row["state"])
            if state is PublicationState.CATALOG_ACTIVATED:
                if (
                    row["catalog_revision"] != revision
                    or bytes(row["catalog_semantic_digest"]) != semantic_digest
                ):
                    raise WorkflowConflict("publication already records a different catalog proof")
                return self._publication_from_row(row)
            if state is not PublicationState.GIT_COMMITTED:
                raise WorkflowConflict(f"publication is {state.value}, not git_committed")
            updated = connection.execute(
                """
                UPDATE publication_operations
                SET state = ?, catalog_revision = ?,
                    catalog_semantic_digest = ?, updated_at = ?
                WHERE publication_id = ? AND state = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND lease_generation = ? AND lease_expires_at > ?
                """,
                (
                    PublicationState.CATALOG_ACTIVATED.value,
                    revision,
                    semantic_digest,
                    timestamp,
                    publication_id,
                    PublicationState.GIT_COMMITTED.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")
            self._emit_to_publication_members(
                connection,
                publication_id=publication_id,
                kind="publication_catalog_activated",
                now=timestamp,
                payload={
                    "catalog_revision": revision,
                    "publication_id": publication_id,
                },
            )
            return self._publication_from_row(
                self._require_publication_row(connection, publication_id)
            )

    def complete_publication(
        self,
        publication_id: str,
        worker_id: str,
        receipt: object,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> bool:
        """Atomically persist the global receipt and settle all memberships."""

        receipt_json = canonical_json(receipt)
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            operation = self._require_publication_row(
                connection,
                publication_id,
            )
            state = PublicationState(operation["state"])
            if state is PublicationState.COMPLETED:
                if operation["lease_token"] != token or operation["lease_generation"] != generation:
                    raise WorkflowConflict("publication lease fence is stale")
                existing_receipt = connection.execute(
                    """
                    SELECT * FROM component_publication_receipts
                    WHERE publication_id = ?
                    """,
                    (publication_id,),
                ).fetchone()
                if existing_receipt is None:
                    raise WorkflowDataCorruption("completed publication has no global receipt")
                if existing_receipt["payload_json"] != receipt_json:
                    raise WorkflowConflict("publication already has a different receipt")
                return False

            self._require_publication_lease(
                operation,
                worker_id,
                token,
                generation,
                timestamp,
            )
            if state is not PublicationState.CATALOG_ACTIVATED:
                raise WorkflowConflict(f"publication is {state.value}, not catalog_activated")
            if (
                operation["git_commit_oid"] is None
                or operation["verified_tree_digest"] is None
                or operation["catalog_revision"] is None
                or operation["catalog_semantic_digest"] is None
            ):
                raise WorkflowDataCorruption(
                    "catalog-activated publication is missing verified proofs"
                )

            updated_operation = connection.execute(
                """
                UPDATE publication_operations
                SET state = ?, updated_at = ?
                WHERE publication_id = ? AND state = ?
                  AND lease_owner = ? AND lease_token = ?
                  AND lease_generation = ? AND lease_expires_at > ?
                """,
                (
                    PublicationState.COMPLETED.value,
                    timestamp,
                    publication_id,
                    PublicationState.CATALOG_ACTIVATED.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            if updated_operation.rowcount != 1:
                raise WorkflowConflict("publication lease fence is stale")

            head = connection.execute(
                """
                SELECT publication_id FROM component_publication_heads
                WHERE component_id = ?
                """,
                (operation["component_id"],),
            ).fetchone()
            expected_head = operation["expected_head_publication_id"]
            if expected_head is None:
                if head is None:
                    connection.execute(
                        """
                        INSERT INTO component_publication_heads(
                            component_id, publication_id, updated_at
                        ) VALUES (?, ?, ?)
                        """,
                        (
                            operation["component_id"],
                            publication_id,
                            timestamp,
                        ),
                    )
                elif head["publication_id"] != publication_id:
                    raise WorkflowConflict("component publication head changed before completion")
            else:
                if head is None or head["publication_id"] != expected_head:
                    raise WorkflowConflict("component publication head changed before completion")
                updated_head = connection.execute(
                    """
                    UPDATE component_publication_heads
                    SET publication_id = ?, updated_at = ?
                    WHERE component_id = ? AND publication_id = ?
                    """,
                    (
                        publication_id,
                        timestamp,
                        operation["component_id"],
                        expected_head,
                    ),
                )
                if updated_head.rowcount != 1:
                    raise WorkflowConflict("component publication head changed before completion")

            connection.execute(
                """
                INSERT INTO component_publication_receipts(
                    publication_id, component_id, git_commit_oid,
                    verified_tree_digest, catalog_revision,
                    catalog_semantic_digest, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    publication_id,
                    operation["component_id"],
                    operation["git_commit_oid"],
                    operation["verified_tree_digest"],
                    operation["catalog_revision"],
                    operation["catalog_semantic_digest"],
                    receipt_json,
                    timestamp,
                ),
            )
            memberships = connection.execute(
                """
                SELECT membership.*, item.batch_id
                FROM publication_memberships AS membership
                JOIN items AS item ON item.id = membership.item_id
                WHERE membership.publication_id = ?
                ORDER BY item.batch_id, item.ordinal
                """,
                (publication_id,),
            ).fetchall()
            affected_items: set[str] = set()
            affected_batches: set[str] = set()
            for membership in memberships:
                if (
                    PublicationMembershipState(membership["state"])
                    is not PublicationMembershipState.WAITING
                ):
                    continue
                disposition = (
                    PublicationCompletionDisposition.COMPLETED_BEFORE_CANCEL
                    if membership["cancel_after_fence"]
                    else PublicationCompletionDisposition.NORMAL
                )
                connection.execute(
                    """
                    UPDATE publication_memberships
                    SET state = ?, completion_disposition = ?, updated_at = ?
                    WHERE item_id = ? AND state = ?
                    """,
                    (
                        PublicationMembershipState.COMPLETED.value,
                        disposition.value,
                        timestamp,
                        membership["item_id"],
                        PublicationMembershipState.WAITING.value,
                    ),
                )
                stage_result = canonical_json(
                    {
                        "component_id": operation["component_id"],
                        "disposition": disposition.value,
                        "publication_id": publication_id,
                    }
                )
                completed_stage = connection.execute(
                    """
                    UPDATE stages
                    SET status = ?, result_json = ?, error_json = NULL,
                        updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        StageStatus.COMPLETED.value,
                        stage_result,
                        timestamp,
                        membership["publish_stage_id"],
                        StageStatus.BLOCKED.value,
                    ),
                )
                if completed_stage.rowcount != 1:
                    raise WorkflowDataCorruption(
                        "publication membership stage is not durably blocked"
                    )
                self._emit(
                    connection,
                    batch_id=membership["batch_id"],
                    item_id=membership["item_id"],
                    stage_id=membership["publish_stage_id"],
                    kind=(
                        "publication_completed_before_cancel"
                        if disposition is PublicationCompletionDisposition.COMPLETED_BEFORE_CANCEL
                        else "publication_completed"
                    ),
                    now=timestamp,
                    payload={
                        "component_id": operation["component_id"],
                        "publication_id": publication_id,
                    },
                )
                affected_items.add(membership["item_id"])
                affected_batches.add(membership["batch_id"])

            self._refresh_items_and_batches(
                connection,
                affected_items,
                timestamp,
            )
            for batch_id in affected_batches:
                self._finalize_batch_cancellation(
                    connection,
                    batch_id,
                    timestamp,
                )
            return True

    def get_component_publication_receipt(
        self,
        publication_id: str,
    ) -> ComponentPublicationReceipt | None:
        with self._reading() as connection:
            self._require_publication_row(connection, publication_id)
            row = connection.execute(
                """
                SELECT * FROM component_publication_receipts
                WHERE publication_id = ?
                """,
                (publication_id,),
            ).fetchone()
            return None if row is None else self._component_receipt_from_row(row)

    def list_publications_for_reconciliation(self) -> list[PublicationOperation]:
        states = tuple(
            state.value
            for state in (
                PublicationState.COMMIT_FENCED,
                PublicationState.GIT_COMMITTED,
                PublicationState.CATALOG_ACTIVATED,
            )
        )
        with self._reading() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM publication_operations
                WHERE state IN ({",".join("?" for _ in states)})
                ORDER BY created_at, publication_id
                """,
                states,
            ).fetchall()
            return [self._publication_from_row(row) for row in rows]

    def get_stage(self, stage_id: str) -> StageRecord:
        with self._reading() as connection:
            return self._stage_from_row(self._require_stage_row(connection, stage_id))

    def count_stages(self, batch_id: str) -> int:
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM stages AS s
                    JOIN items AS i ON i.id = s.item_id
                    WHERE i.batch_id = ?
                    """,
                    (batch_id,),
                ).fetchone()[0]
            )

    def _refresh_item(
        self,
        connection: sqlite3.Connection,
        item_id: str,
        now: float,
    ) -> str:
        row = connection.execute(
            "SELECT status FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        statuses = [
            StageStatus(stage["status"])
            for stage in connection.execute(
                "SELECT status FROM stages WHERE item_id = ?",
                (item_id,),
            )
        ]
        automatically_advancing = {
            StageStatus.READY,
            StageStatus.RUNNING,
            StageStatus.WAITING_RETRY,
        }
        if any(status is StageStatus.FAILED for status in statuses):
            derived = ItemStatus.FAILED
        elif statuses and all(status is StageStatus.COMPLETED for status in statuses):
            derived = ItemStatus.COMPLETED
        elif any(status is StageStatus.RUNNING for status in statuses):
            derived = ItemStatus.RUNNING
        elif any(status in automatically_advancing for status in statuses):
            derived = ItemStatus.QUEUED
        elif any(status is StageStatus.BLOCKED for status in statuses):
            derived = ItemStatus.BLOCKED
        elif any(status is StageStatus.CANCELLED for status in statuses):
            derived = ItemStatus.CANCELLED
        else:
            derived = ItemStatus.QUEUED
        if row["status"] != derived.value:
            connection.execute(
                "UPDATE items SET status = ?, updated_at = ? WHERE id = ?",
                (derived.value, now, item_id),
            )
        batch_id = connection.execute(
            "SELECT batch_id FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()["batch_id"]
        return batch_id

    def _refresh_batch(
        self,
        connection: sqlite3.Connection,
        batch_id: str,
        now: float,
    ) -> None:
        row = self._require_batch_row(connection, batch_id)
        current = BatchStatus(row["status"])
        if current in {BatchStatus.PAUSED, BatchStatus.CANCELLED}:
            return
        cancellation = connection.execute(
            """
            SELECT state FROM batch_cancellations
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if (
            cancellation is not None
            and BatchCancellationState(cancellation["state"]) is BatchCancellationState.REQUESTED
        ):
            self._finalize_batch_cancellation(
                connection,
                batch_id,
                now,
            )
            return

        statuses = [
            ItemStatus(item["status"])
            for item in connection.execute(
                "SELECT status FROM items WHERE batch_id = ?",
                (batch_id,),
            )
        ]
        terminal = {
            ItemStatus.COMPLETED,
            ItemStatus.FAILED,
            ItemStatus.CANCELLED,
        }
        if statuses and all(status is ItemStatus.COMPLETED for status in statuses):
            derived = BatchStatus.COMPLETED
        elif statuses and all(status in terminal for status in statuses):
            if any(status is ItemStatus.FAILED for status in statuses):
                derived = BatchStatus.FAILED
            elif any(status is ItemStatus.CANCELLED for status in statuses):
                derived = BatchStatus.CANCELLED
            else:
                derived = BatchStatus.COMPLETED
        elif statuses and all(
            status
            in {
                ItemStatus.BLOCKED,
                ItemStatus.COMPLETED,
                ItemStatus.FAILED,
                ItemStatus.CANCELLED,
            }
            for status in statuses
        ):
            derived = BatchStatus.BLOCKED
        elif any(status is ItemStatus.RUNNING for status in statuses):
            derived = BatchStatus.RUNNING
        else:
            derived = BatchStatus.QUEUED

        if current is not derived:
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = ? WHERE id = ?",
                (derived.value, now, batch_id),
            )

    def _finalize_batch_cancellation(
        self,
        connection: sqlite3.Connection,
        batch_id: str,
        now: float,
    ) -> bool:
        cancellation = connection.execute(
            """
            SELECT * FROM batch_cancellations
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if cancellation is None:
            return False
        if BatchCancellationState(cancellation["state"]) is BatchCancellationState.COMPLETED:
            return True
        protected = connection.execute(
            """
            SELECT 1
            FROM publication_memberships AS membership
            JOIN items AS item ON item.id = membership.item_id
            JOIN publication_operations AS operation
              ON operation.publication_id = membership.publication_id
            WHERE item.batch_id = ?
              AND membership.state = ?
              AND membership.cancel_after_fence = 1
              AND operation.state IN (
                  'commit_fenced', 'git_committed', 'catalog_activated'
              )
            LIMIT 1
            """,
            (batch_id, PublicationMembershipState.WAITING.value),
        ).fetchone()
        if protected is not None:
            connection.execute(
                """
                UPDATE batches SET status = ?, updated_at = ?
                WHERE id = ? AND status NOT IN ('completed', 'cancelled')
                """,
                (BatchStatus.BLOCKED.value, now, batch_id),
            )
            return False

        connection.execute(
            """
            UPDATE stages
            SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                lease_token = NULL, next_attempt_at = NULL, updated_at = ?
            WHERE item_id IN (
                SELECT id FROM items WHERE batch_id = ?
            )
              AND status <> ?
            """,
            (
                StageStatus.CANCELLED.value,
                now,
                batch_id,
                StageStatus.COMPLETED.value,
            ),
        )
        connection.execute(
            """
            UPDATE decisions
            SET status = ?, resolution_json = ?, resolved_at = ?
            WHERE status = ?
              AND item_id IN (
                  SELECT id FROM items WHERE batch_id = ?
              )
            """,
            (
                DecisionStatus.CANCELLED.value,
                canonical_json({"reason": "batch_cancelled"}),
                now,
                DecisionStatus.OPEN.value,
                batch_id,
            ),
        )
        item_ids = {
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM items WHERE batch_id = ?",
                (batch_id,),
            )
        }
        for item_id in item_ids:
            self._refresh_item(connection, item_id, now)
        connection.execute(
            """
            UPDATE batches SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (BatchStatus.CANCELLED.value, now, batch_id),
        )
        connection.execute(
            """
            UPDATE batch_cancellations
            SET state = ?, completed_at = ?
            WHERE batch_id = ? AND state = ?
            """,
            (
                BatchCancellationState.COMPLETED.value,
                now,
                batch_id,
                BatchCancellationState.REQUESTED.value,
            ),
        )
        self._emit(
            connection,
            batch_id=batch_id,
            kind="batch_cancelled",
            now=now,
            payload={},
        )
        return True

    def _refresh_items_and_batches(
        self,
        connection: sqlite3.Connection,
        item_ids: set[str],
        now: float,
    ) -> None:
        batch_ids = {self._refresh_item(connection, item_id, now) for item_id in item_ids}
        for batch_id in batch_ids:
            self._refresh_batch(connection, batch_id, now)

    def _recover_expired_in_transaction(
        self,
        connection: sqlite3.Connection,
        now: float,
    ) -> int:
        rows = connection.execute(
            f"""
            {_STAGE_SELECT}
            WHERE s.status = ?
              AND s.lease_expires_at <= ?
            ORDER BY s.id
            """,
            (StageStatus.RUNNING.value, now),
        ).fetchall()
        for row in rows:
            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.READY.value,
                    now,
                    row["id"],
                    StageStatus.RUNNING.value,
                    row["lease_token"],
                    row["lease_generation"],
                ),
            )
            if updated.rowcount != 1:
                continue
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=row["id"],
                kind="stage_lease_expired",
                now=now,
                payload={
                    "attempt": row["attempt_count"],
                    "previous_owner": row["lease_owner"],
                },
            )
        if rows:
            self._refresh_items_and_batches(
                connection,
                {row["item_id"] for row in rows},
                now,
            )
        return sum(
            1
            for row in rows
            if StageStatus(self._require_stage_row(connection, row["id"])["status"])
            is StageStatus.READY
        )

    def _promote_due_retries(
        self,
        connection: sqlite3.Connection,
        now: float,
    ) -> None:
        rows = connection.execute(
            f"""
            {_STAGE_SELECT}
            WHERE s.status = ?
              AND s.next_attempt_at <= ?
            ORDER BY s.id
            """,
            (StageStatus.WAITING_RETRY.value, now),
        ).fetchall()
        for row in rows:
            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, next_attempt_at = NULL, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    StageStatus.READY.value,
                    now,
                    row["id"],
                    StageStatus.WAITING_RETRY.value,
                ),
            )
            if updated.rowcount != 1:
                continue
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=row["id"],
                kind="stage_retry_ready",
                now=now,
                payload={"attempts_completed": row["attempt_count"]},
            )

    def recover_expired_leases(self, *, now: float | None = None) -> int:
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            return self._recover_expired_in_transaction(connection, timestamp)

    def claim_ready(
        self,
        worker_id: str,
        *,
        now: float | None = None,
        lease_seconds: float = 60.0,
        limit: int = 1,
    ) -> list[StageRecord]:
        """Atomically claim at most ``limit`` dependency-ready stages."""

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        lease_duration = self._finite_number(lease_seconds, "lease_seconds")
        if lease_duration <= 0:
            raise ValueError("lease_seconds must be positive")
        if not 1 <= limit <= MAX_CLAIM_LIMIT:
            raise ValueError("claim limit must be between 1 and 1000")

        timestamp = self._timestamp(now)
        lease_expires_at = self._finite_number(
            timestamp + lease_duration,
            "lease expiration",
        )
        claimed_ids: list[str] = []
        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            self._promote_due_retries(connection, timestamp)
            candidates = connection.execute(
                """
                WITH batch_claims AS (
                    SELECT
                        i.batch_id,
                        SUM(s.attempt_count) AS attempts
                    FROM items AS i
                    JOIN stages AS s ON s.item_id = i.id
                    GROUP BY i.batch_id
                ),
                eligible AS (
                    SELECT
                        s.id,
                        b.id AS batch_id,
                        b.created_at AS batch_created_at,
                        i.ordinal AS item_ordinal,
                        s.ordinal AS stage_ordinal,
                        batch_claims.attempts,
                        ROW_NUMBER() OVER (
                            PARTITION BY b.id
                            ORDER BY i.ordinal, s.ordinal, s.id
                        ) AS batch_slot
                    FROM stages AS s
                    JOIN items AS i ON i.id = s.item_id
                    JOIN batches AS b ON b.id = i.batch_id
                    JOIN batch_claims ON batch_claims.batch_id = b.id
                    WHERE s.status = ?
                      AND i.status NOT IN ('completed', 'failed', 'cancelled')
                      AND b.status NOT IN (
                          'paused', 'completed', 'failed', 'cancelled'
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM batch_cancellations AS cancellation
                          WHERE cancellation.batch_id = b.id
                            AND cancellation.state = 'requested'
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM stage_dependencies AS d
                          JOIN stages AS dependency
                            ON dependency.id = d.depends_on_stage_id
                          WHERE d.stage_id = s.id
                            AND dependency.status <> ?
                      )
                )
                SELECT id
                FROM eligible
                ORDER BY
                    attempts + batch_slot,
                    batch_created_at,
                    batch_id,
                    item_ordinal,
                    stage_ordinal,
                    id
                LIMIT ?
                """,
                (
                    StageStatus.READY.value,
                    StageStatus.COMPLETED.value,
                    limit,
                ),
            ).fetchall()
            for candidate in candidates:
                stage_id = candidate["id"]
                lease_token = secrets.token_urlsafe(32)
                updated = connection.execute(
                    """
                    UPDATE stages
                    SET status = ?,
                        attempt_count = attempt_count + 1,
                        lease_owner = ?,
                        lease_expires_at = ?,
                        lease_token = ?,
                        lease_generation = lease_generation + 1,
                        updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        StageStatus.RUNNING.value,
                        worker_id,
                        lease_expires_at,
                        lease_token,
                        timestamp,
                        stage_id,
                        StageStatus.READY.value,
                    ),
                )
                if updated.rowcount != 1:
                    continue
                row = self._require_stage_row(connection, stage_id)
                claimed_ids.append(stage_id)
                connection.execute(
                    """
                    UPDATE items
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                      AND status NOT IN ('completed', 'failed', 'cancelled')
                    """,
                    (ItemStatus.RUNNING.value, timestamp, row["item_id"]),
                )
                connection.execute(
                    """
                    UPDATE batches
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                      AND status NOT IN ('paused', 'completed', 'failed', 'cancelled')
                    """,
                    (BatchStatus.RUNNING.value, timestamp, row["batch_id"]),
                )
                self._emit(
                    connection,
                    batch_id=row["batch_id"],
                    item_id=row["item_id"],
                    stage_id=stage_id,
                    kind="stage_claimed",
                    now=timestamp,
                    payload={
                        "attempt": row["attempt_count"],
                        "lease_generation": row["lease_generation"],
                        "lease_expires_at": lease_expires_at,
                        "worker_id": worker_id,
                    },
                )

            return [
                self._stage_from_row(self._require_stage_row(connection, stage_id))
                for stage_id in claimed_ids
            ]

    def renew_lease(
        self,
        stage_id: str,
        worker_id: str,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
        lease_seconds: float = 60.0,
    ) -> StageRecord:
        """Heartbeat owned in-flight work without changing its attempt number."""

        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        lease_duration = self._finite_number(lease_seconds, "lease_seconds")
        if lease_duration <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = self._timestamp(now)
        lease_expires_at = self._finite_number(
            timestamp + lease_duration,
            "lease expiration",
        )

        with self._serialized_writing() as connection:
            row = self._require_stage_row(connection, stage_id)
            self._require_running_lease(
                row,
                worker_id,
                token,
                generation,
            )
            if row["lease_expires_at"] <= timestamp:
                raise WorkflowConflict("stage lease has expired")
            updated = connection.execute(
                """
                UPDATE stages
                SET lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                  AND lease_expires_at > ?
                """,
                (
                    lease_expires_at,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                    timestamp,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=stage_id,
                kind="stage_lease_renewed",
                now=timestamp,
                payload={
                    "lease_expires_at": lease_expires_at,
                    "lease_generation": generation,
                    "worker_id": worker_id,
                },
            )
            return self._stage_from_row(self._require_stage_row(connection, stage_id))

    def _promote_dependencies(
        self,
        connection: sqlite3.Connection,
        item_id: str,
        now: float,
    ) -> None:
        rows = connection.execute(
            f"""
            {_STAGE_SELECT}
            WHERE s.item_id = ?
              AND s.status = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM stage_dependencies AS d
                  JOIN stages AS dependency
                    ON dependency.id = d.depends_on_stage_id
                  WHERE d.stage_id = s.id
                    AND dependency.status <> ?
              )
            ORDER BY s.ordinal
            """,
            (
                item_id,
                StageStatus.PENDING.value,
                StageStatus.COMPLETED.value,
            ),
        ).fetchall()
        for row in rows:
            updated = connection.execute(
                """
                UPDATE stages SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    StageStatus.READY.value,
                    now,
                    row["id"],
                    StageStatus.PENDING.value,
                ),
            )
            if updated.rowcount != 1:
                continue
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=row["id"],
                kind="stage_ready",
                now=now,
                payload={"stage": row["name"]},
            )

    @staticmethod
    def _require_running_lease(
        row: sqlite3.Row,
        worker_id: str,
        lease_token: str,
        lease_generation: int,
    ) -> None:
        status = StageStatus(row["status"])
        if status is StageStatus.CANCELLED:
            raise WorkflowConflict("stage or batch is cancelled")
        if status is not StageStatus.RUNNING:
            raise WorkflowConflict(f"stage is {status.value}, not running")
        if row["lease_owner"] != worker_id:
            raise WorkflowConflict("stage is leased by another worker")
        if row["lease_token"] != lease_token or row["lease_generation"] != lease_generation:
            raise WorkflowConflict("stage lease fence is stale")

    @staticmethod
    def _require_fenced_transition(updated: sqlite3.Cursor) -> None:
        if updated.rowcount != 1:
            raise WorkflowConflict("stage lease fence is stale")

    def complete_stage(
        self,
        stage_id: str,
        worker_id: str,
        result: object,
        *,
        lease_token: str,
        lease_generation: int,
        publication_receipt: object | None = None,
        now: float | None = None,
    ) -> bool:
        """Complete an ordinary leased stage once; exact replays are a no-op."""

        result_json = canonical_json(result)
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            row = self._require_stage_row(connection, stage_id)
            status = StageStatus(row["status"])
            name = StageName(row["name"])
            if name is StageName.IDENTITY_DEDUPE:
                raise ValueError("identity_dedupe must use resolve_exact_identity")
            if name is StageName.PUBLISH:
                raise ValueError("publish must use component publication methods")
            if publication_receipt is not None:
                raise ValueError("ordinary stage completion does not accept a publication receipt")
            if status is StageStatus.COMPLETED:
                if row["lease_token"] != token or row["lease_generation"] != generation:
                    raise WorkflowConflict("stage lease fence is stale")
                if row["result_json"] != result_json:
                    raise WorkflowConflict("completed stage already has a different result")
                return False
            batch = self._require_batch_row(connection, row["batch_id"])
            if BatchStatus(batch["status"]) is BatchStatus.CANCELLED:
                raise WorkflowConflict("stage or batch is cancelled")
            self._require_running_lease(
                row,
                worker_id,
                token,
                generation,
            )

            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, result_json = ?, error_json = NULL,
                    next_attempt_at = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.COMPLETED.value,
                    result_json,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=stage_id,
                kind="stage_completed",
                now=timestamp,
                payload={
                    "attempt": row["attempt_count"],
                    "stage": row["name"],
                },
            )
            self._promote_dependencies(
                connection,
                row["item_id"],
                timestamp,
            )
            self._refresh_items_and_batches(
                connection,
                {row["item_id"]},
                timestamp,
            )
            return True

    def retry_stage(
        self,
        stage_id: str,
        worker_id: str,
        error: object,
        *,
        lease_token: str,
        lease_generation: int,
        retry_at: float,
        now: float | None = None,
    ) -> StageRecord:
        """Persist a provider/timeout retry without creating a human decision."""

        error_json = canonical_json(error)
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        retry_timestamp = self._finite_number(retry_at, "retry_at")
        if retry_timestamp < timestamp:
            raise ValueError("retry_at must not be in the past")

        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            row = self._require_stage_row(connection, stage_id)
            self._require_running_lease(
                row,
                worker_id,
                token,
                generation,
            )
            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, error_json = ?, next_attempt_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.WAITING_RETRY.value,
                    error_json,
                    retry_timestamp,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=stage_id,
                kind="stage_retry_scheduled",
                now=timestamp,
                payload={
                    "attempt": row["attempt_count"],
                    "retry_at": retry_timestamp,
                },
            )
            self._refresh_items_and_batches(
                connection,
                {row["item_id"]},
                timestamp,
            )
            return self._stage_from_row(self._require_stage_row(connection, stage_id))

    def fail_stage(
        self,
        stage_id: str,
        worker_id: str,
        error: object,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> StageRecord:
        """Record a terminal machine failure without manufacturing a decision."""

        error_json = canonical_json(error)
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            row = self._require_stage_row(connection, stage_id)
            self._require_running_lease(
                row,
                worker_id,
                token,
                generation,
            )
            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, error_json = ?, next_attempt_at = NULL,
                    lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.FAILED.value,
                    error_json,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=stage_id,
                kind="stage_failed",
                now=timestamp,
                payload={"attempt": row["attempt_count"]},
            )
            self._refresh_items_and_batches(
                connection,
                {row["item_id"]},
                timestamp,
            )
            return self._stage_from_row(self._require_stage_row(connection, stage_id))

    def block_for_decision(
        self,
        stage_id: str,
        worker_id: str,
        kind: DecisionKind,
        prompt: object,
        *,
        lease_token: str,
        lease_generation: int,
        now: float | None = None,
    ) -> DecisionRecord:
        """Create the one compact identity/safety exception for a leased stage."""

        decision_kind = DecisionKind(kind)
        prompt_json = canonical_json(prompt)
        token, generation = self._lease_credentials(
            lease_token,
            lease_generation,
        )
        timestamp = self._timestamp(now)
        decision_id = new_opaque_id()
        with self._serialized_writing() as connection:
            self._recover_expired_in_transaction(connection, timestamp)
            row = self._require_stage_row(connection, stage_id)
            self._require_running_lease(
                row,
                worker_id,
                token,
                generation,
            )
            if (
                decision_kind is DecisionKind.IDENTITY
                and StageName(row["name"]) is not StageName.IDENTITY_DEDUPE
            ):
                raise ValueError("identity decisions belong to the identity stage")

            connection.execute(
                """
                INSERT INTO decisions(
                    id, item_id, stage_id, kind, status,
                    prompt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    row["item_id"],
                    stage_id,
                    decision_kind.value,
                    DecisionStatus.OPEN.value,
                    prompt_json,
                    timestamp,
                ),
            )
            updated = connection.execute(
                """
                UPDATE stages
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    lease_token = NULL, updated_at = ?
                WHERE id = ? AND status = ? AND lease_owner = ?
                  AND lease_token = ? AND lease_generation = ?
                """,
                (
                    StageStatus.BLOCKED.value,
                    timestamp,
                    stage_id,
                    StageStatus.RUNNING.value,
                    worker_id,
                    token,
                    generation,
                ),
            )
            self._require_fenced_transition(updated)
            self._emit(
                connection,
                batch_id=row["batch_id"],
                item_id=row["item_id"],
                stage_id=stage_id,
                kind="decision_opened",
                now=timestamp,
                payload={
                    "decision_id": decision_id,
                    "kind": decision_kind.value,
                },
            )
            self._refresh_items_and_batches(
                connection,
                {row["item_id"]},
                timestamp,
            )
            return self._decision_from_row(self._require_decision_row(connection, decision_id))

    def resolve_decision(
        self,
        decision_id: str,
        resolution: object,
        *,
        now: float | None = None,
    ) -> DecisionRecord:
        """Resolve an exception and make its stage immediately claimable again."""

        resolution_json = canonical_json(resolution)
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            decision = self._require_decision_row(connection, decision_id)
            status = DecisionStatus(decision["status"])
            if status is DecisionStatus.RESOLVED:
                if decision["resolution_json"] == resolution_json:
                    return self._decision_from_row(decision)
                raise WorkflowConflict("resolved decision already has a different resolution")
            if status is DecisionStatus.CANCELLED:
                raise WorkflowConflict("decision was cancelled")

            stage = self._require_stage_row(connection, decision["stage_id"])
            batch = self._require_batch_row(connection, stage["batch_id"])
            if BatchStatus(batch["status"]) is BatchStatus.CANCELLED:
                raise WorkflowConflict("decision belongs to a cancelled batch")
            if connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (
                    stage["batch_id"],
                    BatchCancellationState.REQUESTED.value,
                ),
            ).fetchone():
                raise WorkflowConflict("decision belongs to a cancelling batch")
            if StageStatus(stage["status"]) is not StageStatus.BLOCKED:
                raise WorkflowConflict("decision stage is no longer blocked")

            resolved = connection.execute(
                """
                UPDATE decisions
                SET status = ?, resolution_json = ?, resolved_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    DecisionStatus.RESOLVED.value,
                    resolution_json,
                    timestamp,
                    decision_id,
                    DecisionStatus.OPEN.value,
                ),
            )
            if resolved.rowcount != 1:
                raise WorkflowConflict("decision state changed before resolution")
            requeued = connection.execute(
                """
                UPDATE stages
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    StageStatus.READY.value,
                    timestamp,
                    stage["id"],
                    StageStatus.BLOCKED.value,
                ),
            )
            if requeued.rowcount != 1:
                raise WorkflowConflict("decision stage changed before resolution")
            self._emit(
                connection,
                batch_id=stage["batch_id"],
                item_id=stage["item_id"],
                stage_id=stage["id"],
                kind="decision_resolved",
                now=timestamp,
                payload={"decision_id": decision_id},
            )
            self._emit(
                connection,
                batch_id=stage["batch_id"],
                item_id=stage["item_id"],
                stage_id=stage["id"],
                kind="stage_ready",
                now=timestamp,
                payload={"stage": stage["name"]},
            )
            self._refresh_items_and_batches(
                connection,
                {stage["item_id"]},
                timestamp,
            )
            return self._decision_from_row(self._require_decision_row(connection, decision_id))

    def list_decisions(self, batch_id: str) -> list[DecisionRecord]:
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            rows = connection.execute(
                f"""
                {_DECISION_SELECT}
                JOIN items AS i ON i.id = d.item_id
                WHERE i.batch_id = ?
                ORDER BY d.created_at, d.id
                """,
                (batch_id,),
            ).fetchall()
            return [self._decision_from_row(row) for row in rows]

    def pause_batch(
        self,
        batch_id: str,
        *,
        now: float | None = None,
    ) -> BatchRecord:
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_batch_row(connection, batch_id)
            status = BatchStatus(row["status"])
            if status is BatchStatus.PAUSED:
                return self._batch_from_row(row)
            if connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (batch_id, BatchCancellationState.REQUESTED.value),
            ).fetchone():
                raise WorkflowConflict("cannot pause a cancelling batch")
            if status in {
                BatchStatus.COMPLETED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
            }:
                raise WorkflowConflict(f"cannot pause a {status.value} batch")
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = ? WHERE id = ?",
                (BatchStatus.PAUSED.value, timestamp, batch_id),
            )
            self._emit(
                connection,
                batch_id=batch_id,
                kind="batch_paused",
                now=timestamp,
                payload={},
            )
            return self._batch_from_row(self._require_batch_row(connection, batch_id))

    def resume_batch(
        self,
        batch_id: str,
        *,
        now: float | None = None,
    ) -> BatchRecord:
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_batch_row(connection, batch_id)
            status = BatchStatus(row["status"])
            if status in {
                BatchStatus.COMPLETED,
                BatchStatus.FAILED,
                BatchStatus.CANCELLED,
            }:
                raise WorkflowConflict(f"cannot resume a {status.value} batch")
            if connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (batch_id, BatchCancellationState.REQUESTED.value),
            ).fetchone():
                raise WorkflowConflict("cannot resume a cancelling batch")
            if status is not BatchStatus.PAUSED:
                return self._batch_from_row(row)
            connection.execute(
                "UPDATE batches SET status = ?, updated_at = ? WHERE id = ?",
                (BatchStatus.QUEUED.value, timestamp, batch_id),
            )
            self._refresh_batch(connection, batch_id, timestamp)
            self._emit(
                connection,
                batch_id=batch_id,
                kind="batch_resumed",
                now=timestamp,
                payload={},
            )
            return self._batch_from_row(self._require_batch_row(connection, batch_id))

    def retry_batch(
        self,
        batch_id: str,
        *,
        now: float | None = None,
    ) -> BatchRecord:
        """Requeue only terminally failed stages in a failed batch.

        Completed stages are immutable evidence and are never replayed.  The
        transition is state-idempotent: once the failed stages have been made
        ready, repeating the request returns the current nonterminal batch
        without adding events or changing timestamps.
        """

        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_batch_row(connection, batch_id)
            status = BatchStatus(row["status"])
            if status in {
                BatchStatus.QUEUED,
                BatchStatus.RUNNING,
                BatchStatus.BLOCKED,
            }:
                return self._batch_from_row(row)
            if status is BatchStatus.COMPLETED:
                raise WorkflowConflict("cannot retry a completed batch")
            if status is BatchStatus.CANCELLED:
                raise WorkflowConflict("cannot retry a cancelled batch")
            if status is BatchStatus.PAUSED:
                raise WorkflowConflict("resume a paused batch before retrying it")
            if connection.execute(
                """
                SELECT 1 FROM batch_cancellations
                WHERE batch_id = ? AND state = ?
                """,
                (batch_id, BatchCancellationState.REQUESTED.value),
            ).fetchone():
                raise WorkflowConflict("cannot retry a cancelling batch")

            failed = connection.execute(
                f"""
                {_STAGE_SELECT}
                WHERE s.status = ?
                  AND s.item_id IN (
                      SELECT id FROM items WHERE batch_id = ?
                  )
                ORDER BY s.item_id, s.ordinal
                """,
                (StageStatus.FAILED.value, batch_id),
            ).fetchall()
            if not failed:
                raise WorkflowDataCorruption("failed batch has no failed stage to retry")

            for stage in failed:
                updated = connection.execute(
                    """
                    UPDATE stages
                    SET status = ?, next_attempt_at = NULL,
                        lease_owner = NULL, lease_expires_at = NULL,
                        lease_token = NULL, updated_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        StageStatus.READY.value,
                        timestamp,
                        stage["id"],
                        StageStatus.FAILED.value,
                    ),
                )
                if updated.rowcount != 1:
                    raise WorkflowConflict("failed stage changed before retry")
                self._emit(
                    connection,
                    batch_id=batch_id,
                    item_id=stage["item_id"],
                    stage_id=stage["id"],
                    kind="stage_retry_ready",
                    now=timestamp,
                    payload={"attempts_completed": stage["attempt_count"]},
                )

            self._refresh_items_and_batches(
                connection,
                {stage["item_id"] for stage in failed},
                timestamp,
            )
            self._emit(
                connection,
                batch_id=batch_id,
                kind="batch_retry_requested",
                now=timestamp,
                payload={"failed_stage_count": len(failed)},
            )
            return self._batch_from_row(self._require_batch_row(connection, batch_id))

    def cancel_batch(
        self,
        batch_id: str,
        *,
        reason: object | None = None,
        now: float | None = None,
    ) -> BatchRecord:
        """Request cancellation while preserving post-commit-fence publication."""

        reason_json = canonical_json({"reason": "user_requested"} if reason is None else reason)
        timestamp = self._timestamp(now)
        with self._serialized_writing() as connection:
            row = self._require_batch_row(connection, batch_id)
            status = BatchStatus(row["status"])
            if status is BatchStatus.CANCELLED:
                return self._batch_from_row(row)
            if status is BatchStatus.COMPLETED:
                raise WorkflowConflict("cannot cancel a completed batch")

            existing_cancellation = connection.execute(
                """
                SELECT * FROM batch_cancellations WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
            if existing_cancellation is not None:
                if existing_cancellation["reason_json"] != reason_json:
                    raise WorkflowConflict("batch cancellation already has a different reason")
                self._finalize_batch_cancellation(
                    connection,
                    batch_id,
                    timestamp,
                )
                return self._batch_from_row(self._require_batch_row(connection, batch_id))

            connection.execute(
                """
                INSERT INTO batch_cancellations(
                    batch_id, state, reason_json, requested_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    batch_id,
                    BatchCancellationState.REQUESTED.value,
                    reason_json,
                    timestamp,
                ),
            )

            memberships = connection.execute(
                """
                SELECT
                    membership.*,
                    operation.state AS publication_state
                FROM publication_memberships AS membership
                JOIN items AS item ON item.id = membership.item_id
                JOIN publication_operations AS operation
                  ON operation.publication_id = membership.publication_id
                WHERE item.batch_id = ?
                """,
                (batch_id,),
            ).fetchall()
            protected_stage_ids: set[str] = set()
            for membership in memberships:
                membership_state = PublicationMembershipState(membership["state"])
                if membership_state is not PublicationMembershipState.WAITING:
                    continue
                publication_state = PublicationState(membership["publication_state"])
                if is_post_commit_fence(publication_state):
                    connection.execute(
                        """
                        UPDATE publication_memberships
                        SET cancel_after_fence = 1, updated_at = ?
                        WHERE item_id = ? AND state = ?
                        """,
                        (
                            timestamp,
                            membership["item_id"],
                            PublicationMembershipState.WAITING.value,
                        ),
                    )
                    protected_stage_ids.add(membership["publish_stage_id"])
                    self._emit(
                        connection,
                        batch_id=batch_id,
                        item_id=membership["item_id"],
                        stage_id=membership["publish_stage_id"],
                        kind="publication_cancel_after_fence",
                        now=timestamp,
                        payload={"publication_id": membership["publication_id"]},
                    )
                else:
                    connection.execute(
                        """
                        UPDATE publication_memberships
                        SET state = ?, updated_at = ?
                        WHERE item_id = ? AND state = ?
                        """,
                        (
                            PublicationMembershipState.CANCELLED.value,
                            timestamp,
                            membership["item_id"],
                            PublicationMembershipState.WAITING.value,
                        ),
                    )

            connection.execute(
                """
                UPDATE publication_operations
                SET state = ?, lease_owner = NULL,
                    lease_expires_at = NULL, lease_token = NULL, updated_at = ?
                WHERE state = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM publication_memberships AS membership
                      WHERE membership.publication_id =
                            publication_operations.publication_id
                        AND membership.state = ?
                  )
                """,
                (
                    PublicationState.ABORTED.value,
                    timestamp,
                    PublicationState.PREPARING.value,
                    PublicationMembershipState.WAITING.value,
                ),
            )

            if protected_stage_ids:
                placeholders = ",".join("?" for _ in protected_stage_ids)
                connection.execute(
                    f"""
                    UPDATE stages
                    SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                        lease_token = NULL, next_attempt_at = NULL, updated_at = ?
                    WHERE item_id IN (
                        SELECT id FROM items WHERE batch_id = ?
                    )
                      AND status <> ?
                      AND id NOT IN ({placeholders})
                    """,
                    (
                        StageStatus.CANCELLED.value,
                        timestamp,
                        batch_id,
                        StageStatus.COMPLETED.value,
                        *sorted(protected_stage_ids),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE stages
                    SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                        lease_token = NULL, next_attempt_at = NULL, updated_at = ?
                    WHERE item_id IN (
                        SELECT id FROM items WHERE batch_id = ?
                    )
                      AND status <> ?
                    """,
                    (
                        StageStatus.CANCELLED.value,
                        timestamp,
                        batch_id,
                        StageStatus.COMPLETED.value,
                    ),
                )
            connection.execute(
                """
                UPDATE decisions
                SET status = ?, resolution_json = ?, resolved_at = ?
                WHERE status = ?
                  AND item_id IN (
                      SELECT id FROM items WHERE batch_id = ?
                  )
                """,
                (
                    DecisionStatus.CANCELLED.value,
                    canonical_json({"reason": "batch_cancelled"}),
                    timestamp,
                    DecisionStatus.OPEN.value,
                    batch_id,
                ),
            )
            self._emit(
                connection,
                batch_id=batch_id,
                kind="batch_cancel_requested",
                now=timestamp,
                payload={},
            )
            for item in connection.execute(
                "SELECT id FROM items WHERE batch_id = ?",
                (batch_id,),
            ):
                self._refresh_item(
                    connection,
                    item["id"],
                    timestamp,
                )
            self._finalize_batch_cancellation(
                connection,
                batch_id,
                timestamp,
            )
            return self._batch_from_row(self._require_batch_row(connection, batch_id))

    def get_batch_cancellation(
        self,
        batch_id: str,
    ) -> BatchCancellationRecord | None:
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            row = connection.execute(
                "SELECT * FROM batch_cancellations WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            return None if row is None else self._batch_cancellation_from_row(row)

    def events(
        self,
        batch_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 10_000,
    ) -> list[WorkflowEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if not 1 <= limit <= 10_000:
            raise ValueError("event limit must be between 1 and 10000")
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            rows = connection.execute(
                """
                SELECT *
                FROM events
                WHERE batch_id = ? AND sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (batch_id, after_sequence, limit),
            ).fetchall()
            return [
                WorkflowEvent(
                    sequence=row["sequence"],
                    batch_id=row["batch_id"],
                    item_id=row["item_id"],
                    stage_id=row["stage_id"],
                    kind=row["kind"],
                    payload=decode_json(row["payload_json"]),
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    def latest_event_sequence(self, batch_id: str) -> int:
        """Return the batch's latest durable cursor without loading its journal."""

        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM events WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            return int(row["sequence"])

    def list_publication_receipts(
        self,
        batch_id: str,
    ) -> list[PublicationReceipt]:
        with self._reading() as connection:
            self._require_batch_row(connection, batch_id)
            rows = connection.execute(
                """
                SELECT r.*
                FROM publication_receipts AS r
                JOIN items AS i ON i.id = r.item_id
                WHERE i.batch_id = ?
                ORDER BY i.ordinal
                """,
                (batch_id,),
            ).fetchall()
            return [self._receipt_from_row(row) for row in rows]

    def get_publication_receipt(
        self,
        item_id: str,
    ) -> PublicationReceipt | None:
        """Return the exact item's receipt, never an arbitrary batch member."""

        with self._reading() as connection:
            item = connection.execute(
                "SELECT 1 FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if item is None:
                raise KeyError(item_id)
            row = connection.execute(
                "SELECT * FROM publication_receipts WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            return None if row is None else self._receipt_from_row(row)

    def database_settings(self) -> dict[str, int | str]:
        """Expose the effective durability settings for health checks."""

        with self._reading() as connection:
            return {
                "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
                "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
                "journal_mode": str(
                    connection.execute("PRAGMA journal_mode").fetchone()[0]
                ).casefold(),
                "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
            }
