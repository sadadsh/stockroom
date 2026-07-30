from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from stockroom.domain import AuthoritativeEvidence, build_two_pin_passive_bundle
from stockroom.eda import (
    PassiveTemplateSourceProof,
    build_passive_template_source_proof,
    render_kicad_template_source_plan,
)
from stockroom.templates import representative_passive_template


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _bundle():
    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key="ON Semiconductor",
        mpn_canonical="S1M",
        functional_kind="diode",
        value="1 A 1000 V",
        package="SMA (DO-214AC)",
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://source-proof/value",
            content_digest=_digest("value"),
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://source-proof/package",
            content_digest=_digest("package"),
        ),
    )


def test_dual_eda_source_proof_is_deterministic_and_round_trips() -> None:
    first = build_passive_template_source_proof(_bundle())
    second = build_passive_template_source_proof(_bundle())

    assert first == second
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.canonical_digest() == second.canonical_digest()
    assert (
        first.canonical_digest()
        == "sha256:56227ae29e3816e537e18bb7b84fe226f0f66504fb4dda51849b17a736d49c88"
    )
    assert PassiveTemplateSourceProof.model_validate_json(first.canonical_bytes()) == first
    assert first.canonical_bytes() == (
        json.dumps(
            json.loads(first.canonical_bytes()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def test_source_proof_binds_actual_adapter_sources_but_never_claims_native_readiness() -> None:
    bundle = _bundle()
    profile = representative_passive_template()
    proof = build_passive_template_source_proof(bundle)

    assert proof.component_id == bundle.identity.component_id
    assert proof.canonical_bundle_digest == bundle.canonical_digest()
    assert proof.template_profile_id == profile.profile_id
    assert proof.template_profile_digest == profile.canonical_digest()
    assert tuple(adapter.tool for adapter in proof.adapters) == ("kicad", "altium")
    assert tuple(adapter.adapter_revision for adapter in proof.adapters) == tuple(
        binding.adapter_revision for binding in profile.tool_bindings
    )
    assert tuple(adapter.source_kind for adapter in proof.adapters) == (
        "kicad_projection_plan",
        "altium_delphiscript",
    )
    assert proof.native_execution == "not_run"
    assert proof.limitations[-1] == (
        "Source-contract proof is not component publication readiness evidence."
    )
    assert set(proof.model_dump(mode="json")).isdisjoint(
        {"complete", "production_ready", "readiness", "status", "verified"}
    )


def test_kicad_source_plan_resolves_the_same_profile_and_is_stable() -> None:
    bundle = _bundle()
    profile = representative_passive_template()

    first = render_kicad_template_source_plan(bundle)
    second = render_kicad_template_source_plan(bundle)
    document = json.loads(first)

    assert first == second
    assert document["profile_digest"] == profile.canonical_digest()
    assert document["adapter_revision"] == profile.binding_for("kicad").adapter_revision
    assert document["symbol"]["source_reference"] == "Device:D"
    assert document["footprint"]["source_reference"] == "Diode_SMD:D_SMA"
    assert document["canonical_bundle_digest"] == bundle.canonical_digest()


def test_source_proof_boundary_cannot_be_weakened_during_round_trip() -> None:
    document = build_passive_template_source_proof(_bundle()).model_dump(mode="json")
    document["native_execution"] = "passed"
    document["limitations"] = []

    with pytest.raises(ValidationError):
        PassiveTemplateSourceProof.model_validate_json(json.dumps(document))


def test_missing_or_relabelled_altium_source_evidence_fails_closed() -> None:
    document = build_passive_template_source_proof(_bundle()).model_dump(mode="json")
    document["adapters"] = document["adapters"][:1]
    with pytest.raises(ValidationError):
        PassiveTemplateSourceProof.model_validate_json(json.dumps(document))

    document = build_passive_template_source_proof(_bundle()).model_dump(mode="json")
    document["adapters"][1]["tool"] = "kicad"
    with pytest.raises(ValidationError, match="KiCad then Altium"):
        PassiveTemplateSourceProof.model_validate_json(json.dumps(document))

    document = build_passive_template_source_proof(_bundle()).model_dump(mode="json")
    document["adapters"][1]["source_kind"] = "kicad_projection_plan"
    with pytest.raises(ValidationError, match="wrong source kind"):
        PassiveTemplateSourceProof.model_validate_json(json.dumps(document))
