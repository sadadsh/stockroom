"""Durable, per-user coordinator generation control for Stockroom.

This module is intentionally smaller than a job runner.  It decides which
process may mutate future operational state and issues a durable generation
fence to that process.  It does not dequeue work, publish libraries, expose an
API, or import any legacy orchestration.

Crash recovery has no time lease and no wall-clock takeover:

* the current-user Windows named mutex is the local liveness authority;
* ``WAIT_ABANDONED`` is the only path that may supersede an active row;
* SQLite compare-and-swap advances an irreversible generation;
* every guarded mutation validates both generation and opaque owner ID.

Shadow instances open ``Control.sqlite`` read-only.  Their successful health
checks never confer dequeue, mutation, publication, or mutex authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from .ports import (
    CurrentIdentityPort,
    MutexAcquireResult,
    NamedMutexFactoryPort,
    NamedMutexHandlePort,
    StoragePolicyPort,
    WindowsLocalNtfsStorage,
    is_windows_sid,
)
from .windows_mutex import current_user_mutex_name

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5_000
APPLICATION_ID = 0x5354434C
CONTROL_DATABASE_NAME = "Control.sqlite"
MAX_EVENT_PAYLOAD_BYTES = 65_536
MAX_JSON_DEPTH = 32
DEFAULT_AUTHORITY_SCOPE = "Coordinator"

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_OPAQUE_ID_PATTERN = re.compile(r"[0-9a-f]{32}", re.ASCII)
_EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", re.ASCII)
_AUTHORITY_SCOPE_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*",
    re.ASCII,
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_PROHIBITED_KEY_NAMES = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "clientsecret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "passwd",
        "privatekey",
        "refreshtoken",
        "secret",
        "session",
        "sessionid",
        "token",
    }
)
_PROHIBITED_VALUE_PREFIXES = (
    "-----begin private key",
    "akia",
    "basic ",
    "bearer ",
    "ghp_",
    "github_pat_",
    "sk-",
    "xoxb-",
    "xoxp-",
)


class ServiceMode(str, Enum):
    """Allowed service-control process roles."""

    SHADOW = "shadow"
    COORDINATOR = "coordinator"


class CoordinatorStatus(str, Enum):
    """Durable state of coordinator authority."""

    RELEASED = "released"
    ACTIVE = "active"


class ControlError(RuntimeError):
    """Base class for safe control-plane failures."""


class ControlDataCorruption(ControlError):
    """Control.sqlite failed a schema, integrity, or data invariant."""


class IdentityMismatch(ControlError):
    """The database is not bound to the process's current Windows SID."""


class StoragePolicyViolation(ControlError):
    """Control.sqlite is not on the required local NTFS storage."""


class ShadowModeViolation(ControlError):
    """A shadow process attempted to obtain or exercise mutation authority."""


class CoordinatorBusy(ControlError):
    """A healthy process currently owns the per-user coordinator mutex."""


class CoordinatorConflict(ControlError):
    """A generation fence or durable coordinator state is stale/conflicting."""


class MutexProtocolError(ControlError):
    """The injected named-mutex adapter violated its required contract."""


@dataclass(frozen=True, slots=True)
class GenerationFence:
    """Opaque proof of one acquired coordinator generation."""

    generation: int
    owner_id: str


@dataclass(frozen=True, slots=True)
class ControlSnapshot:
    """Read-only coordinator health projection."""

    mode: ServiceMode
    status: CoordinatorStatus
    generation: int
    owner_id: str | None
    event_sequence: int


@dataclass(frozen=True, slots=True)
class ControlEvent:
    """One append-only control-plane event."""

    sequence: int
    event_id: str
    generation: int
    event_type: str
    payload: dict[str, JsonValue]
    occurred_at: float


