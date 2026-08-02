"""Scoped Git publisher and crash reconciler for prepared component artifacts."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from stockroom.catalog import (
    CATALOG_APPLICATION_ID,
    CATALOG_SCHEMA_VERSION,
    PART_COLUMNS,
)
from stockroom.vcs import GitRepo
from stockroom.workflow import (
    ComponentPublicationReceipt,
    PublicationLease,
    PublicationOperation,
    PublicationState,
    WorkflowStore,
)

from .model import (
    ManifestValidationError,
    PreparedPublicationManifest,
    PreparedTarget,
    PublishAmbiguity,
    PublishCheckpoint,
    PublishConflict,
)

_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0
_CATALOG_METADATA_TABLE = "catalog_metadata"
_CATALOG_TABLE = "Parts"
_SQLITE_BUSY_TIMEOUT_MS = 5_000

CrashHook = Callable[[PublishCheckpoint], None]


@dataclass(frozen=True, slots=True)
class _CommitProof:
    oid: str
    scoped_tree_digest: str


@dataclass(frozen=True, slots=True)
class _CatalogSnapshot:
    metadata: tuple[tuple[str, str], ...]
    rows: tuple[tuple[str, ...], ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _parts(relative_path: str) -> tuple[str, ...]:
    return PurePosixPath(relative_path).parts


def _target_under(root: Path, relative_path: str) -> Path:
    return root.joinpath(*_parts(relative_path))


def _assert_no_links(
    root: Path,
    relative_path: str,
    *,
    require_file: bool,
) -> Path:
    if _is_link(root):
        raise ManifestValidationError("publication root cannot be a link or junction")
    current = root
    missing = False
    for part in _parts(relative_path):
        current = current / part
        if missing:
            continue
        if not current.exists():
            missing = True
            continue
        if _is_link(current):
            raise ManifestValidationError("publication paths cannot traverse links or junctions")
    if require_file and (missing or not current.is_file()):
        raise ManifestValidationError("prepared publication file is missing")
    if not missing:
        try:
            current.resolve(strict=True).relative_to(root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise ManifestValidationError("publication path escapes its declared root") from exc
    return current


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.stockroom-{uuid.uuid4().hex}.tmp"
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


class ScopedComponentPublisher:
    """Publish one immutable prepared manifest through every durable fence."""

    def __init__(
        self,
        store: WorkflowStore,
        repository: GitRepo,
        *,
        live_catalog_path: Path,
        machine_local_root: Path | None = None,
        crash_hook: CrashHook | None = None,
    ):
        self.store = store
        self.repository = repository
        self.repo_root = repository.root.absolute()
        self.live_catalog_path = live_catalog_path.absolute()
        self.machine_local_root = (
            None if machine_local_root is None else machine_local_root.absolute()
        )
        self.crash_hook = crash_hook

        if (
            not self.repo_root.is_absolute()
            or not self.repo_root.is_dir()
            or _is_link(self.repo_root)
            or not repository.is_git_repo()
        ):
            raise ManifestValidationError("publisher requires a non-linked Git repository root")
        if (
            not self.live_catalog_path.is_absolute()
            or self.live_catalog_path.name.casefold() != "catalog.sqlite"
            or not self.live_catalog_path.parent.is_dir()
            or _is_link(self.live_catalog_path.parent)
        ):
            raise ManifestValidationError("live catalog must be an absolute Catalog.sqlite path")
        if self.machine_local_root is not None and (
            not self.machine_local_root.is_dir() or _is_link(self.machine_local_root)
        ):
            raise ManifestValidationError(
                "machine-local root must be an existing non-linked directory"
            )

    def _checkpoint(self, checkpoint: PublishCheckpoint) -> None:
        if self.crash_hook is not None:
            self.crash_hook(checkpoint)

    def _run_git(
        self,
        *args: str,
        input_bytes: bytes | None = None,
        extra_environment: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        if extra_environment:
            environment.update(extra_environment)
        completed = subprocess.run(
            [
                self.repository.git,
                "-C",
                str(self.repo_root),
                *args,
            ],
            input=input_bytes,
            capture_output=True,
            creationflags=_NO_WINDOW,
            env=environment,
        )
        if check and completed.returncode != 0:
            raise PublishConflict("scoped Git operation failed without changing foreign work")
        return completed

    def _git_text(self, *args: str, check: bool = True) -> str:
        output = self._run_git(*args, check=check).stdout
        try:
            return output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublishAmbiguity("Git evidence is not canonical UTF-8") from exc

    @contextmanager
    def _repo_write_lock(self) -> Iterator[None]:
        with self.repository._write_lock():
            yield

    def _read_catalog_snapshot(
        self,
        path: Path,
        *,
        immutable: bool,
    ) -> _CatalogSnapshot:
        uri = path.resolve(strict=True).as_uri() + (
            "?mode=ro&immutable=1" if immutable else "?mode=ro"
        )
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{_CATALOG_METADATA_TABLE}")')
            }
            part_columns = tuple(
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{_CATALOG_TABLE}")')
            )
            metadata = tuple(
                (str(row["key"]), str(row["value"]))
                for row in connection.execute(
                    f"""
                    SELECT key, value
                    FROM "{_CATALOG_METADATA_TABLE}"
                    ORDER BY key
                    """
                )
            )
            quoted_columns = ", ".join(f'"{column}"' for column in PART_COLUMNS)
            rows = tuple(
                tuple(str(row[column]) for column in PART_COLUMNS)
                for row in connection.execute(
                    f"""
                    SELECT {quoted_columns}
                    FROM "{_CATALOG_TABLE}"
                    ORDER BY "Component ID"
                    """
                )
            )
        except sqlite3.DatabaseError as exc:
            raise ManifestValidationError("catalog projection failed SQLite validation") from exc
        finally:
            if connection is not None:
                connection.close()
        if (
            [str(row[0]) for row in integrity] != ["ok"]
            or foreign_keys
            or application_id != CATALOG_APPLICATION_ID
            or user_version != CATALOG_SCHEMA_VERSION
            or columns != {"key", "value"}
            or part_columns != PART_COLUMNS
            or not rows
        ):
            raise ManifestValidationError("catalog projection schema or integrity proof is invalid")
        return _CatalogSnapshot(metadata=metadata, rows=rows)

    def _validate_staged_catalog(
        self,
        path: Path,
        manifest: PreparedPublicationManifest,
    ) -> _CatalogSnapshot:
        if _sha256_file(path) != manifest.catalog_sha256:
            raise ManifestValidationError("staged catalog byte digest does not match")
        snapshot = self._read_catalog_snapshot(path, immutable=True)
        metadata = dict(snapshot.metadata)
        component_index = PART_COLUMNS.index("Component ID")
        if (
            metadata.get("catalog_revision") != manifest.catalog_revision
            or metadata.get("catalog_semantic_digest") != manifest.catalog_semantic_digest
            or manifest.component_id not in {row[component_index] for row in snapshot.rows}
        ):
            raise ManifestValidationError(
                "staged catalog revision, semantic digest, or component differs"
            )
        return snapshot

    def _validate_manifest_files(
        self,
        manifest: PreparedPublicationManifest,
    ) -> None:
        staging_root = manifest.staging_root.absolute()
        if (
            not staging_root.is_dir()
            or _is_link(staging_root)
            or staging_root.resolve(strict=True) == self.repo_root.resolve(strict=True)
        ):
            raise ManifestValidationError("staging root must be a distinct non-linked directory")
        try:
            staging_root.resolve(strict=True).relative_to(self.repo_root.resolve(strict=True))
        except ValueError:
            pass
        else:
            raise ManifestValidationError(
                "publication staging root cannot be inside the Git repository"
            )

        for prepared in (*manifest.tracked_files, *manifest.machine_local_files):
            source = _assert_no_links(
                staging_root,
                prepared.target_path,
                require_file=True,
            )
            if _sha256_file(source) != prepared.sha256:
                raise ManifestValidationError("prepared publication file digest does not match")
        catalog = _assert_no_links(
            staging_root,
            manifest.catalog_staged_path,
            require_file=True,
        )
        self._validate_staged_catalog(catalog, manifest)

        for prepared in manifest.tracked_files:
            target = _assert_no_links(
                self.repo_root,
                prepared.target_path,
                require_file=False,
            )
            if target.exists() and not target.is_file():
                raise ManifestValidationError("tracked publication target is not a regular file")
        if manifest.machine_local_files and self.machine_local_root is None:
            raise ManifestValidationError(
                "manifest has machine-local files but no local root was configured"
            )
        if self.machine_local_root is not None:
            for prepared in manifest.machine_local_files:
                target = _assert_no_links(
                    self.machine_local_root,
                    prepared.target_path,
                    require_file=False,
                )
                if target.exists() and not target.is_file():
                    raise ManifestValidationError("machine-local target is not a regular file")

    def _validate_plan(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        operation: PublicationOperation,
    ) -> None:
        if (
            manifest.publication_id != operation.publication_id
            or manifest.component_id != operation.component_id
            or lease.publication_id != operation.publication_id
            or lease.component_id != operation.component_id
        ):
            raise PublishConflict("manifest, lease, and publication identity do not match")
        if operation.manifest_digest != manifest.digest:
            raise PublishConflict("prepared manifest does not match the durable publication plan")
        if not self.repository.has_commit(operation.expected_base_commit):
            raise PublishConflict("expected publication base commit is unavailable")
        self._validate_manifest_files(manifest)

    def _tracked_paths(
        self,
        manifest: PreparedPublicationManifest,
    ) -> list[Path]:
        return [
            _target_under(self.repo_root, prepared.target_path)
            for prepared in manifest.tracked_files
        ]

    def _base_blob(
        self,
        base_commit: str,
        relative_path: str,
    ) -> bytes | None:
        spec = f"{base_commit}:{relative_path}"
        exists = self._run_git("cat-file", "-e", spec, check=False)
        if exists.returncode != 0:
            return None
        return self._run_git("show", spec).stdout

    def _require_manifest_changes(
        self,
        manifest: PreparedPublicationManifest,
        base_commit: str,
    ) -> None:
        for prepared in manifest.tracked_files:
            previous = self._base_blob(base_commit, prepared.target_path)
            if previous is not None and _sha256_bytes(previous) == prepared.sha256:
                raise ManifestValidationError(
                    "Git allowlist contains a path unchanged from the expected base"
                )

    def _tree_entry_oid(self, revision: str, relative_path: str) -> str | None:
        output = self._run_git(
            "ls-tree",
            "-z",
            revision,
            "--",
            relative_path,
        ).stdout
        if not output:
            return None
        records = [record for record in output.split(b"\x00") if record]
        if len(records) != 1 or b"\t" not in records[0]:
            raise PublishAmbiguity("Git tree path has an ambiguous entry")
        header, _path = records[0].split(b"\t", 1)
        fields = header.split()
        if len(fields) != 3 or fields[1] != b"blob":
            raise PublishAmbiguity("publication target is not a Git blob")
        return fields[2].decode("ascii")

    def _index_entry_oid(self, relative_path: str) -> str | None:
        output = self._run_git(
            "ls-files",
            "--stage",
            "-z",
            "--",
            relative_path,
        ).stdout
        if not output:
            return None
        records = [record for record in output.split(b"\x00") if record]
        if len(records) != 1 or b"\t" not in records[0]:
            raise PublishAmbiguity("publication target has conflicted or ambiguous index entries")
        header, _path = records[0].split(b"\t", 1)
        fields = header.split()
        if len(fields) != 3 or fields[2] != b"0":
            raise PublishAmbiguity("publication target has a non-stage-zero index entry")
        return fields[1].decode("ascii")

    def _require_index_at_base(
        self,
        manifest: PreparedPublicationManifest,
        base_commit: str,
    ) -> None:
        for prepared in manifest.tracked_files:
            if self._index_entry_oid(prepared.target_path) != self._tree_entry_oid(
                base_commit,
                prepared.target_path,
            ):
                raise PublishAmbiguity("publication target index differs from the expected base")

    def _backup_root(
        self,
        manifest: PreparedPublicationManifest,
        label: str,
    ) -> Path:
        root = (
            manifest.staging_root
            / ".stockroom-publish-backups"
            / manifest.publication_id
            / label
            / uuid.uuid4().hex
        )
        root.mkdir(parents=True, exist_ok=False)
        return root

    def _converge_materialized(
        self,
        manifest: PreparedPublicationManifest,
        base_commit: str,
    ) -> None:
        backup_root = self._backup_root(manifest, "Tracked")
        for prepared in manifest.tracked_files:
            source = _target_under(
                manifest.staging_root,
                prepared.target_path,
            )
            target = _target_under(self.repo_root, prepared.target_path)
            current_digest = (
                _sha256_file(target) if target.is_file() and not _is_link(target) else None
            )
            if current_digest == prepared.sha256:
                continue
            base_blob = self._base_blob(base_commit, prepared.target_path)
            if base_blob is None:
                if target.exists():
                    raise PublishAmbiguity("new publication target contains foreign material")
            else:
                base_digest = _sha256_bytes(base_blob)
                if current_digest != base_digest:
                    raise PublishAmbiguity(
                        "publication target differs from both base and desired bytes"
                    )
                backup = _target_under(backup_root, prepared.target_path)
                _atomic_copy(target, backup)
            _atomic_copy(source, target)
            if _sha256_file(target) != prepared.sha256:
                raise ManifestValidationError(
                    "materialized tracked file failed digest verification"
                )
            self._checkpoint(PublishCheckpoint.MATERIALIZATION_PROGRESS)

    def _require_materialized(
        self,
        manifest: PreparedPublicationManifest,
    ) -> None:
        for prepared in manifest.tracked_files:
            target = _target_under(self.repo_root, prepared.target_path)
            if not target.is_file() or _is_link(target) or _sha256_file(target) != prepared.sha256:
                raise PublishAmbiguity("commit-fenced working tree no longer matches its manifest")

    def _all_commit_oids(self) -> tuple[str, ...]:
        output = self._git_text(
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype)",
        )
        return tuple(
            line.split(" ", 1)[0] for line in output.splitlines() if line.endswith(" commit")
        )

    def _commit_message(self, oid: str) -> str:
        value = self._run_git("show", "-s", "--format=%B", oid).stdout
        return value.decode("utf-8", errors="replace").rstrip("\n")

    def _find_publication_commit(
        self,
        manifest: PreparedPublicationManifest,
    ) -> str | None:
        trailer = f"Stockroom-Publish-ID: {manifest.publication_id}"
        matching = [
            oid
            for oid in self._all_commit_oids()
            if trailer in self._commit_message(oid).splitlines()
        ]
        if len(matching) > 1:
            raise PublishAmbiguity("multiple Git commits carry the publication trailer")
        return None if not matching else matching[0]

    def _changed_paths(self, oid: str) -> tuple[str, ...]:
        output = self._run_git(
            "-c",
            "core.quotepath=false",
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            oid,
        ).stdout
        try:
            decoded = output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublishAmbiguity("commit paths are not canonical UTF-8") from exc
        return tuple(path for path in decoded.split("\x00") if path)

    def _commit_parent(self, oid: str) -> str:
        fields = self._git_text("rev-list", "--parents", "-n", "1", oid).split()
        if len(fields) != 2 or fields[0] != oid:
            raise PublishAmbiguity("publication commit does not have exactly one expected parent")
        return fields[1]

    def _scoped_tree_digest(
        self,
        targets: list[tuple[str, str]],
    ) -> str:
        digest = hashlib.sha256(b"stockroom.scoped-tree.v1\0")
        for path, sha256 in sorted(targets, key=lambda item: item[0].casefold()):
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(bytes.fromhex(sha256[7:]))
            digest.update(b"\0")
        return f"sha256:{digest.hexdigest()}"

    def _verify_commit(
        self,
        oid: str,
        manifest: PreparedPublicationManifest,
        operation: PublicationOperation,
        *,
        require_reachable: bool,
    ) -> _CommitProof:
        if not self.repository.has_commit(oid):
            raise PublishAmbiguity("publication Git object is not a commit")
        if self._commit_message(oid) != manifest.final_commit_message:
            raise PublishAmbiguity("publication commit message or required trailers do not match")
        if self._commit_parent(oid) != operation.expected_base_commit:
            raise PublishAmbiguity("publication commit parent is not the expected base")
        expected_paths = tuple(
            sorted(
                (target.target_path for target in manifest.tracked_files),
                key=str.casefold,
            )
        )
        actual_paths = tuple(sorted(self._changed_paths(oid), key=str.casefold))
        if actual_paths != expected_paths:
            raise PublishAmbiguity("publication commit contains paths outside its exact allowlist")

        verified: list[tuple[str, str]] = []
        for prepared in manifest.tracked_files:
            blob = self._run_git(
                "show",
                f"{oid}:{prepared.target_path}",
            ).stdout
            actual_digest = _sha256_bytes(blob)
            if actual_digest != prepared.sha256:
                # Git LFS clean-filters an exact prepared binary into a pointer before it enters
                # the commit tree.  The pointer is the committed representation, while the
                # manifest intentionally proves the original CAD payload.  Accept only the
                # canonical three-line v1 pointer whose OID and byte size both match that exact
                # staged payload; every other transform remains an ambiguity.
                source = _target_under(manifest.staging_root, prepared.target_path)
                source_bytes = source.read_bytes()
                expected_pointer = (
                    "version https://git-lfs.github.com/spec/v1\n"
                    f"oid {prepared.sha256}\n"
                    f"size {len(source_bytes)}\n"
                ).encode("ascii")
                normalized_text = source_bytes.replace(b"\r\n", b"\n")
                exact_lf_normalization = (
                    b"\x00" not in source_bytes
                    and normalized_text != source_bytes
                    and blob == normalized_text
                )
                if blob != expected_pointer and not exact_lf_normalization:
                    raise PublishAmbiguity(
                        "publication commit tree digest does not match its manifest"
                    )
            verified.append((prepared.target_path, prepared.sha256))
        if require_reachable and not self.repository.is_ancestor(
            oid,
            self.repository.head(),
        ):
            raise PublishAmbiguity("publication commit is not reachable from the current branch")
        return _CommitProof(
            oid=oid,
            scoped_tree_digest=self._scoped_tree_digest(verified),
        )

    def _align_real_index(
        self,
        oid: str,
        manifest: PreparedPublicationManifest,
        base_commit: str,
    ) -> None:
        safe_paths: list[str] = []
        for target in manifest.tracked_files:
            current_index = self._index_entry_oid(target.target_path)
            committed = self._tree_entry_oid(oid, target.target_path)
            if current_index == committed:
                continue
            base = self._tree_entry_oid(base_commit, target.target_path)
            worktree = _target_under(self.repo_root, target.target_path)
            if (
                current_index == base
                and worktree.is_file()
                and _sha256_file(worktree) == target.sha256
            ):
                safe_paths.append(target.target_path)
        if safe_paths:
            self._run_git(
                "reset",
                "-q",
                oid,
                "--",
                *safe_paths,
            )

    def _install_existing_commit(
        self,
        oid: str,
        manifest: PreparedPublicationManifest,
        operation: PublicationOperation,
    ) -> _CommitProof:
        self._verify_commit(
            oid,
            manifest,
            operation,
            require_reachable=False,
        )
        head = self.repository.head()
        if not self.repository.is_ancestor(oid, head):
            if head != operation.expected_base_commit:
                raise PublishAmbiguity(
                    "orphaned publication commit cannot be installed over an advanced branch"
                )
            reference = self._git_text("symbolic-ref", "-q", "HEAD").strip()
            if not reference:
                raise PublishConflict("publication requires an attached Git branch")
            updated = self._run_git(
                "update-ref",
                reference,
                oid,
                operation.expected_base_commit,
                check=False,
            )
            if updated.returncode != 0:
                raise PublishConflict("Git base advanced while installing the fenced publication")
        self._align_real_index(
            oid,
            manifest,
            operation.expected_base_commit,
        )
        return self._verify_commit(
            oid,
            manifest,
            operation,
            require_reachable=True,
        )

    def _create_scoped_commit(
        self,
        manifest: PreparedPublicationManifest,
        operation: PublicationOperation,
    ) -> _CommitProof:
        if self.repository.head() != operation.expected_base_commit:
            raise PublishConflict("Git base advanced before the scoped publication commit")
        reference = self._git_text("symbolic-ref", "-q", "HEAD").strip()
        if not reference:
            raise PublishConflict("publication requires an attached Git branch")
        self.repository._set_test_identity_if_missing()

        with tempfile.TemporaryDirectory(prefix="stockroom-publish-index-") as directory:
            index_path = Path(directory) / "index"
            environment = {"GIT_INDEX_FILE": str(index_path)}
            self._run_git(
                "read-tree",
                operation.expected_base_commit,
                extra_environment=environment,
            )
            self._run_git(
                "add",
                "-A",
                "--",
                *(target.target_path for target in manifest.tracked_files),
                extra_environment=environment,
            )
            staged = self._run_git(
                "-c",
                "core.quotepath=false",
                "diff",
                "--cached",
                "--name-only",
                "-z",
                operation.expected_base_commit,
                extra_environment=environment,
            ).stdout
            try:
                staged_paths = tuple(path for path in staged.decode("utf-8").split("\x00") if path)
            except UnicodeDecodeError as exc:
                raise PublishAmbiguity("temporary Git index contains noncanonical paths") from exc
            expected_paths = tuple(target.target_path for target in manifest.tracked_files)
            if sorted(staged_paths, key=str.casefold) != sorted(
                expected_paths,
                key=str.casefold,
            ):
                raise PublishAmbiguity(
                    "temporary Git index differs from the exact publication allowlist"
                )
            tree_oid = (
                self._run_git(
                    "write-tree",
                    extra_environment=environment,
                )
                .stdout.decode("ascii")
                .strip()
            )
            commit_oid = (
                self._run_git(
                    "commit-tree",
                    tree_oid,
                    "-p",
                    operation.expected_base_commit,
                    input_bytes=(manifest.final_commit_message + "\n").encode("utf-8"),
                )
                .stdout.decode("ascii")
                .strip()
            )

        proof = self._verify_commit(
            commit_oid,
            manifest,
            operation,
            require_reachable=False,
        )
        updated = self._run_git(
            "update-ref",
            reference,
            commit_oid,
            operation.expected_base_commit,
            check=False,
        )
        if updated.returncode != 0:
            raise PublishConflict("Git base advanced during the commit reference compare-and-swap")
        if self._git_text("symbolic-ref", "-q", "HEAD").strip() != reference:
            raise PublishAmbiguity("current Git branch changed during publication")
        self._align_real_index(
            commit_oid,
            manifest,
            operation.expected_base_commit,
        )
        return self._verify_commit(
            proof.oid,
            manifest,
            operation,
            require_reachable=True,
        )

    def _record_git(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        proof: _CommitProof,
        *,
        now: float | None,
    ) -> PublicationOperation:
        operation = self.store.record_git_commit(
            manifest.publication_id,
            lease.worker_id,
            git_commit_oid=proof.oid,
            verified_tree_digest=proof.scoped_tree_digest,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            now=now,
        )
        self._checkpoint(PublishCheckpoint.GIT_COMMIT_RECORDED)
        return operation

    def _backup_local_file(
        self,
        source: Path,
        manifest: PreparedPublicationManifest,
        label: str,
    ) -> None:
        if not source.exists():
            return
        if not source.is_file() or _is_link(source):
            raise PublishAmbiguity("local projection target is not a regular owned file")
        backup_root = self._backup_root(manifest, "Local")
        backup = backup_root / f"{label}.before"
        _atomic_copy(source, backup)

    def _activate_machine_local_files(
        self,
        manifest: PreparedPublicationManifest,
    ) -> None:
        if not manifest.machine_local_files:
            return
        if self.machine_local_root is None:
            raise ManifestValidationError("machine-local publication root is not configured")
        for prepared in manifest.machine_local_files:
            source = _target_under(manifest.staging_root, prepared.target_path)
            target = _target_under(self.machine_local_root, prepared.target_path)
            if target.exists() and _sha256_file(target) == prepared.sha256:
                continue
            self._backup_local_file(
                target,
                manifest,
                PurePosixPath(prepared.target_path).name,
            )
            _atomic_copy(source, target)
            if _sha256_file(target) != prepared.sha256:
                raise PublishAmbiguity("machine-local projection activation failed verification")

    def _activate_catalog(
        self,
        manifest: PreparedPublicationManifest,
    ) -> None:
        staged = _target_under(
            manifest.staging_root,
            manifest.catalog_staged_path,
        )
        desired = self._validate_staged_catalog(staged, manifest)
        live = self.live_catalog_path
        if _is_link(live):
            raise PublishAmbiguity("live Catalog.sqlite cannot be a link")
        if not live.exists():
            _atomic_copy(staged, live)
            connection = sqlite3.connect(live, isolation_level=None)
            try:
                connection.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
                journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                connection.execute("PRAGMA synchronous=FULL")
            except sqlite3.DatabaseError as exc:
                raise PublishConflict("new live catalog could not enter WAL mode") from exc
            finally:
                connection.close()
            if str(journal_mode).casefold() != "wal":
                raise PublishConflict("new live catalog refused WAL mode")
        else:
            if not live.is_file():
                raise PublishAmbiguity("live Catalog.sqlite is not a regular file")
            self._read_catalog_snapshot(live, immutable=False)
            connection = sqlite3.connect(
                live,
                isolation_level=None,
                timeout=_SQLITE_BUSY_TIMEOUT_MS / 1_000,
            )
            try:
                connection.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA synchronous=FULL")
                journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if str(journal_mode).casefold() != "wal":
                    raise PublishConflict("live catalog refused WAL mode")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(f'DELETE FROM "{_CATALOG_TABLE}"')
                quoted_columns = ", ".join(f'"{column}"' for column in PART_COLUMNS)
                placeholders = ", ".join("?" for _ in PART_COLUMNS)
                connection.executemany(
                    f"""
                    INSERT INTO "{_CATALOG_TABLE}" ({quoted_columns})
                    VALUES ({placeholders})
                    """,
                    desired.rows,
                )
                connection.execute(f'DELETE FROM "{_CATALOG_METADATA_TABLE}"')
                connection.executemany(
                    f"""
                    INSERT INTO "{_CATALOG_METADATA_TABLE}"(key, value)
                    VALUES (?, ?)
                    """,
                    desired.metadata,
                )
                if connection.execute("PRAGMA foreign_key_check").fetchall():
                    raise PublishAmbiguity(
                        "live catalog activation failed foreign-key verification"
                    )
                connection.commit()
            except sqlite3.DatabaseError as exc:
                connection.rollback()
                raise PublishConflict("live catalog activation was busy or invalid") from exc
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

        actual = self._read_catalog_snapshot(live, immutable=False)
        if actual != desired:
            raise PublishAmbiguity("live catalog readback differs from the staged projection")
        metadata = dict(actual.metadata)
        if (
            metadata.get("catalog_revision") != manifest.catalog_revision
            or metadata.get("catalog_semantic_digest") != manifest.catalog_semantic_digest
        ):
            raise PublishAmbiguity("live catalog semantic proof differs after activation")

    def _activate_and_complete(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        operation: PublicationOperation,
        *,
        now: float | None,
    ) -> ComponentPublicationReceipt:
        if operation.state is PublicationState.GIT_COMMITTED:
            self._activate_catalog(manifest)
            self._activate_machine_local_files(manifest)
            self._checkpoint(PublishCheckpoint.CATALOG_ACTIVATED)
            operation = self.store.record_catalog_activation(
                manifest.publication_id,
                lease.worker_id,
                catalog_revision=manifest.catalog_revision,
                catalog_semantic_digest=manifest.catalog_semantic_digest,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                now=now,
            )
            self._checkpoint(PublishCheckpoint.CATALOG_RECORDED)
        elif operation.state is PublicationState.CATALOG_ACTIVATED:
            if (
                operation.catalog_revision != manifest.catalog_revision
                or operation.catalog_semantic_digest != manifest.catalog_semantic_digest
            ):
                raise PublishAmbiguity("durable catalog proof differs from the prepared manifest")
            self._activate_catalog(manifest)
            self._activate_machine_local_files(manifest)
        else:
            raise PublishConflict("publication is not ready for local catalog activation")

        receipt_payload = {
            "catalog_revision": manifest.catalog_revision,
            "catalog_semantic_digest": manifest.catalog_semantic_digest,
            "component_id": manifest.component_id,
            "git_commit_oid": operation.git_commit_oid,
            "local_preparation_digest": manifest.local_preparation_digest,
            "machine_local_files": [
                {
                    "path": target.target_path,
                    "sha256": target.sha256,
                }
                for target in sorted(
                    manifest.machine_local_files,
                    key=lambda target: target.target_path.casefold(),
                )
            ],
            "publication_id": manifest.publication_id,
            "tracked_files": [
                {
                    "path": target.target_path,
                    "sha256": target.sha256,
                }
                for target in sorted(
                    manifest.tracked_files,
                    key=lambda target: target.target_path.casefold(),
                )
            ],
            "verified_tree_digest": operation.verified_tree_digest,
        }
        self.store.complete_publication(
            manifest.publication_id,
            lease.worker_id,
            receipt_payload,
            lease_token=lease.lease_token,
            lease_generation=lease.lease_generation,
            now=now,
        )
        receipt = self.store.get_component_publication_receipt(manifest.publication_id)
        if receipt is None:
            raise PublishAmbiguity("completed publication did not produce its durable receipt")
        return receipt

    def publish(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        *,
        now: float | None = None,
    ) -> ComponentPublicationReceipt:
        """Execute a new PREPARING publication through durable completion."""

        operation = self.store.get_publication_operation(manifest.publication_id)
        self._validate_plan(manifest, lease, operation)
        if operation.state is not PublicationState.PREPARING:
            raise PublishConflict("non-preparing publication must use crash reconciliation")

        with self._repo_write_lock():
            if self._find_publication_commit(manifest) is not None:
                raise PublishAmbiguity(
                    "a publication commit exists before its durable commit fence"
                )
            if self.repository.head() != operation.expected_base_commit:
                raise PublishConflict("Git base differs from the durable publication plan")
            tracked_paths = self._tracked_paths(manifest)
            if not self.repository.is_clean(tracked_paths):
                raise PublishConflict("one or more exact publication target paths are dirty")
            self._require_manifest_changes(
                manifest,
                operation.expected_base_commit,
            )
            self._require_index_at_base(
                manifest,
                operation.expected_base_commit,
            )
            operation = self.store.arm_publication_commit(
                manifest.publication_id,
                lease.worker_id,
                lease_token=lease.lease_token,
                lease_generation=lease.lease_generation,
                now=now,
            )
            self._checkpoint(PublishCheckpoint.COMMIT_FENCED)
            self._converge_materialized(
                manifest,
                operation.expected_base_commit,
            )
            self._require_materialized(manifest)
            proof = self._create_scoped_commit(manifest, operation)
            self._checkpoint(PublishCheckpoint.GIT_COMMIT_CREATED)
            operation = self._record_git(
                manifest,
                lease,
                proof,
                now=now,
            )

        return self._activate_and_complete(
            manifest,
            lease,
            operation,
            now=now,
        )

    def reconcile(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        *,
        now: float | None = None,
    ) -> ComponentPublicationReceipt:
        """Resume one fenced publication without duplicating external effects."""

        operation = self.store.get_publication_operation(manifest.publication_id)
        self._validate_plan(manifest, lease, operation)
        if operation.state not in {
            PublicationState.COMMIT_FENCED,
            PublicationState.GIT_COMMITTED,
            PublicationState.CATALOG_ACTIVATED,
        }:
            raise PublishConflict("publication is not in a reconcilable post-fence state")

        if operation.state is PublicationState.COMMIT_FENCED:
            with self._repo_write_lock():
                commit_oid = self._find_publication_commit(manifest)
                if commit_oid is None:
                    if self.repository.head() != operation.expected_base_commit:
                        raise PublishAmbiguity(
                            "fenced publication has no commit and its Git base advanced"
                        )
                    self._require_index_at_base(
                        manifest,
                        operation.expected_base_commit,
                    )
                    self._converge_materialized(
                        manifest,
                        operation.expected_base_commit,
                    )
                    self._require_materialized(manifest)
                    proof = self._create_scoped_commit(manifest, operation)
                    self._checkpoint(PublishCheckpoint.GIT_COMMIT_CREATED)
                else:
                    proof = self._install_existing_commit(
                        commit_oid,
                        manifest,
                        operation,
                    )
                operation = self._record_git(
                    manifest,
                    lease,
                    proof,
                    now=now,
                )
        else:
            if operation.git_commit_oid is None or operation.verified_tree_digest is None:
                raise PublishAmbiguity("post-Git publication is missing durable Git proof")
            with self._repo_write_lock():
                commit_oid = self._find_publication_commit(manifest)
                if commit_oid != operation.git_commit_oid:
                    raise PublishAmbiguity(
                        "durable Git proof does not match unique commit evidence"
                    )
                proof = self._install_existing_commit(
                    commit_oid,
                    manifest,
                    operation,
                )
                if proof.scoped_tree_digest != operation.verified_tree_digest:
                    raise PublishAmbiguity("durable scoped tree digest differs from Git evidence")

        return self._activate_and_complete(
            manifest,
            lease,
            operation,
            now=now,
        )


class PublicationReconciler:
    """Narrow named facade for startup reconciliation."""

    def __init__(self, publisher: ScopedComponentPublisher):
        self.publisher = publisher

    def reconcile(
        self,
        manifest: PreparedPublicationManifest,
        lease: PublicationLease,
        *,
        now: float | None = None,
    ) -> ComponentPublicationReceipt:
        return self.publisher.reconcile(manifest, lease, now=now)


__all__ = [
    "PublicationReconciler",
    "ScopedComponentPublisher",
]
