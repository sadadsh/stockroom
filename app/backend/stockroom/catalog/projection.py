"""Deterministic staging projection for the vNext component catalog.

The KiCad database-library shape follows KiCad's official current QA fixture
and parser:

* https://gitlab.com/kicad/code/kicad/-/raw/master/qa/data/dblib/qa_dblib.kicad_dbl
* https://gitlab.com/kicad/code/kicad/-/raw/master/common/database/database_lib_settings.cpp

This module only stages derived files in a caller-owned directory. It does not
install either link configuration or write canonical library/Git content.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from stockroom.altium.dblib import FIELD_MAP, render_dblib
from stockroom.altium.odbc import SQLITE3_ODBC_DRIVER
from stockroom.domain import (
    CanonicalPassiveBundle,
    canonical_model_digest,
)
from stockroom.workflow.identifiers import (
    authoritative_text,
    digest_id,
    digest_text,
    parse_sha256,
)
from stockroom.workflow.model import canonical_json

CATALOG_SCHEMA_VERSION = 1
CATALOG_APPLICATION_ID = 0x53544B52
CATALOG_FILENAME = "Catalog.sqlite"
KICAD_DBL_FILENAME = "Stockroom.kicad_dbl"
ALTIUM_DBLIB_FILENAME = "Stockroom.DbLib"
CATALOG_DIGEST_FILENAME = "Catalog Digest.json"
CATALOG_TABLE = "Parts"

NonBlankText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
ToolKey = Literal["kicad", "altium"]
ArtifactKind = Literal["symbol", "footprint"]

_BASE_PART_COLUMNS = (
    "Component ID",
    "Manufacturer ID",
    "Manufacturer",
    "MPN",
    "Value",
    "Package",
    "Description",
    "KiCad Symbol Ref",
    "KiCad Footprint Ref",
    "Canonical Bundle Digest",
    "Definition Digest",
    "Artifact Set Digest",
    "Verification Digest",
    "KiCad Symbol Template ID",
    "KiCad Symbol Artifact Digest",
    "KiCad Symbol Artifact Path",
    "KiCad Footprint Template ID",
    "KiCad Footprint Artifact Digest",
    "KiCad Footprint Artifact Path",
    "Altium Symbol Template ID",
    "Altium Symbol Artifact Digest",
    "Altium Symbol Artifact Path",
    "Altium Footprint Template ID",
    "Altium Footprint Artifact Digest",
    "Altium Footprint Artifact Path",
)
_ALTIUM_COLUMNS = tuple(column for column, _parameter, _visible in FIELD_MAP)
PART_COLUMNS = _BASE_PART_COLUMNS + tuple(
    column for column in _ALTIUM_COLUMNS if column not in _BASE_PART_COLUMNS
)
_ARTIFACT_ORDER = (
    ("kicad", "symbol"),
    ("kicad", "footprint"),
    ("altium", "symbol"),
    ("altium", "footprint"),
)
_KICAD_FIELDS = (
    ("Manufacturer", "Manufacturer", False, True, True),
    ("MPN", "MPN", False, True, True),
    ("Value", "Value", True, True, False),
    ("Package", "Package", False, True, True),
    ("Component ID", "Stockroom ID", False, False, True),
    ("Canonical Bundle Digest", "Canonical Bundle Digest", False, False, True),
    ("Definition Digest", "Definition Digest", False, False, True),
    ("Artifact Set Digest", "Artifact Set Digest", False, False, True),
    ("Verification Digest", "Verification Digest", False, False, True),
)


class CatalogProjectionError(ValueError):
    """The staged projection failed structural or readback validation."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProjectedArtifact(_StrictModel):
    """One exact tool artifact that a shared canonical template resolves to."""

    schema_version: Literal[1] = 1
    tool: ToolKey
    kind: ArtifactKind
    template_id: NonBlankText
    reference: NonBlankText
    path: NonBlankText
    digest: Sha256Digest

    @field_validator("template_id", "reference")
    @classmethod
    def validate_exact_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("artifact text must not contain NUL")
        return authoritative_text(value, "artifact text")

    @field_validator("path")
    @classmethod
    def validate_portable_path(cls, value: str) -> str:
        exact = authoritative_text(value, "artifact path")
        if (
            "\x00" in exact
            or "\\" in exact
            or ":" in exact
            or exact.startswith("/")
            or (len(exact) >= 2 and exact[0].isalpha() and exact[1] == ":")
        ):
            raise ValueError("artifact path must be a portable library-relative POSIX path")
        segments = exact.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError("artifact path must not contain empty, dot, or parent segments")
        return exact

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        parse_sha256(value, "artifact digest")
        return value

    @model_validator(mode="after")
    def validate_tool_reference(self) -> Self:
        if self.tool == "kicad":
            library, separator, entry = self.reference.partition(":")
            if not separator or not library or not entry or ":" in entry:
                raise ValueError("KiCad artifact reference must be a full library:entry ID")
        return self


