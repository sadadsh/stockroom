import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from stockroom.catalog import (
    ALTIUM_DBLIB_FILENAME,
    CATALOG_APPLICATION_ID,
    CATALOG_DIGEST_FILENAME,
    CATALOG_FILENAME,
    CATALOG_SCHEMA_VERSION,
    KICAD_DBL_FILENAME,
    PART_COLUMNS,
    CatalogArtifactRole,
    CatalogArtifacts,
    CatalogProjectionError,
    ProjectedArtifact,
    lookup_catalog_component,
    stage_catalog_projection,
    validate_catalog_projection,
)
from stockroom.catalog import projection as projection_module
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)
from stockroom.workflow.model import canonical_json


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _digest_from_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _evidence(label: str) -> AuthoritativeEvidence:
    return AuthoritativeEvidence(
        source_kind="manufacturer_datasheet",
        source_locator=f"https://onsemi.example/{label}.pdf",
        content_digest=_digest(f"evidence:{label}"),
    )


def _bundle() -> CanonicalPassiveBundle:
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key="ON Semiconductor",
        mpn_canonical="S1M",
        functional_kind="diode",
        value="1 kV, 1 A rectifier diode",
        package="SMA (DO-214AC)",
        value_evidence=_evidence("value"),
        package_evidence=_evidence("package"),
    )


def _artifacts(bundle: CanonicalPassiveBundle | None = None) -> CatalogArtifacts:
    canonical = _bundle() if bundle is None else bundle
    templates = {
        template.kind: template.template_id for template in canonical.artifacts.shared_templates
    }
    return CatalogArtifacts(
        links=(
            ProjectedArtifact(
                tool="kicad",
                kind="symbol",
                template_id=templates["symbol"],
                reference="Device:D",
                path="templates/Device.kicad_sym",
                digest=_digest("kicad-symbol"),
            ),
            ProjectedArtifact(
                tool="kicad",
                kind="footprint",
                template_id=templates["footprint"],
                reference="Diode_SMD:D_SMA",
                path="templates/Diode_SMD.pretty/D_SMA.kicad_mod",
                digest=_digest("kicad-footprint"),
            ),
            ProjectedArtifact(
                tool="altium",
                kind="symbol",
                template_id=templates["symbol"],
                reference="S1M",
                path="fixtures/sample.SchLib",
                digest=_digest("altium-symbol"),
            ),
            ProjectedArtifact(
                tool="altium",
                kind="footprint",
                template_id=templates["footprint"],
                reference="DIOM5227X270N",
                path="fixtures/sample.PcbLib",
                digest=_digest("altium-footprint"),
            ),
        )
    )


def _output_bytes(staging: Path) -> dict[str, bytes]:
    return {
        filename: (staging / filename).read_bytes()
        for filename in (
            CATALOG_FILENAME,
            KICAD_DBL_FILENAME,
            ALTIUM_DBLIB_FILENAME,
            CATALOG_DIGEST_FILENAME,
        )
    }


def test_stages_only_declared_outputs_inside_caller_directory(tmp_path):
    staging = tmp_path / "caller-staging"
    bundle = _bundle()
    result = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        staging,
        fixture_mode=True,
    )

    assert result.staging_directory == staging.resolve()
    assert result.fixture_mode is True
    assert result.row_count == 1
    assert {path.name for path in staging.iterdir()} == {
        CATALOG_FILENAME,
        KICAD_DBL_FILENAME,
        ALTIUM_DBLIB_FILENAME,
        CATALOG_DIGEST_FILENAME,
    }
    assert all(
        path.parent == staging.resolve()
        for path in (
            result.catalog_path,
            result.kicad_dbl_path,
            result.altium_dblib_path,
            result.catalog_digest_path,
        )
    )
    assert {path.name for path in tmp_path.iterdir()} == {"caller-staging"}