_MIGRATION_1_OBJECTS = {
    "schema_migrations": """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL CHECK (
                length(sha256) = 64
                AND sha256 NOT GLOB '*[^0-9a-f]*'
            ),
            applied_at REAL NOT NULL
        ) STRICT
    """,
    "runtime_identity": """
        CREATE TABLE runtime_identity (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            windows_sid TEXT NOT NULL,
            authority_scope TEXT NOT NULL,
            bound_at REAL NOT NULL
        ) STRICT
    """,
    "coordinator_state": """
        CREATE TABLE coordinator_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            generation INTEGER NOT NULL CHECK (generation >= 0),
            status TEXT NOT NULL CHECK (status IN ('released', 'active')),
            owner_id TEXT,
            updated_at REAL NOT NULL,
            CHECK (
                (status = 'released' AND owner_id IS NULL)
                OR (status = 'active' AND owner_id IS NOT NULL)
            )
        ) STRICT
    """,
    "coordinator_generations": """
        CREATE TABLE coordinator_generations (
            generation INTEGER PRIMARY KEY CHECK (generation > 0),
            owner_id TEXT NOT NULL UNIQUE,
            acquired_via TEXT NOT NULL CHECK (
                acquired_via IN ('normal', 'abandoned', 'recreated')
            ),
            acquired_at REAL NOT NULL,
            released_at REAL,
            release_reason TEXT CHECK (
                release_reason IN ('clean', 'abandoned', 'cold_crash')
            ),
            CHECK (
                (released_at IS NULL AND release_reason IS NULL)
                OR (released_at IS NOT NULL AND release_reason IS NOT NULL)
            )
        ) STRICT
    """,
    "control_events": """
        CREATE TABLE control_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            generation INTEGER NOT NULL REFERENCES coordinator_generations(generation),
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL CHECK (
                json_valid(payload_json)
                AND json_type(payload_json) = 'object'
            ),
            occurred_at REAL NOT NULL,
            schema_version INTEGER NOT NULL CHECK (schema_version = 1)
        ) STRICT
    """,
    "control_events_generation_sequence": """
        CREATE INDEX control_events_generation_sequence
        ON control_events(generation, sequence)
    """,
    "control_events_type_sequence": """
        CREATE INDEX control_events_type_sequence
        ON control_events(event_type, sequence)
    """,
}

_EXPECTED_TABLE_COLUMNS = {
    "schema_migrations": {"version", "name", "sha256", "applied_at"},
    "runtime_identity": {
        "singleton",
        "windows_sid",
        "authority_scope",
        "bound_at",
    },
    "coordinator_state": {
        "singleton",
        "generation",
        "status",
        "owner_id",
        "updated_at",
    },
    "coordinator_generations": {
        "generation",
        "owner_id",
        "acquired_via",
        "acquired_at",
        "released_at",
        "release_reason",
    },
    "control_events": {
        "sequence",
        "event_id",
        "generation",
        "event_type",
        "payload_json",
        "occurred_at",
        "schema_version",
    },
}

_EXPECTED_INDEXES = {
    "control_events_generation_sequence": (
        "control_events",
        ("generation", "sequence"),
        False,
    ),
    "control_events_type_sequence": (
        "control_events",
        ("event_type", "sequence"),
        False,
    ),
}


def _normalized_sql(value: str) -> str:
    return " ".join(value.split()).casefold()


