from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from stockroom.templates import (
    PassiveTemplateDefinition,
    passive_template_definition,
    representative_passive_template,
)


def test_representative_template_is_versioned_deterministic_and_round_trips() -> None:
    first = representative_passive_template()
    second = passive_template_definition("diode", "SMA (DO-214AC)")

    assert first is second
    assert first.schema_version == 1
    assert first.profile_id == "shared.passive.diode.sma_do_214ac.profile.v1"
    assert first.canonical_bytes().endswith(b"\n")
    assert PassiveTemplateDefinition.model_validate_json(first.canonical_bytes()) == first
    assert first.canonical_digest() == second.canonical_digest()
    assert (
        first.canonical_digest()
        == "sha256:6d27e86dc5b339b97cf2be42b7e7c068d212048dd3ce97775f61016f7922b3ff"
    )
    assert first.canonical_bytes() == (
        json.dumps(
            json.loads(first.canonical_bytes()),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def test_representative_template_binds_both_edas_to_one_shared_definition() -> None:
    profile = representative_passive_template()

    assert tuple(binding.tool for binding in profile.tool_bindings) == (
        "kicad",
        "altium",
    )
    assert tuple(artifact.kind for artifact in profile.artifacts) == (
        "symbol",
        "footprint",
    )
    symbol_id, footprint_id = (artifact.template_id for artifact in profile.artifacts)
    assert all(
        binding.symbol_template_id == symbol_id and binding.footprint_template_id == footprint_id
        for binding in profile.tool_bindings
    )
    assert tuple(
        terminal.tool_terminal for terminal in profile.binding_for("kicad").terminal_bindings
    ) == ("1", "2")
    assert tuple(
        terminal.tool_terminal for terminal in profile.binding_for("altium").terminal_bindings
    ) == ("C", "A")
    assert profile.binding_for("kicad").adapter_symbol_reference == "Device:D"
    assert profile.binding_for("kicad").adapter_footprint_reference == "Diode_SMD:D_SMA"


def test_template_definition_contains_no_readiness_or_native_success_shortcut() -> None:
    document = representative_passive_template().model_dump(mode="json")
    keys: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            keys.update(str(key) for key in value)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(document)
    assert keys.isdisjoint(
        {
            "complete",
            "native_verified",
            "production_ready",
            "readiness",
            "status",
            "verified",
        }
    )


def test_missing_altium_binding_or_forged_template_digest_fails_closed() -> None:
    profile = representative_passive_template()
    document = profile.model_dump(mode="json")
    document["tool_bindings"] = document["tool_bindings"][:1]
    with pytest.raises(ValidationError):
        PassiveTemplateDefinition.model_validate_json(json.dumps(document))

    document = profile.model_dump(mode="json")
    document["tool_bindings"][1]["tool"] = "kicad"
    with pytest.raises(ValidationError, match="explicit KiCad and Altium"):
        PassiveTemplateDefinition.model_validate_json(json.dumps(document))

    document = profile.model_dump(mode="json")
    document["artifacts"][0]["contract_digest"] = f"sha256:{'0' * 64}"
    with pytest.raises(ValidationError, match="does not match its identity"):
        PassiveTemplateDefinition.model_validate_json(json.dumps(document))


def test_a_template_revision_is_new_content_and_does_not_mutate_old_bytes() -> None:
    profile = representative_passive_template()
    old_bytes = profile.canonical_bytes()
    document = profile.model_dump(mode="json")
    document["profile_id"] = "shared.passive.diode.sma_do_214ac.profile.v2"
    revised = PassiveTemplateDefinition.model_validate_json(json.dumps(document))

    assert revised.canonical_digest() != profile.canonical_digest()
    assert profile.canonical_bytes() == old_bytes
    assert PassiveTemplateDefinition.model_validate_json(old_bytes) == profile


def test_profile_resolution_is_exact_and_preserves_the_existing_resistor_contract() -> None:
    resistor = passive_template_definition("resistor", "0603 (1608 Metric)")

    assert resistor.functional_kind == "resistor"
    assert tuple(binding.tool for binding in resistor.tool_bindings) == (
        "kicad",
        "altium",
    )
    with pytest.raises(ValueError, match="unsupported two-pin passive template"):
        passive_template_definition("resistor", "0603")
