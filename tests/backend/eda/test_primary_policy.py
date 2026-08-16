from __future__ import annotations

import pytest

from stockroom.eda.primary_policy import PrimaryEdaPolicy
from stockroom.store.machine_config import MachineConfig


def test_unconfirmed_machine_recommends_detected_tool_without_selecting_it():
    config = MachineConfig(onboarded=True)
    policy = PrimaryEdaPolicy(config)

    state = policy.snapshot(detected_keys=("altium",))

    assert state.primary_key is None
    assert state.pending_key is None
    assert state.recommended_key == "altium"
    assert state.confirmation_required is True
    assert config.primary_eda == ""


def test_recommendation_uses_registry_order_when_both_tools_are_detected():
    state = PrimaryEdaPolicy(MachineConfig()).snapshot(
        detected_keys=("altium", "kicad")
    )

    assert state.recommended_key == "kicad"


def test_invalid_persisted_tool_fails_closed_instead_of_falling_back():
    state = PrimaryEdaPolicy(MachineConfig(primary_eda="unknown")).snapshot()

    assert state.primary_key is None
    assert state.confirmation_required is True
    assert state.recommended_key is None


def test_machine_with_no_detected_tool_has_no_recommendation_or_silent_default():
    state = PrimaryEdaPolicy(MachineConfig()).snapshot()

    assert state.primary_key is None
    assert state.recommended_key is None
    assert state.confirmation_required is True


def test_pending_tool_without_a_valid_active_tool_fails_closed():
    state = PrimaryEdaPolicy(
        MachineConfig(primary_eda="unknown", primary_eda_pending="altium")
    ).snapshot()

    assert state.primary_key is None
    assert state.pending_key is None


def test_confirming_first_tool_activates_it_immediately():
    config = MachineConfig()
    policy = PrimaryEdaPolicy(config)

    state = policy.request_switch("altium")

    assert state.primary_key == "altium"
    assert state.pending_key is None
    assert config.primary_eda == "altium"
    assert config.primary_eda_pending == ""


def test_running_old_tool_stays_primary_until_its_work_finishes():
    config = MachineConfig(primary_eda="kicad")
    policy = PrimaryEdaPolicy(config)

    pending = policy.request_switch("altium", active_tool="kicad")

    assert pending.primary_key == "kicad"
    assert pending.pending_key == "altium"
    assert policy.activate_pending("altium") is False
    assert policy.snapshot().primary_key == "kicad"

    assert policy.activate_pending("kicad") is True
    active = policy.snapshot()
    assert active.primary_key == "altium"
    assert active.pending_key is None


def test_requesting_current_tool_cancels_a_pending_switch():
    config = MachineConfig(primary_eda="kicad", primary_eda_pending="altium")
    policy = PrimaryEdaPolicy(config)

    state = policy.request_switch("kicad", active_tool="kicad")

    assert state.primary_key == "kicad"
    assert state.pending_key is None


def test_unknown_tool_is_rejected_for_an_explicit_choice():
    with pytest.raises(ValueError, match="unknown primary CAD tool"):
        PrimaryEdaPolicy(MachineConfig()).request_switch("unknown")


def test_policy_derives_requirements_checks_and_settings_from_registry():
    policy = PrimaryEdaPolicy(MachineConfig(primary_eda="altium"))

    assert policy.requirements() == ("symbol", "footprint", "model")
    assert policy.setup_checks() == (
        "installation",
        "odbc",
        "catalog_connection",
    )
    assert policy.promoted_settings_target() == "settings.altium"
    assert policy.retained_optional_tool_keys() == ("kicad",)


def test_dto_is_one_shared_redacted_contract_for_settings_and_onboarding():
    dto = PrimaryEdaPolicy(
        MachineConfig(primary_eda="kicad", primary_eda_pending="altium")
    ).dto(detected_keys=("kicad", "altium"))

    assert dto["primary_eda"] == "kicad"
    assert dto["primary_eda_pending"] == "altium"
    assert dto["primary_eda_confirmation_required"] is False
    assert dto["recommended_primary_eda"] == "kicad"
    assert dto["primary_eda_requirements"] == ["symbol", "footprint", "model"]
    assert dto["retained_optional_eda"] == ["altium"]
    assert [tool["key"] for tool in dto["eda_tools"]] == ["kicad", "altium"]
    assert dto["eda_tools"][0] == {
        "key": "kicad",
        "label": "KiCad",
        "detected": True,
        "selected": True,
        "pending": False,
        "setup_checks": ["installation", "catalog_wiring"],
        "settings_target": "settings.kicad",
    }