class CatalogArtifacts(_StrictModel):
    """The exact four artifact links required by the dual-EDA projection."""

    schema_version: Literal[1] = 1
    links: tuple[
        ProjectedArtifact,
        ProjectedArtifact,
        ProjectedArtifact,
        ProjectedArtifact,
    ]

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        actual = tuple((link.tool, link.kind) for link in self.links)
        if actual != _ARTIFACT_ORDER:
            raise ValueError(
                "catalog artifacts must be ordered as KiCad symbol/footprint, "
                "then Altium symbol/footprint"
            )
        return self

    def get(self, tool: ToolKey, kind: ArtifactKind) -> ProjectedArtifact:
        return next(link for link in self.links if link.tool == tool and link.kind == kind)


@dataclass(frozen=True, slots=True)
class CatalogOutput:
    path: Path
    role: "CatalogArtifactRole"

    @property
    def commit_eligible(self) -> bool:
        return self.role is CatalogArtifactRole.TRACKED_PORTABLE


class CatalogArtifactRole(StrEnum):
    TRACKED_PORTABLE = "tracked_portable"
    ACTIVATION_ONLY = "activation_only"
    MACHINE_LOCAL = "machine_local"


@dataclass(frozen=True, slots=True)
class CatalogProjection:
    staging_directory: Path
    catalog_path: Path
    altium_catalog_path: Path
    kicad_dbl_path: Path
    altium_dblib_path: Path
    catalog_digest_path: Path
    catalog_sqlite_digest: str
    kicad_dbl_digest: str
    altium_dblib_digest: str
    catalog_digest_document_digest: str
    semantic_digest: str
    revision: str
    semantic_row_digest: str
    outputs: tuple[CatalogOutput, CatalogOutput, CatalogOutput, CatalogOutput]
    row_count: int
    fixture_mode: bool

    @property
    def tracked_portable_outputs(self) -> tuple[Path, ...]:
        return tuple(output.path for output in self.outputs if output.commit_eligible)


def _file_digest(path: Path) -> str:
    return digest_text(hashlib.sha256(path.read_bytes()).digest())


def _claim_values(bundle: CanonicalPassiveBundle) -> tuple[str, str]:
    claims = {claim.key: claim.value for claim in bundle.claims}
    return claims["value"], claims["package"]


def _validate_template_links(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
) -> None:
    templates = {
        template.kind: template.template_id for template in bundle.artifacts.shared_templates
    }
    for link in artifacts.links:
        expected_template = templates[link.kind]
        if link.template_id != expected_template:
            raise CatalogProjectionError(
                f"{link.tool} {link.kind} resolves template "
                f"{link.template_id!r}, expected {expected_template!r}"
            )