def test_catalog_schema_metadata_and_artifact_readback_are_exact(tmp_path):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    result = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )

    with sqlite3.connect(result.catalog_path) as connection:
        connection.row_factory = sqlite3.Row
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA application_id").fetchone()[0] == CATALOG_APPLICATION_ID
        metadata = dict(connection.execute("SELECT key, value FROM catalog_metadata ORDER BY key"))
        assert metadata["schema_version"] == str(CATALOG_SCHEMA_VERSION)
        assert metadata["fixture_mode"] == "true"
        assert metadata["artifact_role"] == "activation_only"
        assert metadata["catalog_revision"] == result.revision
        assert metadata["catalog_semantic_digest"] == result.semantic_digest
        assert metadata["semantic_row_digest"] == result.semantic_row_digest
        columns = tuple(row["name"] for row in connection.execute('PRAGMA table_info("Parts")'))
        assert columns == PART_COLUMNS
        row = connection.execute('SELECT * FROM "Parts"').fetchone()

    assert row["Manufacturer"] == "ON Semiconductor"
    assert row["MPN"] == "S1M"
    assert row["KiCad Symbol Artifact Digest"] == _digest("kicad-symbol")
    assert row["KiCad Footprint Artifact Path"] == "templates/Diode_SMD.pretty/D_SMA.kicad_mod"
    assert row["Altium Symbol Artifact Path"] == "fixtures/sample.SchLib"
    assert row["Footprint Ref"] == "DIOM5227X270N"
    assert not list(staging.glob("*-journal"))
    assert not list(staging.glob("*-wal"))


def test_lookup_requires_exact_manufacturer_and_mpn_bytes(tmp_path):
    bundle = _bundle()
    result = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        tmp_path / "stage",
        fixture_mode=True,
    )

    exact = lookup_catalog_component(
        result.catalog_path,
        manufacturer="ON Semiconductor",
        mpn="S1M",
    )
    assert exact is not None
    assert exact["Component ID"] == bundle.identity.component_id
    assert (
        lookup_catalog_component(
            result.catalog_path,
            manufacturer="ON semiconductor",
            mpn="S1M",
        )
        is None
    )
    assert (
        lookup_catalog_component(
            result.catalog_path,
            manufacturer="ON Semiconductor",
            mpn="s1m",
        )
        is None
    )
    assert (
        lookup_catalog_component(
            result.catalog_path,
            manufacturer="Other Manufacturer",
            mpn="S1M",
        )
        is None
    )


def test_catalog_rejects_bare_kicad_entry_references():
    bundle = _bundle()
    document = _artifacts(bundle).model_dump(mode="json")
    document["links"][0]["reference"] = "S1M"

    with pytest.raises(ValidationError, match="full library:entry ID"):
        CatalogArtifacts.model_validate_json(json.dumps(document))


def test_kicad_link_matches_official_database_library_structure(tmp_path):
    bundle = _bundle()
    result = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        tmp_path / "stage",
        fixture_mode=True,
    )
    document = json.loads(result.kicad_dbl_path.read_text(encoding="utf-8"))

    assert document["meta"] == {
        "filename": KICAD_DBL_FILENAME,
        "version": 1,
    }
    assert document["source"] == {
        "connection_string": ("Driver={SQLite3 ODBC Driver};Database=${CWD}/Catalog.sqlite"),
        "dsn": "",
        "password": "",
        "timeout_seconds": 2,
        "type": "odbc",
        "username": "",
    }
    assert document["cache"] == {"max_age": 10, "max_size": 256}
    assert document["globally_unique_keys"] is True
    library = document["libraries"]
    assert len(library) == 1
    assert library[0]["table"] == "Parts"
    assert library[0]["key"] == "Component ID"
    assert library[0]["symbols"] == "KiCad Symbol Ref"
    assert library[0]["footprints"] == "KiCad Footprint Ref"
    assert library[0]["properties"] == {"description": "Description"}
    assert all(
        {
            "column",
            "name",
            "show_name",
            "visible_in_chooser",
            "visible_on_add",
        }
        == set(field)
        for field in library[0]["fields"]
    )


def test_altium_link_reuses_measured_dblib_conventions(tmp_path):
    bundle = _bundle()
    result = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        tmp_path / "stage",
        fixture_mode=True,
    )
    raw = result.altium_dblib_path.read_bytes()
    text = raw.decode()

    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert "Version=1.1" in text
    assert "TableName=Parts" in text
    assert "FieldNameOnly=MPN|FieldType=0|ParameterName=MPN" in text
    assert "ParameterName=[Library Ref]" in text
    assert "ParameterName=[Footprint Ref]" in text
    assert f"Database={result.catalog_path.resolve()};" in text
    assert "LibraryDatabasePath=.\\Catalog.sqlite" in text


