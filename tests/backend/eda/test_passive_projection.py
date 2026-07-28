from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

import stockroom.eda.passive_projection as passive_projection
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)
from stockroom.eda import (
    ProjectionMismatch,
    UnsupportedProjection,
    project_passive_bundle,
)
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.stock import find_kicad_share_dir

FIXTURE = Path(__file__).parents[1] / "altium" / "fixtures" / "sample.IntLib"
_DIGEST_A = f"sha256:{hashlib.sha256(b'value-evidence').hexdigest()}"
_DIGEST_B = f"sha256:{hashlib.sha256(b'package-evidence').hexdigest()}"

pytestmark = pytest.mark.requires_kicad_cli


def _bundle(
    *,
    manufacturer: str = "ON Semiconductor",
    mpn: str = "S1M",
) -> CanonicalPassiveBundle:
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
        functional_kind="diode",
        value="1 A 1000 V",
        package="SMA (DO-214AC)",
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/value",
            content_digest=_DIGEST_A,
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/package",
            content_digest=_DIGEST_B,
        ),
    )


def _requires_kicad_10() -> None:
    cli = KiCadCli()
    if not cli.available or find_kicad_share_dir() is None:
        pytest.skip("installed KiCad 10 CLI and stock libraries are required")
    if not cli.version().startswith("10."):
        pytest.skip("this projection is qualified only against KiCad 10")


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def test_projects_s1m_into_content_addressed_staging_with_real_readback(tmp_path):
    _requires_kicad_10()
    staging = tmp_path / "staging"
    staging.mkdir()
    canonical = _bundle()

    result = project_passive_bundle(
        canonical,
        staging,
        fixture_mode=True,
        altium_intlib=FIXTURE,
    )

    assert result.canonical_bundle_digest == canonical.canonical_digest()
    assert result.semantic_cross_check_passed is True
    assert result.production_ready is False
    assert result.limitations == (
        "Altium artifacts were acquired from a checked-in fixture, not generated.",
        "Altium semantics were read from OLE fixture streams, not the live official adapter.",
        "Database-library browse, placement, and compilation were not exercised.",
    )

    assert result.kicad.tool == "kicad"
    assert result.kicad.fixture_mode is False
    assert result.kicad.tool_version.startswith("10.")
    assert result.kicad.binding.symbol_template_id == "shared.passive.diode.two_pin.v1"
    assert result.kicad.binding.footprint_template_id == "shared.passive.diode.sma_do_214ac.v1"
    assert result.kicad.binding.source_symbol_reference == "Device:D"
    assert result.kicad.binding.source_footprint_reference == "Diode_SMD:D_SMA"
    nickname = f"Stockroom_{canonical.identity.component_id}"
    assert result.kicad.binding.symbol_library_nickname == nickname
    assert result.kicad.binding.footprint_library_nickname == nickname
    assert result.kicad.binding.symbol_ref == f"{nickname}:S1M"
    assert result.kicad.binding.footprint_ref == f"{nickname}:S1M"
    assert [(pin.native_number, pin.name, pin.tool_terminal) for pin in result.kicad.pins] == [
        ("1", "K", "1"),
        ("2", "A", "2"),
    ]
    assert [(pad.native_number, pad.tool_terminal) for pad in result.kicad.pads] == [
        ("1", "1"),
        ("2", "2"),
    ]

    assert result.altium.tool == "altium"
    assert result.altium.fixture_mode is True
    assert result.altium.tool_version == ""
    assert result.altium.binding.symbol_template_id == "shared.passive.diode.two_pin.v1"
    assert result.altium.binding.footprint_template_id == "shared.passive.diode.sma_do_214ac.v1"
    assert result.altium.binding.source_symbol_reference == "S1M"
    assert result.altium.binding.source_footprint_reference == "DIOM5227X270N"
    assert result.altium.binding.symbol_library_nickname is None
    assert result.altium.binding.footprint_library_nickname is None
    assert result.altium.binding.symbol_ref == "S1M"
    assert result.altium.binding.footprint_ref == "DIOM5227X270N"
    assert [(pin.native_number, pin.name, pin.tool_terminal) for pin in result.altium.pins] == [
        ("C", "K", "C"),
        ("A", "A", "A"),
    ]
    assert [(pad.native_number, pad.tool_terminal) for pad in result.altium.pads] == [
        ("C", "C"),
        ("A", "A"),
    ]
    assert {evidence.locator.rsplit(":", 1)[-1] for evidence in result.altium.evidence} == {
        "FileHeader",
        "S1M/Data",
        "DIOM5227X270N/Data",
    }

    artifacts = {(artifact.tool, artifact.kind): artifact for artifact in result.artifacts}
    assert set(artifacts) == {
        ("altium", "footprint"),
        ("altium", "symbol"),
        ("kicad", "footprint"),
        ("kicad", "symbol"),
    }
    for artifact in artifacts.values():
        path = staging / Path(artifact.relative_path)
        assert path.is_file()
        assert artifact.digest == _sha256(path)
        assert artifact.size_bytes == path.stat().st_size
        assert artifact.digest.removeprefix("sha256:") in Path(artifact.relative_path).parts
        assert "\\" not in artifact.relative_path

    altium_symbol = staging / Path(artifacts[("altium", "symbol")].relative_path)
    altium_footprint = staging / Path(artifacts[("altium", "footprint")].relative_path)
    assert read_symbol_names(altium_symbol) == ["S1M"]
    assert read_footprint_names(altium_footprint) == ["DIOM5227X270N"]
    assert sorted(
        path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()
    ) == sorted(artifact.relative_path for artifact in result.artifacts)