def _catalog_row(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
) -> dict[str, str]:
    value, package = _claim_values(bundle)
    kicad_symbol = artifacts.get("kicad", "symbol")
    kicad_footprint = artifacts.get("kicad", "footprint")
    altium_symbol = artifacts.get("altium", "symbol")
    altium_footprint = artifacts.get("altium", "footprint")
    description = f"{bundle.identity.mpn_canonical} — {value}"
    row = {column: "" for column in PART_COLUMNS}
    row.update(
        {
            "Component ID": bundle.identity.component_id,
            "Manufacturer ID": bundle.manufacturer.manufacturer_id,
            "Manufacturer": bundle.manufacturer.authoritative_key,
            "MPN": bundle.identity.mpn_canonical,
            "Value": value,
            "Package": package,
            "Description": description,
            "KiCad Symbol Ref": kicad_symbol.reference,
            "KiCad Footprint Ref": kicad_footprint.reference,
            "Canonical Bundle Digest": bundle.canonical_digest(),
            "Definition Digest": canonical_model_digest(bundle.definition),
            "Artifact Set Digest": canonical_model_digest(bundle.artifacts),
            "Verification Digest": canonical_model_digest(bundle.verification),
            "KiCad Symbol Template ID": kicad_symbol.template_id,
            "KiCad Symbol Artifact Digest": kicad_symbol.digest,
            "KiCad Symbol Artifact Path": kicad_symbol.path,
            "KiCad Footprint Template ID": kicad_footprint.template_id,
            "KiCad Footprint Artifact Digest": kicad_footprint.digest,
            "KiCad Footprint Artifact Path": kicad_footprint.path,
            "Altium Symbol Template ID": altium_symbol.template_id,
            "Altium Symbol Artifact Digest": altium_symbol.digest,
            "Altium Symbol Artifact Path": altium_symbol.path,
            "Altium Footprint Template ID": altium_footprint.template_id,
            "Altium Footprint Artifact Digest": altium_footprint.digest,
            "Altium Footprint Artifact Path": altium_footprint.path,
            "Library Ref": altium_symbol.reference,
            "Library Path": altium_symbol.path,
            "Footprint Ref": altium_footprint.reference,
            "Footprint Path": altium_footprint.path,
            "Comment": value,
            "Category": bundle.definition.functional_kind.capitalize(),
            "Stockroom ID": bundle.identity.component_id,
        }
    )
    return row


def _base_catalog_metadata(
    bundle: CanonicalPassiveBundle,
    fixture_mode: bool,
) -> tuple[tuple[str, str], ...]:
    return (
        ("artifact_role", CatalogArtifactRole.ACTIVATION_ONLY.value),
        ("canonical_bundle_digest", bundle.canonical_digest()),
        ("component_count", "1"),
        ("fixture_mode", "true" if fixture_mode else "false"),
        ("projection", "stockroom.catalog"),
        ("schema_version", str(CATALOG_SCHEMA_VERSION)),
    )


def _logical_altium_link() -> dict[str, object]:
    return {
        "database_filename": CATALOG_FILENAME,
        "field_map": [
            {
                "column": column,
                "parameter": parameter,
                "visible_on_add": visible,
            }
            for column, parameter, visible in FIELD_MAP
        ],
        "format_version": "1.1",
        "key_column": "MPN",
        "table": CATALOG_TABLE,
    }


def _semantic_rows(
    bundle: CanonicalPassiveBundle, artifacts: CatalogArtifacts
) -> list[dict[str, str]]:
    return sorted(
        [_catalog_row(bundle, artifacts)],
        key=lambda row: row["Component ID"],
    )