def test_altium_link_can_target_the_final_live_catalog_path(tmp_path):
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    live_catalog = (tmp_path / "live" / CATALOG_FILENAME).resolve()
    result = stage_catalog_projection(
        bundle,
        artifacts,
        tmp_path / "stage",
        fixture_mode=True,
        altium_catalog_path=live_catalog,
    )

    assert result.altium_catalog_path == live_catalog
    assert f"Database={live_catalog};" in result.altium_dblib_path.read_text(encoding="utf-8")
    validate_catalog_projection(
        result.staging_directory,
        bundle,
        artifacts,
        fixture_mode=True,
        altium_catalog_path=live_catalog,
    )


def test_rebuilding_same_stage_is_byte_deterministic(tmp_path):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    first = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )
    before = _output_bytes(staging)
    second = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )

    assert _output_bytes(staging) == before
    assert second.catalog_sqlite_digest == first.catalog_sqlite_digest
    assert second.kicad_dbl_digest == first.kicad_dbl_digest
    assert second.altium_dblib_digest == first.altium_dblib_digest
    assert second.semantic_digest == first.semantic_digest
    assert second.revision == first.revision
    assert second.semantic_row_digest == first.semantic_row_digest


def test_semantic_identity_is_path_independent_and_manifest_is_canonical(tmp_path):
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    first = stage_catalog_projection(
        bundle,
        artifacts,
        tmp_path / "first",
        fixture_mode=True,
    )
    second = stage_catalog_projection(
        bundle,
        artifacts,
        tmp_path / "second",
        fixture_mode=True,
    )

    assert first.semantic_digest == second.semantic_digest
    assert first.revision == second.revision
    assert first.semantic_row_digest == second.semantic_row_digest
    assert first.catalog_path.read_bytes() == second.catalog_path.read_bytes()
    assert first.kicad_dbl_path.read_bytes() == second.kicad_dbl_path.read_bytes()
    assert first.catalog_digest_path.read_bytes() == second.catalog_digest_path.read_bytes()
    assert first.altium_dblib_digest != second.altium_dblib_digest
    document = json.loads(first.catalog_digest_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == CATALOG_SCHEMA_VERSION
    assert document["catalog_revision"] == first.revision
    assert document["catalog_semantic_digest"] == first.semantic_digest
    assert document["semantic_row_digest"] == first.semantic_row_digest
    assert document["source_canonical_digest"] == bundle.canonical_digest()
    row = lookup_catalog_component(
        first.catalog_path,
        manufacturer="ON Semiconductor",
        mpn="S1M",
    )
    assert row is not None
    assert document["semantic_row_digest"] == _digest_from_bytes(
        canonical_json([row]).encode("utf-8")
    )
    assert first.revision.startswith("catrev_")
    assert len(first.revision) == 59


def test_output_roles_form_a_commit_allowlist(tmp_path):
    bundle = _bundle()
    result = stage_catalog_projection(
        bundle,
        _artifacts(bundle),
        tmp_path / "stage",
        fixture_mode=True,
    )

    roles = {output.path.name: output.role for output in result.outputs}
    assert roles == {
        CATALOG_DIGEST_FILENAME: CatalogArtifactRole.TRACKED_PORTABLE,
        KICAD_DBL_FILENAME: CatalogArtifactRole.TRACKED_PORTABLE,
        CATALOG_FILENAME: CatalogArtifactRole.ACTIVATION_ONLY,
        ALTIUM_DBLIB_FILENAME: CatalogArtifactRole.MACHINE_LOCAL,
    }
    assert {path.name for path in result.tracked_portable_outputs} == {
        CATALOG_DIGEST_FILENAME,
        KICAD_DBL_FILENAME,
    }
    assert CATALOG_FILENAME not in {path.name for path in result.tracked_portable_outputs}


def test_fixture_mode_is_required_and_persisted_when_false(tmp_path):
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    with pytest.raises(TypeError):
        stage_catalog_projection(bundle, artifacts, tmp_path / "missing")  # type: ignore[call-arg]

    result = stage_catalog_projection(
        bundle,
        artifacts,
        tmp_path / "production-stage",
        fixture_mode=False,
    )
    assert result.fixture_mode is False
    with sqlite3.connect(result.catalog_path) as connection:
        assert (
            connection.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'fixture_mode'"
            ).fetchone()[0]
            == "false"
        )