def test_projection_is_byte_and_path_deterministic_for_installed_kicad(tmp_path):
    _requires_kicad_10()
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    first = project_passive_bundle(
        _bundle(),
        left,
        fixture_mode=True,
        altium_intlib=FIXTURE,
    )
    second = project_passive_bundle(
        _bundle(),
        right,
        fixture_mode=True,
        altium_intlib=FIXTURE,
    )

    assert [
        (
            artifact.tool,
            artifact.kind,
            artifact.template_id,
            artifact.reference,
            artifact.relative_path,
            artifact.digest,
            artifact.size_bytes,
        )
        for artifact in first.artifacts
    ] == [
        (
            artifact.tool,
            artifact.kind,
            artifact.template_id,
            artifact.reference,
            artifact.relative_path,
            artifact.digest,
            artifact.size_bytes,
        )
        for artifact in second.artifacts
    ]


def test_non_fixture_altium_mode_is_rejected_before_staging_is_touched(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(UnsupportedProjection, match="native Altium adapter"):
        project_passive_bundle(
            _bundle(),
            staging,
            fixture_mode=False,
            altium_intlib=FIXTURE,
        )

    assert list(staging.iterdir()) == []


def test_staging_directory_must_already_exist_and_be_empty(tmp_path):
    _requires_kicad_10()
    absent = tmp_path / "absent"
    with pytest.raises(ValueError, match="existing empty directory"):
        project_passive_bundle(
            _bundle(),
            absent,
            fixture_mode=True,
            altium_intlib=FIXTURE,
        )

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "owner.txt").write_text("preserve me", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        project_passive_bundle(
            _bundle(),
            occupied,
            fixture_mode=True,
            altium_intlib=FIXTURE,
        )
    assert (occupied / "owner.txt").read_text(encoding="utf-8") == "preserve me"


def test_domain_model_is_revalidated_and_broken_links_never_reach_staging(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    canonical = _bundle()
    corrupted_artifacts = canonical.artifacts.model_copy(
        update={"definition_digest": f"sha256:{'0' * 64}"}
    )
    corrupted = canonical.model_copy(update={"artifacts": corrupted_artifacts})

    with pytest.raises(ValidationError, match="definition digest link"):
        project_passive_bundle(
            corrupted,
            staging,
            fixture_mode=True,
            altium_intlib=FIXTURE,
        )

    assert list(staging.iterdir()) == []


def test_native_readback_mismatch_fails_closed_without_partial_projection(
    tmp_path,
    monkeypatch,
):
    _requires_kicad_10()
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(
        passive_projection,
        "_read_altium_pad_numbers",
        lambda _raw, _name: ("A", "WRONG"),
    )

    with pytest.raises(ProjectionMismatch, match="Altium pad"):
        project_passive_bundle(
            _bundle(),
            staging,
            fixture_mode=True,
            altium_intlib=FIXTURE,
        )

    assert list(staging.iterdir()) == []


def test_only_exact_supported_domain_identity_is_accepted(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(UnsupportedProjection, match="ON Semiconductor/S1M"):
        project_passive_bundle(
            _bundle(manufacturer="onsemi"),
            staging,
            fixture_mode=True,
            altium_intlib=FIXTURE,
        )

    assert list(staging.iterdir()) == []
