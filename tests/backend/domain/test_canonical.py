import hashlib
import json

import pytest
from pydantic import ValidationError

from stockroom.domain import (
    ArtifactSet,
    AuthoritativeEvidence,
    BodyRectangleNm,
    CanonicalPassiveBundle,
    Manufacturer,
    PassiveTerminal,
    PointNm,
    ToolNeutralDefinition,
    build_two_pin_passive_bundle,
    canonical_model_digest,
)
from stockroom.workflow.identifiers import derive_component_identity, digest_text


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _evidence(label: str) -> AuthoritativeEvidence:
    return AuthoritativeEvidence(
        source_kind="manufacturer_datasheet",
        source_locator=f"https://manufacturer.example/{label}.pdf",
        content_digest=_digest(label),
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


def test_complete_passive_bundle_has_deterministic_bytes_and_digest():
    first = _bundle()
    second = _bundle()

    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.canonical_digest() == second.canonical_digest()
    assert first.canonical_bytes().endswith(b"\n")
    assert first.canonical_bytes() == (
        json.dumps(
            json.loads(first.canonical_bytes()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        + b"\n"
    )
    assert CanonicalPassiveBundle.model_validate_json(first.canonical_bytes()) == first


def test_identity_reuses_workflow_full_digest_derivation():
    bundle = _bundle()
    expected = derive_component_identity(
        "ON Semiconductor",
        "S1M",
    )

    assert bundle.manufacturer.manufacturer_id == expected.manufacturer_id
    assert bundle.identity.component_id == expected.component_id
    assert bundle.identity.identity_digest == digest_text(expected.component_digest)
    assert len(bundle.identity.component_id) == 56


def test_bundle_contains_selected_authoritative_value_and_package_claims():
    bundle = _bundle()

    assert tuple(claim.key for claim in bundle.claims) == ("value", "package")
    assert tuple(claim.value for claim in bundle.claims) == (
        "1 kV, 1 A rectifier diode",
        "SMA (DO-214AC)",
    )
    assert bundle.verification.claim_evidence_digests == (
        _digest("value"),
        _digest("package"),
    )


def test_qualified_fixture_evidence_is_explicit_in_canonical_facts():
    evidence = AuthoritativeEvidence(
        source_kind="qualified_fixture",
        source_locator="fixture:sample.IntLib#S1M",
        content_digest=_digest("sample-intlib"),
    )

    assert evidence.source_kind == "qualified_fixture"


def test_tool_neutral_geometry_uses_only_integer_nm_and_udeg():
    definition = _bundle().definition

    assert definition.geometry_unit == "nm"
    assert definition.angle_unit == "udeg"
    assert tuple(terminal.number for terminal in definition.terminals) == ("1", "2")
    assert tuple(terminal.role for terminal in definition.terminals) == (
        "cathode",
        "anode",
    )
    assert all(
        type(coordinate) is int
        for terminal in definition.terminals
        for coordinate in (
            terminal.position.x_nm,
            terminal.position.y_nm,
            terminal.rotation_udeg,
        )
    )
    with pytest.raises(ValidationError):
        PointNm(x_nm=1.5, y_nm=0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        PassiveTerminal(
            number="1",
            role="cathode",
            position=PointNm(x_nm=0, y_nm=0),
            rotation_udeg=360_000_000,
        )


def test_artifacts_bind_exactly_kicad_and_altium_to_shared_templates():
    artifacts = _bundle().artifacts
    symbol, footprint = artifacts.shared_templates

    assert tuple(binding.tool for binding in artifacts.tool_bindings) == (
        "kicad",
        "altium",
    )
    assert all(
        binding.symbol_template_id == symbol.template_id
        and binding.footprint_template_id == footprint.template_id
        for binding in artifacts.tool_bindings
    )
    assert tuple(
        (terminal.canonical_terminal, terminal.tool_terminal)
        for terminal in artifacts.tool_bindings[0].terminal_bindings
    ) == (("1", "1"), ("2", "2"))
    assert tuple(
        (terminal.canonical_terminal, terminal.tool_terminal)
        for terminal in artifacts.tool_bindings[1].terminal_bindings
    ) == (("1", "C"), ("2", "A"))

    document = artifacts.model_dump(mode="json")
    document["tool_bindings"][1]["tool"] = "kicad"
    with pytest.raises(ValidationError, match="exactly KiCad and Altium"):
        ArtifactSet.model_validate_json(json.dumps(document))


def test_schema_is_versioned_strict_and_forbids_unknown_fields():
    bundle_document = _bundle().model_dump(mode="json")
    bundle_document["invented"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CanonicalPassiveBundle.model_validate(bundle_document)

    manufacturer_document = _bundle().manufacturer.model_dump(mode="json")
    manufacturer_document["schema_version"] = 2
    with pytest.raises(ValidationError):
        Manufacturer.model_validate(manufacturer_document)

    with pytest.raises(ValidationError):
        BodyRectangleNm(
            min_x_nm=-1,
            min_y_nm=0,
            max_x_nm=True,  # type: ignore[arg-type]
            max_y_nm=1,
        )


def test_canonical_content_stores_facts_but_no_runtime_readiness():
    document = _bundle().model_dump(mode="json")
    serialized_keys: set[str] = set()

    def collect(value) -> None:
        if isinstance(value, dict):
            serialized_keys.update(value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(document)
    assert serialized_keys.isdisjoint(
        {
            "complete",
            "is_complete",
            "ready",
            "readiness",
            "status",
            "workflow_state",
        }
    )


def test_bundle_rejects_broken_content_links_and_nonexact_identity_text():
    bundle = _bundle()
    document = bundle.model_dump(mode="json")
    document["artifacts"]["definition_digest"] = _digest("other-definition")
    with pytest.raises(ValidationError, match="definition digest link"):
        CanonicalPassiveBundle.model_validate_json(json.dumps(document))

    with pytest.raises(ValueError, match="surrounding whitespace"):
        build_two_pin_passive_bundle(
            authoritative_manufacturer_key=" ON Semiconductor",
            mpn_canonical="S1M",
            functional_kind="diode",
            value="1 kV, 1 A rectifier diode",
            package="SMA (DO-214AC)",
            value_evidence=_evidence("value"),
            package_evidence=_evidence("package"),
        )


def test_definition_and_artifact_digests_are_recomputed_from_exact_content():
    bundle = _bundle()

    assert bundle.artifacts.definition_digest == canonical_model_digest(bundle.definition)
    assert bundle.verification.definition_digest == canonical_model_digest(bundle.definition)
    assert bundle.verification.artifact_set_digest == canonical_model_digest(bundle.artifacts)


def test_unsupported_kind_package_pair_is_not_silently_mapped_to_a_template():
    with pytest.raises(ValueError, match="unsupported two-pin passive template"):
        build_two_pin_passive_bundle(
            authoritative_manufacturer_key="ON Semiconductor",
            mpn_canonical="S1M",
            functional_kind="resistor",
            value="1 kV, 1 A rectifier diode",
            package="SMA (DO-214AC)",
            value_evidence=_evidence("value"),
            package_evidence=_evidence("package"),
        )


def test_definition_rejects_duplicate_or_reordered_terminals():
    bundle = _bundle()
    terminal = bundle.definition.terminals[0]

    with pytest.raises(ValidationError, match="exactly"):
        ToolNeutralDefinition(
            component_id=bundle.identity.component_id,
            functional_kind="diode",
            body=bundle.definition.body,
            terminals=(terminal, terminal),
        )


def test_tool_binding_rejects_duplicate_native_terminal_identifiers():
    document = _bundle().artifacts.model_dump(mode="json")
    document["tool_bindings"][1]["terminal_bindings"][1]["tool_terminal"] = "C"

    with pytest.raises(ValidationError, match="must be unique"):
        ArtifactSet.model_validate_json(json.dumps(document))