def test_invalid_template_or_extra_input_is_rejected_before_writing(tmp_path):
    bundle = _bundle()
    document = _artifacts(bundle).model_dump(mode="json")
    document["links"][0]["template_id"] = "wrong-template"
    mismatched = CatalogArtifacts.model_validate_json(json.dumps(document))
    staging = tmp_path / "stage"

    with pytest.raises(CatalogProjectionError, match="expected"):
        stage_catalog_projection(
            bundle,
            mismatched,
            staging,
            fixture_mode=True,
        )
    assert not staging.exists()

    document = _artifacts(bundle).model_dump(mode="json")
    document["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        CatalogArtifacts.model_validate_json(json.dumps(document))


@pytest.mark.parametrize(
    "invalid_path",
    [
        "/absolute/file.kicad_sym",
        "C:/library/file.kicad_sym",
        "templates/name:stream.kicad_sym",
        r"\\server\share\file.kicad_sym",
        r"templates\file.kicad_sym",
        "templates/../file.kicad_sym",
        "templates/./file.kicad_sym",
        "templates//file.kicad_sym",
        "templates/",
    ],
)
def test_native_artifact_paths_must_be_portable_library_relative_posix(
    invalid_path,
):
    bundle = _bundle()
    link = _artifacts(bundle).links[0].model_dump(mode="json")
    link["path"] = invalid_path
    with pytest.raises(ValidationError, match="portable|segments"):
        ProjectedArtifact.model_validate_json(json.dumps(link))


def test_failed_staged_readback_preserves_previous_generation(tmp_path, monkeypatch):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )
    before = _output_bytes(staging)

    def fail_readback(_path, _catalog_path):
        raise CatalogProjectionError("injected readback failure")

    monkeypatch.setattr(
        projection_module,
        "_validate_altium_dblib",
        fail_readback,
    )
    with pytest.raises(CatalogProjectionError, match="injected"):
        stage_catalog_projection(
            bundle,
            artifacts,
            staging,
            fixture_mode=True,
        )
    assert _output_bytes(staging) == before


def test_public_readback_detects_catalog_tampering(tmp_path):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    result = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )
    with sqlite3.connect(result.catalog_path) as connection:
        connection.execute(
            'UPDATE "Parts" SET "Manufacturer" = ?',
            ("Other Manufacturer",),
        )
        connection.commit()

    with pytest.raises(CatalogProjectionError, match="row readback differs"):
        validate_catalog_projection(
            staging,
            bundle,
            artifacts,
            fixture_mode=True,
        )


def test_public_readback_detects_semantic_manifest_tampering(tmp_path):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    result = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )
    document = json.loads(result.catalog_digest_path.read_text(encoding="utf-8"))
    document["semantic_row_digest"] = _digest("tampered")
    result.catalog_digest_path.write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    with pytest.raises(CatalogProjectionError, match="Digest.json readback"):
        validate_catalog_projection(
            staging,
            bundle,
            artifacts,
            fixture_mode=True,
        )


def test_public_readback_detects_machine_local_link_tampering(tmp_path):
    staging = tmp_path / "stage"
    bundle = _bundle()
    artifacts = _artifacts(bundle)
    result = stage_catalog_projection(
        bundle,
        artifacts,
        staging,
        fixture_mode=True,
    )
    result.altium_dblib_path.write_bytes(
        result.altium_dblib_path.read_bytes().replace(
            b"ParameterName=Value",
            b"ParameterName=Wrong",
        )
    )

    with pytest.raises(CatalogProjectionError, match="DbLib readback differs"):
        validate_catalog_projection(
            staging,
            bundle,
            artifacts,
            fixture_mode=True,
        )