def _semantic_identity(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> tuple[str, str, str]:
    rows = _semantic_rows(bundle, artifacts)
    row_digest = digest_text(hashlib.sha256(canonical_json(rows).encode("utf-8")).digest())
    document = {
        "links": {
            "altium": _logical_altium_link(),
            "kicad": json.loads(render_kicad_dbl()),
        },
        "metadata": dict(_base_catalog_metadata(bundle, fixture_mode)),
        "parts": rows,
        "schema": {
            "application_id": CATALOG_APPLICATION_ID,
            "columns": list(PART_COLUMNS),
            "schema_version": CATALOG_SCHEMA_VERSION,
            "table": CATALOG_TABLE,
        },
    }
    digest = hashlib.sha256(canonical_json(document).encode("utf-8")).digest()
    return digest_text(digest), digest_id("catrev", digest), row_digest


def _catalog_metadata(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> tuple[tuple[str, str], ...]:
    semantic_digest, revision, row_digest = _semantic_identity(
        bundle,
        artifacts,
        fixture_mode,
    )
    return tuple(
        sorted(
            (
                *_base_catalog_metadata(bundle, fixture_mode),
                ("catalog_revision", revision),
                ("catalog_semantic_digest", semantic_digest),
                ("semantic_row_digest", row_digest),
                ("source_canonical_digest", bundle.canonical_digest()),
            )
        )
    )


def _catalog_digest_document(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> dict[str, object]:
    semantic_digest, revision, row_digest = _semantic_identity(
        bundle,
        artifacts,
        fixture_mode,
    )
    return {
        "catalog_revision": revision,
        "catalog_semantic_digest": semantic_digest,
        "outputs": [
            {
                "filename": CATALOG_DIGEST_FILENAME,
                "portability": "portable",
                "role": CatalogArtifactRole.TRACKED_PORTABLE.value,
            },
            {
                "filename": KICAD_DBL_FILENAME,
                "portability": "portable-${CWD}-catalog-link",
                "role": CatalogArtifactRole.TRACKED_PORTABLE.value,
            },
            {
                "filename": CATALOG_FILENAME,
                "portability": "local-scratch-projection",
                "role": CatalogArtifactRole.ACTIVATION_ONLY.value,
            },
            {
                "filename": ALTIUM_DBLIB_FILENAME,
                "portability": "machine-local-absolute-catalog-path",
                "role": CatalogArtifactRole.MACHINE_LOCAL.value,
            },
        ],
        "schema_version": CATALOG_SCHEMA_VERSION,
        "semantic_row_digest": row_digest,
        "source_canonical_digest": bundle.canonical_digest(),
    }


def _render_catalog_digest(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> bytes:
    return (
        canonical_json(_catalog_digest_document(bundle, artifacts, fixture_mode)).encode("utf-8")
        + b"\n"
    )


def _write_catalog(
    path: Path,
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> None:
    row = _catalog_row(bundle, artifacts)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA page_size = 4096")
        connection.execute(f"PRAGMA application_id = {CATALOG_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION}")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE catalog_metadata (
                key TEXT PRIMARY KEY COLLATE BINARY,
                value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        connection.executemany(
            "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
            _catalog_metadata(bundle, artifacts, fixture_mode),
        )
        definitions = ", ".join(
            f'"{column}" TEXT NOT NULL'
            + (" PRIMARY KEY COLLATE BINARY" if column == "Component ID" else "")
            for column in PART_COLUMNS
        )
        connection.execute(f'CREATE TABLE "{CATALOG_TABLE}" ({definitions}) WITHOUT ROWID')
        connection.execute(
            f"""
            CREATE UNIQUE INDEX parts_exact_manufacturer_mpn
            ON "{CATALOG_TABLE}"("Manufacturer" COLLATE BINARY, "MPN" COLLATE BINARY)
            """
        )
        quoted_columns = ", ".join(f'"{column}"' for column in PART_COLUMNS)
        placeholders = ", ".join("?" for _ in PART_COLUMNS)
        connection.execute(
            f'INSERT INTO "{CATALOG_TABLE}" ({quoted_columns}) VALUES ({placeholders})',
            tuple(row[column] for column in PART_COLUMNS),
        )
        connection.execute("COMMIT")
        connection.execute("VACUUM")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def render_kicad_dbl() -> bytes:
    """Render KiCad schema v1 using its official database-library field names."""

    fields = [
        {
            "column": column,
            "name": name,
            "show_name": show_name,
            "visible_in_chooser": visible_in_chooser,
            "visible_on_add": visible_on_add,
        }
        for (
            column,
            name,
            visible_on_add,
            visible_in_chooser,
            show_name,
        ) in _KICAD_FIELDS
    ]
    document = {
        "cache": {"max_age": 10, "max_size": 256},
        "description": "Stockroom staged canonical component catalog",
        "globally_unique_keys": True,
        "libraries": [
            {
                "fields": fields,
                "footprints": "KiCad Footprint Ref",
                "key": "Component ID",
                "name": "Components",
                "properties": {"description": "Description"},
                "symbols": "KiCad Symbol Ref",
                "table": CATALOG_TABLE,
            }
        ],
        "meta": {
            "filename": KICAD_DBL_FILENAME,
            "version": CATALOG_SCHEMA_VERSION,
        },
        "name": "Stockroom",
        "source": {
            "connection_string": (
                f"Driver={{{SQLITE3_ODBC_DRIVER}}};Database=${{CWD}}/{CATALOG_FILENAME}"
            ),
            "dsn": "",
            "password": "",
            "timeout_seconds": 2,
            "type": "odbc",
            "username": "",
        },
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def lookup_catalog_component(
    catalog_path: str | Path,
    *,
    manufacturer: str,
    mpn: str,
) -> dict[str, str] | None:
    """Look up one component using exact case/punctuation-sensitive identity."""

    exact_manufacturer = authoritative_text(manufacturer, "manufacturer")
    exact_mpn = authoritative_text(mpn, "mpn")
    connection = sqlite3.connect(Path(catalog_path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            f"""
            SELECT * FROM "{CATALOG_TABLE}"
            WHERE "Manufacturer" = ? COLLATE BINARY
              AND "MPN" = ? COLLATE BINARY
            """,
            (exact_manufacturer, exact_mpn),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return None
    if len(rows) != 1:
        raise CatalogProjectionError("exact catalog identity is not unique")
    return {str(key): str(rows[0][key]) for key in rows[0].keys()}


def _validate_catalog(
    catalog_path: Path,
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> None:
    connection = sqlite3.connect(catalog_path)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise CatalogProjectionError("Catalog.sqlite failed integrity_check")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise CatalogProjectionError("Catalog.sqlite failed foreign_key_check")
        if connection.execute("PRAGMA user_version").fetchone()[0] != CATALOG_SCHEMA_VERSION:
            raise CatalogProjectionError("Catalog.sqlite schema version is invalid")
        if connection.execute("PRAGMA application_id").fetchone()[0] != CATALOG_APPLICATION_ID:
            raise CatalogProjectionError("Catalog.sqlite application ID is invalid")
        metadata = tuple(
            (str(row["key"]), str(row["value"]))
            for row in connection.execute("SELECT key, value FROM catalog_metadata ORDER BY key")
        )
        if metadata != _catalog_metadata(bundle, artifacts, fixture_mode):
            raise CatalogProjectionError("Catalog.sqlite metadata readback differs")
        columns = tuple(
            str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{CATALOG_TABLE}")')
        )
        if columns != PART_COLUMNS:
            raise CatalogProjectionError("Catalog.sqlite Parts columns differ")
        rows = connection.execute(f'SELECT * FROM "{CATALOG_TABLE}"').fetchall()
        if len(rows) != 1:
            raise CatalogProjectionError("Catalog.sqlite must contain exactly one row")
        actual = {column: str(rows[0][column]) for column in PART_COLUMNS}
        if actual != _catalog_row(bundle, artifacts):
            raise CatalogProjectionError("Catalog.sqlite row readback differs")
    except sqlite3.DatabaseError as exc:
        raise CatalogProjectionError("Catalog.sqlite could not be read back") from exc
    finally:
        connection.close()


def _validate_kicad_dbl(path: Path) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogProjectionError("KiCad database link is invalid JSON") from exc
    if document != json.loads(render_kicad_dbl()):
        raise CatalogProjectionError("KiCad database link readback differs")
    source = document["source"]
    if source["username"] or source["password"] or source["dsn"]:
        raise CatalogProjectionError("KiCad database link contains credentials")
    library = document["libraries"][0]
    database_columns = set(PART_COLUMNS)
    required_columns = {
        library["key"],
        library["symbols"],
        library["footprints"],
        library["properties"]["description"],
        *(field["column"] for field in library["fields"]),
    }
    if not required_columns <= database_columns:
        raise CatalogProjectionError("KiCad database link names a missing Catalog.sqlite column")


def _validate_altium_dblib(path: Path, catalog_path: Path) -> None:
    raw = path.read_bytes()
    if b"\r\n" not in raw or raw.replace(b"\r\n", b"").find(b"\n") >= 0:
        raise CatalogProjectionError("Altium DbLib must use deterministic CRLF")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogProjectionError("Altium DbLib is not UTF-8") from exc
    expected = render_dblib(
        CATALOG_TABLE,
        CATALOG_FILENAME,
        db_path=str(catalog_path.resolve()),
    ).encode("utf-8")
    if raw != expected:
        raise CatalogProjectionError("Altium DbLib readback differs")
    required = {
        "[OutputDatabaseLinkFile]",
        "Version=1.1",
        f"TableName={CATALOG_TABLE}",
        f"LibraryDatabasePath=.\\{CATALOG_FILENAME}",
        "DatabasePathRelative=1",
        f"Database={catalog_path.resolve()};",
        "ParameterName=[Library Ref]",
        "ParameterName=[Footprint Ref]",
        "ParameterName=Manufacturer",
        "ParameterName=MPN",
    }
    missing = {value for value in required if value not in text}
    if missing:
        raise CatalogProjectionError(f"Altium DbLib readback is missing {sorted(missing)!r}")
    mapped_columns = {
        column for column, _parameter, _visible in FIELD_MAP if f"FieldNameOnly={column}|" in text
    }
    if mapped_columns != set(_ALTIUM_COLUMNS):
        raise CatalogProjectionError("Altium DbLib field map readback differs")


def _validate_catalog_digest(
    path: Path,
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    fixture_mode: bool,
) -> None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogProjectionError("Catalog Digest.json is invalid JSON") from exc
    expected = _catalog_digest_document(bundle, artifacts, fixture_mode)
    if document != expected:
        raise CatalogProjectionError("Catalog Digest.json readback differs")


def validate_catalog_projection(
    staging_directory: str | Path,
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    *,
    fixture_mode: bool,
    altium_catalog_path: str | Path | None = None,
) -> CatalogProjection:
    """Read back and validate all four staged outputs."""

    if type(fixture_mode) is not bool:
        raise TypeError("fixture_mode must be an explicit boolean")
    staging = Path(staging_directory).resolve()
    catalog_path = staging / CATALOG_FILENAME
    if altium_catalog_path is None:
        altium_data_source = catalog_path
    else:
        raw_altium_data_source = Path(altium_catalog_path)
        if not raw_altium_data_source.is_absolute():
            raise CatalogProjectionError("Altium catalog data source must be an absolute path")
        altium_data_source = raw_altium_data_source.resolve()
    kicad_path = staging / KICAD_DBL_FILENAME
    altium_path = staging / ALTIUM_DBLIB_FILENAME
    digest_path = staging / CATALOG_DIGEST_FILENAME
    for path in (catalog_path, kicad_path, altium_path, digest_path):
        if not path.is_file() or path.parent != staging:
            raise CatalogProjectionError(
                "projection output is missing from the supplied staging directory"
            )
    _validate_template_links(bundle, artifacts)
    _validate_catalog(catalog_path, bundle, artifacts, fixture_mode)
    _validate_kicad_dbl(kicad_path)
    _validate_altium_dblib(altium_path, altium_data_source)
    _validate_catalog_digest(digest_path, bundle, artifacts, fixture_mode)
    semantic_digest, revision, row_digest = _semantic_identity(
        bundle,
        artifacts,
        fixture_mode,
    )
    outputs = (
        CatalogOutput(
            path=digest_path,
            role=CatalogArtifactRole.TRACKED_PORTABLE,
        ),
        CatalogOutput(
            path=kicad_path,
            role=CatalogArtifactRole.TRACKED_PORTABLE,
        ),
        CatalogOutput(
            path=catalog_path,
            role=CatalogArtifactRole.ACTIVATION_ONLY,
        ),
        CatalogOutput(
            path=altium_path,
            role=CatalogArtifactRole.MACHINE_LOCAL,
        ),
    )
    return CatalogProjection(
        staging_directory=staging,
        catalog_path=catalog_path,
        altium_catalog_path=altium_data_source,
        kicad_dbl_path=kicad_path,
        altium_dblib_path=altium_path,
        catalog_digest_path=digest_path,
        catalog_sqlite_digest=_file_digest(catalog_path),
        kicad_dbl_digest=_file_digest(kicad_path),
        altium_dblib_digest=_file_digest(altium_path),
        catalog_digest_document_digest=_file_digest(digest_path),
        semantic_digest=semantic_digest,
        revision=revision,
        semantic_row_digest=row_digest,
        outputs=outputs,
        row_count=1,
        fixture_mode=fixture_mode,
    )


def _replace_projection(
    sources: tuple[Path, ...],
    destinations: tuple[Path, ...],
    backup_directory: Path,
) -> None:
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    try:
        for destination in destinations:
            if destination.exists():
                backup = backup_directory / f"{destination.name}.backup"
                os.replace(destination, backup)
                backups[destination] = backup
        for source, destination in zip(sources, destinations, strict=True):
            os.replace(source, destination)
            installed.append(destination)
    except BaseException:
        for destination in installed:
            destination.unlink(missing_ok=True)
        for destination, backup in backups.items():
            os.replace(backup, destination)
        raise


def stage_catalog_projection(
    bundle: CanonicalPassiveBundle,
    artifacts: CatalogArtifacts,
    staging_directory: str | Path,
    *,
    fixture_mode: bool,
    altium_catalog_path: str | Path | None = None,
) -> CatalogProjection:
    """Transactionally build, validate, and atomically replace staged outputs."""

    if type(fixture_mode) is not bool:
        raise TypeError("fixture_mode must be an explicit boolean")
    _validate_template_links(bundle, artifacts)
    staging = Path(staging_directory).resolve()
    staging.mkdir(parents=True, exist_ok=True)
    destinations = (
        staging / CATALOG_FILENAME,
        staging / KICAD_DBL_FILENAME,
        staging / ALTIUM_DBLIB_FILENAME,
        staging / CATALOG_DIGEST_FILENAME,
    )
    if altium_catalog_path is None:
        altium_data_source = destinations[0]
    else:
        raw_altium_data_source = Path(altium_catalog_path)
        if not raw_altium_data_source.is_absolute():
            raise CatalogProjectionError("Altium catalog data source must be an absolute path")
        altium_data_source = raw_altium_data_source.resolve()
    with tempfile.TemporaryDirectory(
        dir=staging,
        prefix=".catalog-projection-",
    ) as temporary:
        temporary_path = Path(temporary)
        sources = (
            temporary_path / CATALOG_FILENAME,
            temporary_path / KICAD_DBL_FILENAME,
            temporary_path / ALTIUM_DBLIB_FILENAME,
            temporary_path / CATALOG_DIGEST_FILENAME,
        )
        _write_catalog(sources[0], bundle, artifacts, fixture_mode)
        sources[1].write_bytes(render_kicad_dbl())
        sources[2].write_bytes(
            render_dblib(
                CATALOG_TABLE,
                CATALOG_FILENAME,
                db_path=str(altium_data_source),
            ).encode("utf-8")
        )
        sources[3].write_bytes(_render_catalog_digest(bundle, artifacts, fixture_mode))
        _validate_catalog(sources[0], bundle, artifacts, fixture_mode)
        _validate_kicad_dbl(sources[1])
        _validate_altium_dblib(sources[2], altium_data_source)
        _validate_catalog_digest(
            sources[3],
            bundle,
            artifacts,
            fixture_mode,
        )
        _replace_projection(sources, destinations, temporary_path)
    return validate_catalog_projection(
        staging,
        bundle,
        artifacts,
        fixture_mode=fixture_mode,
        altium_catalog_path=altium_data_source,
    )
