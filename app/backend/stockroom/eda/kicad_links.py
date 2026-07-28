"""Portable KiCad library-table projection for immutable native artifacts.

The generated files are Stockroom-owned, tracked table fragments.  They are not
KiCad's global ``sym-lib-table`` or ``fp-lib-table`` and this module never reads
or mutates those machine-local files.  A later installer must explicitly merge
these rows and configure ``SR_LIB`` on each machine.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

from stockroom.eda.passive_projection import (
    ArtifactDigest,
    DualEdaProjectionResult,
)
from stockroom.kicad.lib_table import LibTable
from stockroom.sexp.document import SexpDocument

PortableTableKind = Literal["symbol", "footprint"]

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STABLE_NICKNAME = re.compile(r"Stockroom_cmp_[a-z2-7]{52}\Z")
_OUTPUT_DIRECTORY = "Stockroom-Portable-KiCad-Tables"
_SYMBOL_TABLE = "Stockroom-Portable-Symbol-Libraries.kicad-table"
_FOOTPRINT_TABLE = "Stockroom-Portable-Footprint-Libraries.kicad-table"


class KiCadLinkProjectionError(ValueError):
    """Portable table projection input or readback is invalid."""


class KiCadLinkConflict(KiCadLinkProjectionError):
    """Two projections claim the same nickname or path incompatibly."""


@dataclass(frozen=True, slots=True)
class PortableLibraryRow:
    kind: PortableTableKind
    nickname: str
    uri: str
    library_reference: str
    library_relative_path: str
    artifact_relative_path: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if _STABLE_NICKNAME.fullmatch(self.nickname) is None:
            raise ValueError("nickname must be stable and component-ID-derived")
        if self.library_reference != f"{self.nickname}:S1M":
            raise ValueError("library reference must be a full KiCad library ID")
        if self.uri != f"${{SR_LIB}}/{self.library_relative_path}":
            raise ValueError("portable URI must use ${SR_LIB} and the library path")
        for value, name in (
            (self.library_relative_path, "library path"),
            (self.artifact_relative_path, "artifact path"),
        ):
            _portable_path(value, name)
        if _SHA256.fullmatch(self.artifact_digest) is None:
            raise ValueError("artifact digest must be a lowercase sha256 digest")
        if (
            self.artifact_digest.removeprefix("sha256:")
            not in PurePosixPath(self.artifact_relative_path).parts
        ):
            raise ValueError("artifact path must contain its content digest")


@dataclass(frozen=True, slots=True)
class PortableTableArtifact:
    kind: PortableTableKind
    relative_path: str
    digest: str
    size_bytes: int
    row_count: int

    def __post_init__(self) -> None:
        _portable_path(self.relative_path, "table path")
        if _SHA256.fullmatch(self.digest) is None:
            raise ValueError("table digest must be a lowercase sha256 digest")
        if self.size_bytes <= 0:
            raise ValueError("table size must be positive")
        if self.row_count <= 0:
            raise ValueError("table row count must be positive")


@dataclass(frozen=True, slots=True)
class PortableKiCadLinkProjection:
    symbol_table: PortableTableArtifact
    footprint_table: PortableTableArtifact
    symbol_rows: tuple[PortableLibraryRow, ...]
    footprint_rows: tuple[PortableLibraryRow, ...]
    requires_machine_local_install: bool = True

    def __post_init__(self) -> None:
        if self.symbol_table.kind != "symbol":
            raise ValueError("symbol table artifact has the wrong kind")
        if self.footprint_table.kind != "footprint":
            raise ValueError("footprint table artifact has the wrong kind")
        if self.symbol_table.row_count != len(self.symbol_rows):
            raise ValueError("symbol table row count does not match readback")
        if self.footprint_table.row_count != len(self.footprint_rows):
            raise ValueError("footprint table row count does not match readback")
        if not self.requires_machine_local_install:
            raise ValueError("portable fragments cannot claim machine-local installation")


def _portable_path(value: str, name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-blank string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or "\\" in value:
        raise ValueError(f"{name} must be a normalized relative POSIX path")
    return path


def _empty_staging_root(staging_directory: Path) -> Path:
    root = Path(staging_directory)
    if not root.is_dir():
        raise ValueError("staging_directory must be an existing empty directory")
    if any(root.iterdir()):
        raise ValueError("staging_directory must be empty")
    return root


def _artifact(
    result: DualEdaProjectionResult,
    kind: PortableTableKind,
) -> ArtifactDigest:
    return next(artifact for artifact in result.kicad.artifacts if artifact.kind == kind)


def _qualified_reference(reference: str, nickname: str, label: str) -> None:
    if ":" not in reference:
        raise KiCadLinkProjectionError(f"{label} reference must not be bare")
    prefix, entry = reference.split(":", 1)
    if prefix != nickname or entry != "S1M":
        raise KiCadLinkProjectionError(
            f"{label} reference does not match its stable library nickname"
        )


def _row_from_result(
    result: DualEdaProjectionResult,
    kind: PortableTableKind,
) -> PortableLibraryRow:
    if not isinstance(result, DualEdaProjectionResult):
        raise TypeError("results must contain DualEdaProjectionResult values")
    binding = result.kicad.binding
    if binding.symbol_library_nickname is None or binding.footprint_library_nickname is None:
        raise KiCadLinkProjectionError("KiCad projection has no portable nicknames")
    if binding.symbol_library_nickname != binding.footprint_library_nickname:
        raise KiCadLinkProjectionError(
            "KiCad symbol and footprint nicknames must share one component identity"
        )
    nickname = binding.symbol_library_nickname
    if _STABLE_NICKNAME.fullmatch(nickname) is None:
        raise KiCadLinkProjectionError("KiCad nickname is not stable and component-ID-derived")

    if kind == "symbol":
        reference = binding.symbol_ref
        library_path = binding.symbol_library
    else:
        reference = binding.footprint_ref
        library_path = binding.footprint_library
    _qualified_reference(reference, nickname, kind)
    library_relative_path = _portable_path(
        library_path,
        f"{kind} library path",
    ).as_posix()
    artifact = _artifact(result, kind)
    artifact_path = _portable_path(
        artifact.relative_path,
        f"{kind} artifact path",
    )
    if kind == "symbol" and artifact_path.as_posix() != library_relative_path:
        raise KiCadLinkProjectionError(
            "symbol library path does not equal its immutable artifact path"
        )
    if kind == "footprint" and artifact_path.parent != PurePosixPath(library_relative_path):
        raise KiCadLinkProjectionError(
            "footprint library path is not the immutable artifact's .pretty directory"
        )
    if artifact.reference != reference:
        raise KiCadLinkProjectionError(
            f"{kind} artifact reference does not equal its KiCad library ID"
        )
    return PortableLibraryRow(
        kind=kind,
        nickname=nickname,
        uri=f"${{SR_LIB}}/{library_relative_path}",
        library_reference=reference,
        library_relative_path=library_relative_path,
        artifact_relative_path=artifact_path.as_posix(),
        artifact_digest=artifact.digest,
    )


def _merge_rows(
    results: Sequence[DualEdaProjectionResult],
    kind: PortableTableKind,
) -> tuple[PortableLibraryRow, ...]:
    by_nickname: dict[str, PortableLibraryRow] = {}
    nickname_by_path: dict[str, str] = {}
    for result in results:
        row = _row_from_result(result, kind)
        existing = by_nickname.get(row.nickname)
        if existing is not None and existing != row:
            raise KiCadLinkConflict(f"{kind} nickname {row.nickname!r} maps to conflicting paths")
        path_owner = nickname_by_path.get(row.library_relative_path)
        if path_owner is not None and path_owner != row.nickname:
            raise KiCadLinkConflict(
                f"{kind} path {row.library_relative_path!r} is claimed by "
                f"{path_owner!r} and {row.nickname!r}"
            )
        by_nickname[row.nickname] = row
        nickname_by_path[row.library_relative_path] = row.nickname
    return tuple(by_nickname[nickname] for nickname in sorted(by_nickname))


def _render_table(
    path: Path,
    kind: PortableTableKind,
    rows: tuple[PortableLibraryRow, ...],
) -> None:
    table_kind = "sym_lib_table" if kind == "symbol" else "fp_lib_table"
    table = LibTable.new(table_kind)
    for row in rows:
        appended = table.append_kicad_lib(
            row.nickname,
            row.uri,
            f"Stockroom portable {kind} library for {row.library_reference}",
        )
        if not appended:
            raise KiCadLinkConflict(f"duplicate {kind} nickname {row.nickname!r} during rendering")
    table.save(path)


def _node_value(node, field: str) -> str:
    child = node.find(field)
    if child is None or len(child.children) < 2:
        raise KiCadLinkProjectionError(f"portable table row has no {field!r}")
    return child.children[1].value


def _read_rows(
    path: Path,
    kind: PortableTableKind,
) -> tuple[tuple[str, str, str, str, str], ...]:
    expected_kind = "sym_lib_table" if kind == "symbol" else "fp_lib_table"
    table = LibTable.load(path)
    if table.kind != expected_kind:
        raise KiCadLinkProjectionError(f"portable {kind} table has the wrong root")
    document = SexpDocument.load(path)
    rows = tuple(
        (
            _node_value(node, "name"),
            _node_value(node, "type"),
            _node_value(node, "uri"),
            _node_value(node, "options"),
            _node_value(node, "descr"),
        )
        for node in document.root.find_all("lib")
    )
    if table.entries() != [row[0] for row in rows]:
        raise KiCadLinkProjectionError(f"portable {kind} table parser readback disagrees")
    return rows


def _verify_table(
    path: Path,
    kind: PortableTableKind,
    rows: tuple[PortableLibraryRow, ...],
) -> None:
    expected = tuple(
        (
            row.nickname,
            "KiCad",
            row.uri,
            "",
            f"Stockroom portable {kind} library for {row.library_reference}",
        )
        for row in rows
    )
    observed = _read_rows(path, kind)
    if observed != expected:
        raise KiCadLinkProjectionError(
            f"portable {kind} table readback differs: observed={observed!r}, expected={expected!r}"
        )


def _table_artifact(
    path: Path,
    root: Path,
    kind: PortableTableKind,
    row_count: int,
) -> PortableTableArtifact:
    data = path.read_bytes()
    return PortableTableArtifact(
        kind=kind,
        relative_path=path.relative_to(root).as_posix(),
        digest=f"sha256:{hashlib.sha256(data).hexdigest()}",
        size_bytes=len(data),
        row_count=row_count,
    )


def project_portable_kicad_links(
    results: Sequence[DualEdaProjectionResult],
    staging_directory: Path,
) -> PortableKiCadLinkProjection:
    """Render verified Stockroom-owned KiCad table fragments atomically.

    The caller must provide an existing empty staging directory.  Exact
    duplicate results are deduplicated.  Conflicting nicknames or library paths
    fail before any output becomes visible.
    """

    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise TypeError("results must be a sequence of DualEdaProjectionResult values")
    if not results:
        raise ValueError("at least one dual-EDA projection result is required")
    for result in results:
        if not isinstance(result, DualEdaProjectionResult):
            raise TypeError("results must contain DualEdaProjectionResult values")
    root = _empty_staging_root(staging_directory)
    symbol_rows = _merge_rows(results, "symbol")
    footprint_rows = _merge_rows(results, "footprint")

    with tempfile.TemporaryDirectory(prefix=".kicad-links-", dir=root) as temporary:
        temporary_root = Path(temporary)
        payload = temporary_root / _OUTPUT_DIRECTORY
        payload.mkdir()
        symbol_path = payload / _SYMBOL_TABLE
        footprint_path = payload / _FOOTPRINT_TABLE
        _render_table(symbol_path, "symbol", symbol_rows)
        _render_table(footprint_path, "footprint", footprint_rows)
        _verify_table(symbol_path, "symbol", symbol_rows)
        _verify_table(footprint_path, "footprint", footprint_rows)
        result = PortableKiCadLinkProjection(
            symbol_table=_table_artifact(
                symbol_path,
                temporary_root,
                "symbol",
                len(symbol_rows),
            ),
            footprint_table=_table_artifact(
                footprint_path,
                temporary_root,
                "footprint",
                len(footprint_rows),
            ),
            symbol_rows=symbol_rows,
            footprint_rows=footprint_rows,
        )
        payload.replace(root / _OUTPUT_DIRECTORY)
        return result