def _migration_digest() -> str:
    canonical = "\n".join(
        f"{name}\0{_normalized_sql(statement)}" for name, statement in _MIGRATION_1_OBJECTS.items()
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


MIGRATION_1_SHA256 = _migration_digest()


def _timestamp(value: float | None = None) -> float:
    candidate = time.time() if value is None else value
    if type(candidate) not in (int, float):
        raise ValueError("timestamp must be a finite number")
    result = float(candidate)
    if not math.isfinite(result):
        raise ValueError("timestamp must be finite")
    return result


def _opaque_id() -> str:
    return secrets.token_hex(16)


def _require_opaque_id(value: object) -> str:
    if type(value) is not str or _OPAQUE_ID_PATTERN.fullmatch(value) is None:
        raise CoordinatorConflict("coordinator generation fence is invalid")
    return value


def _authority_scope(value: object) -> str:
    if (
        type(value) is not str
        or len(value) > 96
        or _AUTHORITY_SCOPE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("authority_scope is invalid")
    return value


def _validate_event_type(value: object, *, internal: bool) -> str:
    if type(value) is not str or len(value) > 64 or _EVENT_TYPE_PATTERN.fullmatch(value) is None:
        raise ValueError("event_type must be lowercase snake_case")
    if not internal and value.startswith("coordinator_"):
        raise ValueError("coordinator event types are reserved")
    return value


def _secret_shaped_text(value: str) -> bool:
    folded = value.strip().casefold()
    return any(folded.startswith(prefix) for prefix in _PROHIBITED_VALUE_PREFIXES)


def _normalize_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("control event payload exceeds the maximum JSON depth")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("control event payload contains a non-finite number")
        return
    if type(value) is str:
        if _secret_shaped_text(value):
            raise ValueError("control event payload contains prohibited secret-like data")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("control event payload keys must be strings")
            if _normalize_key(key) in _PROHIBITED_KEY_NAMES:
                raise ValueError("control event payload contains prohibited secret-like data")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("control event payload must contain only strict JSON values")


def _canonical_payload(payload: object) -> str:
    if type(payload) is not dict:
        raise ValueError("control event payload must be a JSON object")
    _validate_json_value(payload)
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload_bytes = encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("control event payload is not valid strict JSON") from exc
    if len(payload_bytes) > MAX_EVENT_PAYLOAD_BYTES:
        raise ValueError("control event payload exceeds the size limit")
    return encoded


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON constant")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decode_payload(value: object) -> dict[str, JsonValue]:
    if type(value) is not str:
        raise ControlDataCorruption("control event payload has an invalid storage type")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _validate_json_value(decoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ControlDataCorruption("control event payload is not valid strict JSON") from exc
    if type(decoded) is not dict:
        raise ControlDataCorruption("control event payload is not a JSON object")
    return decoded


class ServiceControl:
    """Control.sqlite-backed shadow/coordinator authority boundary."""

    def __init__(
        self,
        database: str | Path,
        *,
        mode: ServiceMode,
        identity: CurrentIdentityPort,
        mutex_factory: NamedMutexFactoryPort | None = None,
        storage_policy: StoragePolicyPort | None = None,
        authority_scope: str = DEFAULT_AUTHORITY_SCOPE,
    ):
        raw_database = Path(database)
        if not raw_database.is_absolute() or raw_database.name != CONTROL_DATABASE_NAME:
            raise StoragePolicyViolation(
                "service control requires an absolute path ending in Control.sqlite"
            )
        policy = WindowsLocalNtfsStorage() if storage_policy is None else storage_policy
        try:
            self.database = policy.validate(raw_database)
        except StoragePolicyViolation:
            raise
        except BaseException as exc:
            raise StoragePolicyViolation(
                "service control requires a fixed local NTFS volume"
            ) from exc
        if self.database.name != CONTROL_DATABASE_NAME:
            raise StoragePolicyViolation(
                "service control requires an absolute path ending in Control.sqlite"
            )
        if type(mode) is not ServiceMode:
            raise ValueError("mode must be a ServiceMode")

        self.mode = mode
        self.authority_scope = _authority_scope(authority_scope)
        self._identity = identity
        self._initial_sid = self._current_sid()
        self._mutex: NamedMutexHandlePort | None = None
        self._held_fence: GenerationFence | None = None

        if mode is ServiceMode.SHADOW:
            if not self.database.is_file() or self.database.stat().st_size == 0:
                raise ControlDataCorruption("shadow service requires an initialized Control.sqlite")
            self._validate_existing()
            return

        if mutex_factory is None:
            raise MutexProtocolError("coordinator mode requires a current-user named-mutex adapter")
        mutex_name = current_user_mutex_name(
            self._initial_sid,
            purpose=self.authority_scope,
        )
        try:
            self._mutex = mutex_factory.open_current_user(
                name=mutex_name,
                sid=self._initial_sid,
            )
        except BaseException as exc:
            raise MutexProtocolError("current-user named-mutex setup failed") from exc

        if not self.database.exists() or self.database.stat().st_size == 0:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self._initialize_or_join()
        self._validate_existing()

    def _current_sid(self) -> str:
        try:
            sid = self._identity.current_sid()
        except BaseException as exc:
            raise IdentityMismatch("current Windows identity could not be verified") from exc
        if not is_windows_sid(sid):
            raise IdentityMismatch("current Windows identity could not be verified")
        return sid

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        try:
            if readonly:
                uri = self.database.as_uri() + "?mode=ro"
                connection = sqlite3.connect(
                    uri,
                    isolation_level=None,
                    timeout=BUSY_TIMEOUT_MS / 1_000,
                    uri=True,
                )
                connection.execute("PRAGMA query_only=ON")
            else:
                connection = sqlite3.connect(
                    self.database,
                    isolation_level=None,
                    timeout=BUSY_TIMEOUT_MS / 1_000,
                )
                connection.execute("PRAGMA synchronous=FULL")
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            return connection
        except sqlite3.DatabaseError as exc:
            raise ControlDataCorruption("Control.sqlite could not be opened safely") from exc

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect(readonly=True)
        try:
            self._assert_bound_identity(connection)
            yield connection
        except sqlite3.DatabaseError as exc:
            raise ControlDataCorruption("Control.sqlite read failed") from exc
        finally:
            connection.close()

    @contextmanager
    def _writing(self) -> Iterator[sqlite3.Connection]:
        self._require_coordinator()
        connection = self._connect(readonly=False)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._assert_bound_identity(connection)
            yield connection
            connection.commit()
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise ControlDataCorruption("Control.sqlite mutation failed") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_or_join(self) -> None:
        connection = self._connect(readonly=False)
        initialized = False
        try:
            journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(journal_mode).casefold() != "wal":
                raise ControlDataCorruption("Control.sqlite refused WAL mode")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                LIMIT 1
                """
            ).fetchone()
            if existing is None:
                applied_at = _timestamp()
                for statement in _MIGRATION_1_OBJECTS.values():
                    connection.execute(statement)
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.execute(
                    """
                    INSERT INTO schema_migrations(
                        version, name, sha256, applied_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (1, "Initial control authority schema", MIGRATION_1_SHA256, applied_at),
                )
                connection.execute(
                    """
                    INSERT INTO runtime_identity(
                        singleton, windows_sid, authority_scope, bound_at
                    )
                    VALUES (1, ?, ?, ?)
                    """,
                    (self._initial_sid, self.authority_scope, applied_at),
                )
                connection.execute(
                    """
                    INSERT INTO coordinator_state(
                        singleton, generation, status, owner_id, updated_at
                    ) VALUES (1, 0, 'released', NULL, ?)
                    """,
                    (applied_at,),
                )
                initialized = True
            connection.commit()
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise ControlDataCorruption("Control.sqlite initialization failed") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if not initialized:
            self._validate_existing()

    @staticmethod
    def _schema_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{table}")')}

    @classmethod
    def _verify_schema(cls, connection: sqlite3.Connection) -> None:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        if (
            type(application_id) is not int
            or application_id != APPLICATION_ID
            or type(user_version) is not int
            or user_version != SCHEMA_VERSION
            or str(journal_mode).casefold() != "wal"
        ):
            raise ControlDataCorruption("Control.sqlite metadata is unsupported")

        rows = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'view', 'trigger')
            """
        ).fetchall()
        objects = {(str(row["type"]), str(row["name"])): row for row in rows}
        expected_names = set(_MIGRATION_1_OBJECTS)
        for row in rows:
            name = str(row["name"])
            if name == "sqlite_sequence" or name.startswith("sqlite_autoindex_"):
                continue
            if name not in expected_names:
                raise ControlDataCorruption("Control.sqlite contains an unsupported schema object")

        for name, expected_sql in _MIGRATION_1_OBJECTS.items():
            object_type = "index" if name in _EXPECTED_INDEXES else "table"
            row = objects.get((object_type, name))
            if row is None or type(row["sql"]) is not str:
                raise ControlDataCorruption("Control.sqlite is missing a required schema object")
            if _normalized_sql(row["sql"]) != _normalized_sql(expected_sql):
                raise ControlDataCorruption(
                    "Control.sqlite schema does not match its migration ledger"
                )

        for table, expected_columns in _EXPECTED_TABLE_COLUMNS.items():
            if cls._schema_columns(connection, table) != expected_columns:
                raise ControlDataCorruption(
                    "Control.sqlite table shape does not match its migration ledger"
                )

        for name, (table, columns, unique) in _EXPECTED_INDEXES.items():
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
                or actual_columns != columns
            ):
                raise ControlDataCorruption(
                    "Control.sqlite index does not match its migration ledger"
                )

        ledger = connection.execute(
            """
            SELECT version, name, sha256, applied_at
            FROM schema_migrations
            ORDER BY version
            """
        ).fetchall()
        if len(ledger) != 1:
            raise ControlDataCorruption("Control.sqlite migration ledger is not contiguous")
        row = ledger[0]
        if (
            type(row["version"]) is not int
            or row["version"] != 1
            or row["name"] != "Initial control authority schema"
            or type(row["sha256"]) is not str
            or _SHA256_PATTERN.fullmatch(row["sha256"]) is None
            or row["sha256"] != MIGRATION_1_SHA256
        ):
            raise ControlDataCorruption("Control.sqlite migration ledger is invalid")
        try:
            _timestamp(row["applied_at"])
        except ValueError as exc:
            raise ControlDataCorruption(
                "Control.sqlite migration ledger timestamp is invalid"
            ) from exc

        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        if [str(row[0]) for row in integrity_rows] != ["ok"]:
            raise ControlDataCorruption("Control.sqlite failed its integrity check")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ControlDataCorruption("Control.sqlite failed its foreign-key check")

    def _validate_existing(self) -> None:
        connection = self._connect(readonly=True)
        try:
            self._verify_schema(connection)
            self._assert_bound_identity(connection)
            self._read_state(connection)
        except sqlite3.DatabaseError as exc:
            raise ControlDataCorruption("Control.sqlite validation failed") from exc
        finally:
            connection.close()

    def _assert_bound_identity(self, connection: sqlite3.Connection) -> None:
        current_sid = self._current_sid()
        rows = connection.execute(
            """
            SELECT singleton, windows_sid, authority_scope, bound_at
            FROM runtime_identity
            """
        ).fetchall()
        if len(rows) != 1:
            raise ControlDataCorruption("Control.sqlite identity binding is invalid")
        row = rows[0]
        try:
            bound_at = _timestamp(row["bound_at"])
        except ValueError as exc:
            raise ControlDataCorruption("Control.sqlite identity binding is invalid") from exc
        stored_sid = row["windows_sid"]
        stored_scope = row["authority_scope"]
        if (
            type(row["singleton"]) is not int
            or row["singleton"] != 1
            or not is_windows_sid(stored_sid)
            or type(stored_scope) is not str
            or _AUTHORITY_SCOPE_PATTERN.fullmatch(stored_scope) is None
            or not math.isfinite(bound_at)
        ):
            raise ControlDataCorruption("Control.sqlite identity binding is invalid")
        if not secrets.compare_digest(stored_sid, current_sid):
            raise IdentityMismatch("Control.sqlite belongs to a different Windows identity")
        if not secrets.compare_digest(stored_scope, self.authority_scope):
            raise IdentityMismatch("Control.sqlite belongs to a different authority scope")

    @staticmethod
    def _read_state(
        connection: sqlite3.Connection,
    ) -> tuple[int, CoordinatorStatus, str | None]:
        rows = connection.execute(
            """
            SELECT singleton, generation, status, owner_id, updated_at
            FROM coordinator_state
            """
        ).fetchall()
        if len(rows) != 1:
            raise ControlDataCorruption("Control.sqlite coordinator state is invalid")
        row = rows[0]
        try:
            status = CoordinatorStatus(row["status"])
            _timestamp(row["updated_at"])
        except (TypeError, ValueError) as exc:
            raise ControlDataCorruption("Control.sqlite coordinator state is invalid") from exc
        generation = row["generation"]
        owner_id = row["owner_id"]
        if (
            type(row["singleton"]) is not int
            or row["singleton"] != 1
            or type(generation) is not int
            or generation < 0
            or (status is CoordinatorStatus.RELEASED and owner_id is not None)
            or (
                status is CoordinatorStatus.ACTIVE
                and (generation <= 0 or _OPAQUE_ID_PATTERN.fullmatch(owner_id or "") is None)
            )
        ):
            raise ControlDataCorruption("Control.sqlite coordinator state is invalid")
        return generation, status, owner_id

    def _require_coordinator(self) -> None:
        if self.mode is not ServiceMode.COORDINATOR:
            raise ShadowModeViolation(
                "shadow service cannot obtain or exercise coordinator authority"
            )

    def _require_held_fence(self, fence: GenerationFence) -> None:
        self._require_coordinator()
        if (
            type(fence) is not GenerationFence
            or type(fence.generation) is not int
            or fence.generation <= 0
        ):
            raise CoordinatorConflict("coordinator generation fence is invalid")
        _require_opaque_id(fence.owner_id)
        if self._held_fence != fence:
            raise CoordinatorConflict("coordinator generation fence is not held")

    @staticmethod
    def _assert_fence_in_database(
        connection: sqlite3.Connection,
        fence: GenerationFence,
    ) -> None:
        generation, status, owner_id = ServiceControl._read_state(connection)
        if (
            status is not CoordinatorStatus.ACTIVE
            or generation != fence.generation
            or owner_id != fence.owner_id
        ):
            raise CoordinatorConflict("coordinator generation fence is stale")

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        generation: int,
        event_type: str,
        payload_json: str,
        occurred_at: float,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO control_events(
                event_id,
                generation,
                event_type,
                payload_json,
                occurred_at,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                _opaque_id(),
                generation,
                event_type,
                payload_json,
                occurred_at,
                SCHEMA_VERSION,
            ),
        )
        if type(cursor.lastrowid) is not int or cursor.lastrowid <= 0:
            raise ControlDataCorruption("Control.sqlite event sequence is invalid")
        return cursor.lastrowid

    def _release_mutex_after_failed_acquire(self) -> None:
        if self._mutex is None:
            raise MutexProtocolError("coordinator named-mutex handle is unavailable")
        try:
            self._mutex.release()
        except BaseException as exc:
            raise MutexProtocolError(
                "coordinator named-mutex release failed after acquisition error"
            ) from exc

    def acquire(self, *, now: float | None = None) -> GenerationFence:
        """Non-blockingly acquire the next durable generation."""

        self._require_coordinator()
        if self._held_fence is not None:
            raise CoordinatorConflict("this process already holds a generation")
        if self._mutex is None:
            raise MutexProtocolError("coordinator named-mutex handle is unavailable")
        acquired_at = _timestamp(now)
        try:
            result = self._mutex.try_acquire()
        except BaseException as exc:
            raise MutexProtocolError("coordinator named-mutex claim failed") from exc
        if type(result) is not MutexAcquireResult:
            raise MutexProtocolError("coordinator named-mutex adapter returned an invalid result")
        if result is MutexAcquireResult.BUSY:
            raise CoordinatorBusy("another process owns coordinator liveness")

        try:
            with self._writing() as connection:
                generation, status, owner_id = self._read_state(connection)
                is_abandoned_recovery = (
                    status is CoordinatorStatus.ACTIVE and result is MutexAcquireResult.ABANDONED
                )
                is_cold_crash_recovery = (
                    status is CoordinatorStatus.ACTIVE and result is MutexAcquireResult.CREATED
                )
                if (
                    status is CoordinatorStatus.ACTIVE
                    and not is_abandoned_recovery
                    and not is_cold_crash_recovery
                ):
                    raise CoordinatorConflict(
                        "durable coordinator state is active without kernel crash evidence"
                    )
                if is_cold_crash_recovery:
                    acquired_via = "recreated"
                    acquisition_label = "recreated"
                elif result is MutexAcquireResult.ABANDONED:
                    acquired_via = "abandoned"
                    acquisition_label = "abandoned"
                else:
                    acquired_via = "normal"
                    acquisition_label = (
                        "created" if result is MutexAcquireResult.CREATED else "normal"
                    )

                if status is CoordinatorStatus.ACTIVE:
                    if owner_id is None:
                        raise ControlDataCorruption("Control.sqlite coordinator state is invalid")
                    released = connection.execute(
                        """
                        UPDATE coordinator_generations
                        SET released_at = ?, release_reason = ?
                        WHERE generation = ?
                          AND owner_id = ?
                          AND released_at IS NULL
                        """,
                        (
                            acquired_at,
                            "cold_crash" if is_cold_crash_recovery else "abandoned",
                            generation,
                            owner_id,
                        ),
                    )
                    if released.rowcount != 1:
                        raise CoordinatorConflict(
                            "abandoned coordinator generation could not be fenced"
                        )
                    self._append_event(
                        connection,
                        generation=generation,
                        event_type=(
                            "coordinator_cold_crash"
                            if is_cold_crash_recovery
                            else "coordinator_abandoned"
                        ),
                        payload_json="{}",
                        occurred_at=acquired_at,
                    )

                next_generation = generation + 1
                next_owner = _opaque_id()
                if status is CoordinatorStatus.ACTIVE:
                    updated = connection.execute(
                        """
                        UPDATE coordinator_state
                        SET generation = ?,
                            status = 'active',
                            owner_id = ?,
                            updated_at = ?
                        WHERE singleton = 1
                          AND generation = ?
                          AND status = 'active'
                          AND owner_id = ?
                        """,
                        (
                            next_generation,
                            next_owner,
                            acquired_at,
                            generation,
                            owner_id,
                        ),
                    )
                else:
                    updated = connection.execute(
                        """
                        UPDATE coordinator_state
                        SET generation = ?,
                            status = 'active',
                            owner_id = ?,
                            updated_at = ?
                        WHERE singleton = 1
                          AND generation = ?
                          AND status = 'released'
                          AND owner_id IS NULL
                        """,
                        (
                            next_generation,
                            next_owner,
                            acquired_at,
                            generation,
                        ),
                    )
                if updated.rowcount != 1:
                    raise CoordinatorConflict("coordinator generation compare-and-swap failed")
                connection.execute(
                    """
                    INSERT INTO coordinator_generations(
                        generation,
                        owner_id,
                        acquired_via,
                        acquired_at,
                        released_at,
                        release_reason
                    ) VALUES (?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        next_generation,
                        next_owner,
                        acquired_via,
                        acquired_at,
                    ),
                )
                self._append_event(
                    connection,
                    generation=next_generation,
                    event_type="coordinator_acquired",
                    payload_json=_canonical_payload({"acquisition": acquisition_label}),
                    occurred_at=acquired_at,
                )
                fence = GenerationFence(next_generation, next_owner)
        except BaseException:
            self._release_mutex_after_failed_acquire()
            raise

        self._held_fence = fence
        return fence

    def release(
        self,
        fence: GenerationFence,
        *,
        now: float | None = None,
    ) -> None:
        """Release an exactly matching generation, then release its mutex."""

        self._require_held_fence(fence)
        released_at = _timestamp(now)
        with self._writing() as connection:
            self._assert_fence_in_database(connection, fence)
            history = connection.execute(
                """
                UPDATE coordinator_generations
                SET released_at = ?, release_reason = 'clean'
                WHERE generation = ?
                  AND owner_id = ?
                  AND released_at IS NULL
                """,
                (released_at, fence.generation, fence.owner_id),
            )
            state = connection.execute(
                """
                UPDATE coordinator_state
                SET status = 'released', owner_id = NULL, updated_at = ?
                WHERE singleton = 1
                  AND generation = ?
                  AND status = 'active'
                  AND owner_id = ?
                """,
                (released_at, fence.generation, fence.owner_id),
            )
            if history.rowcount != 1 or state.rowcount != 1:
                raise CoordinatorConflict("coordinator generation release compare-and-swap failed")
            self._append_event(
                connection,
                generation=fence.generation,
                event_type="coordinator_released",
                payload_json="{}",
                occurred_at=released_at,
            )

        if self._mutex is None:
            raise MutexProtocolError("coordinator named-mutex handle is unavailable")
        try:
            self._mutex.release()
        except BaseException as exc:
            raise MutexProtocolError("coordinator named-mutex release failed") from exc
        self._held_fence = None

    def close(self) -> None:
        """Close an unowned native mutex handle without inventing a release.

        A released Win32 mutex object remains alive while any process retains an
        open handle. Explicit closure preserves the distinction between
        ``WAIT_ABANDONED`` and cold recreation and prevents completed authority
        generations from leaking kernel resources for the process lifetime.
        """

        if self._held_fence is not None:
            raise CoordinatorConflict(
                "coordinator control cannot close while holding a generation"
            )
        mutex = self._mutex
        if mutex is None:
            return
        closer = getattr(mutex, "close", None)
        if callable(closer):
            closer()
        self._mutex = None

    def record_event(
        self,
        fence: GenerationFence,
        event_type: str,
        payload: dict[str, JsonValue],
        *,
        now: float | None = None,
    ) -> int:
        """Append a strictly encoded event under an active generation fence."""

        self._require_held_fence(fence)
        safe_type = _validate_event_type(event_type, internal=False)
        payload_json = _canonical_payload(payload)
        occurred_at = _timestamp(now)
        with self._writing() as connection:
            self._assert_fence_in_database(connection, fence)
            return self._append_event(
                connection,
                generation=fence.generation,
                event_type=safe_type,
                payload_json=payload_json,
                occurred_at=occurred_at,
            )

    def checkpoint(self, fence: GenerationFence) -> tuple[int, int]:
        """Run a bounded passive WAL checkpoint under coordinator authority."""

        self._require_held_fence(fence)
        with self._reading() as connection:
            self._assert_fence_in_database(connection, fence)
        connection = self._connect(readonly=False)
        try:
            row = connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ControlDataCorruption("Control.sqlite checkpoint failed") from exc
        finally:
            connection.close()
        if (
            row is None
            or len(row) != 3
            or type(row[0]) is not int
            or type(row[1]) is not int
            or type(row[2]) is not int
            or row[0] != 0
        ):
            raise ControlDataCorruption("Control.sqlite checkpoint was not completed")
        return int(row[1]), int(row[2])

    def snapshot(self) -> ControlSnapshot:
        """Read current health without obtaining coordinator authority."""

        with self._reading() as connection:
            generation, status, owner_id = self._read_state(connection)
            event_sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM control_events"
            ).fetchone()[0]
        if type(event_sequence) is not int or event_sequence < 0:
            raise ControlDataCorruption("Control.sqlite event sequence is invalid")
        return ControlSnapshot(
            mode=self.mode,
            status=status,
            generation=generation,
            owner_id=owner_id,
            event_sequence=event_sequence,
        )

    def events(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 1_000,
    ) -> tuple[ControlEvent, ...]:
        """Read and strictly decode a monotonic page of control events."""

        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 1_000
        ):
            raise ValueError("event page bounds are invalid")
        with self._reading() as connection:
            rows = connection.execute(
                """
                SELECT
                    sequence,
                    event_id,
                    generation,
                    event_type,
                    payload_json,
                    occurred_at,
                    schema_version
                FROM control_events
                WHERE sequence > ?
                ORDER BY sequence
                LIMIT ?
                """,
                (after_sequence, limit),
            ).fetchall()
        events: list[ControlEvent] = []
        previous = after_sequence
        for row in rows:
            sequence = row["sequence"]
            generation = row["generation"]
            event_id = row["event_id"]
            event_type = row["event_type"]
            schema_version = row["schema_version"]
            try:
                occurred_at = _timestamp(row["occurred_at"])
            except ValueError as exc:
                raise ControlDataCorruption("Control.sqlite event timestamp is invalid") from exc
            if (
                type(sequence) is not int
                or sequence <= previous
                or type(generation) is not int
                or generation <= 0
                or type(event_id) is not str
                or _OPAQUE_ID_PATTERN.fullmatch(event_id) is None
                or type(event_type) is not str
                or _EVENT_TYPE_PATTERN.fullmatch(event_type) is None
                or type(schema_version) is not int
                or schema_version != SCHEMA_VERSION
            ):
                raise ControlDataCorruption("Control.sqlite event record is invalid")
            events.append(
                ControlEvent(
                    sequence=sequence,
                    event_id=event_id,
                    generation=generation,
                    event_type=event_type,
                    payload=_decode_payload(row["payload_json"]),
                    occurred_at=occurred_at,
                )
            )
            previous = sequence
        return tuple(events)
