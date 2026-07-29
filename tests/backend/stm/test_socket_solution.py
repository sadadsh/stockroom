from __future__ import annotations

import json

from stockroom.stm.socket_solution import compile_socket_solution_from_definition


def _pin(
    ref: str,
    *,
    name: str,
    electrical: str,
    critical: str | None = None,
    family: str = "STM32F4",
) -> dict:
    return {
        "ref": ref,
        "family": family,
        "canonical_pin_name": name,
        "electrical_class": electrical,
        "critical_identity": critical,
        "roles": [],
        "functions": [],
        "alternate_functions": [],
        "access_tags": [],
    }


def _definition(target_count: int, positions: list[dict]) -> dict:
    targets = [
        {
            "ref": f"STM32F4TEST{i:04d}",
            "family": "STM32F4",
            "line": "STM32F4TEST",
            "verified_mpns": [],
        }
        for i in range(target_count)
    ]
    return {
        "format": "stm-target-definition/2",
        "compiler_rev": 8,
        "artifact_digest": "a" * 64,
        "scope": {
            "package": "LQFP64",
            "families": ["STM32F4"],
            "target_count": target_count,
            "targets": targets,
        },
        "provenance": {
            "silicon_source": "TEST",
            "source_sha256": "b" * 64,
            "classifier_rev": 2,
            "af_schema_rev": 1,
            "geometry_rev": 1,
        },
        "readiness": {"status": "ready", "blockers": [], "warnings": []},
        "functional_foundation": {"status": "complete"},
        "service_groups": [],
        "universalization": {"strategies": []},
        "positions": positions,
    }


def test_reset_gpio_pair_becomes_one_passive_compatible_lane():
    refs = ["STM32F4TEST0000", "STM32F4TEST0001"]
    definition = _definition(
        2,
        [
            {
                "position": "11",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": [
                    _pin(refs[0], name="NRST", electrical="reset", critical="reset"),
                    _pin(refs[1], name="PA0", electrical="io"),
                ],
            }
        ],
    )

    result = compile_socket_solution_from_definition(definition)
    position = result["positions"][0]

    assert result["format"] == "stm-socket-solution/1"
    assert position["cell_type"] == "passive-compatible-lane"
    assert position["safe_default"] == "connected"
    assert {mode["id"] for mode in position["modes"]} == {
        "reset",
        "universal-io",
    }
    assert len(position["branches"]) == 1
    assert position["branches"][0]["endpoint"] == "universal-lane"
    assert not position["branches"][0]["controlled"]
    assert result["summary"]["controlled_branches"] == 0
    assert result["proofs"][0]["position"] == "11"
    assert "bias current" in " ".join(result["proofs"][0]["checks"])
    assert result["summary"]["target_cohort_count"] == 2
    assert result["closure"]["zero_omission"] is True
    assert result["closure"]["supported_target_count"] == 2


def test_one_thousand_targets_compact_to_unique_modes_and_cohorts():
    target_count = 1000
    refs = [f"STM32F4TEST{i:04d}" for i in range(target_count)]
    role_pins = []
    for index, ref in enumerate(refs):
        if index < 810:
            role_pins.append(_pin(ref, name="PA0", electrical="io"))
        elif index < 980:
            role_pins.append(_pin(ref, name="NRST", electrical="reset", critical="reset"))
        # The final 20 targets intentionally omit the physical position.
    stable_pins = [
        _pin(ref, name=f"P{chr(65 + (index % 4))}1", electrical="io")
        for index, ref in enumerate(refs)
    ]
    definition = _definition(
        target_count,
        [
            {
                "position": "11",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": role_pins,
            },
            {
                "position": "12",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": stable_pins,
            },
        ],
    )

    result = compile_socket_solution_from_definition(definition)
    role_position = result["positions"][0]

    assert result["summary"]["target_count"] == 1000
    assert result["summary"]["target_cohort_count"] == 3
    assert role_position["mode_count"] == 3
    assert {mode["target_count"] for mode in role_position["modes"]} == {
        810,
        170,
        20,
    }
    assert role_position["cell_type"] == "passive-compatible-lane"
    assert len(role_position["branches"]) == 1
    assert result["summary"]["controlled_branches"] == 0
    assert len(result["scope"]["target_index"]) == 1000
    assert all(len(cohort["target_examples"]) <= 8 for cohort in result["target_cohorts"])
    assert (
        sum(int(cohort["target_mask"], 16).bit_count() for cohort in result["target_cohorts"])
        == 1000
    )
    assert result["closure"]["zero_omission"] is True
    assert result["closure"]["supported_target_count"] == 1000
    assert result["closure"]["configuration_errors"] == []


def test_one_thousand_identical_targets_need_one_lane_and_no_control_bits():
    target_count = 1000
    refs = [f"STM32F4TEST{i:04d}" for i in range(target_count)]
    definition = _definition(
        target_count,
        [
            {
                "position": "1",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": [_pin(ref, name="PA0", electrical="io") for ref in refs],
            }
        ],
    )

    first = compile_socket_solution_from_definition(definition)
    second = compile_socket_solution_from_definition(definition)

    assert first["artifact_digest"] == second["artifact_digest"]
    assert first["summary"]["target_cohort_count"] == 1
    assert first["summary"]["universal_lanes"] == 1
    assert first["summary"]["controlled_branches"] == 0
    assert first["fabric"]["control_bits_required"] == 0
    assert first["closure"]["verdict"] == "architecture-complete"
    assert first["closure"]["target_coverage_percentage"] == 100
    serialized = json.dumps(first)
    for forbidden in ("Netdeck", "Altium", "ADG714", "build card"):
        assert forbidden not in serialized


def test_vdda_and_vref_compact_to_one_proven_shared_analog_network():
    refs = ["STM32F4TEST0000", "STM32F4TEST0001"]
    definition = _definition(
        2,
        [
            {
                "position": "13",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": [
                    _pin(
                        refs[0],
                        name="VDDA",
                        electrical="power",
                        critical="power:vdda",
                    ),
                    _pin(
                        refs[1],
                        name="VREF+",
                        electrical="power",
                        critical="power:vref",
                    ),
                ],
            }
        ],
    )

    result = compile_socket_solution_from_definition(definition)
    position = result["positions"][0]

    assert position["cell_type"] == "shared-analog-network"
    assert position["controlled"] is False
    assert position["branches"][0]["endpoint"] == "fixed:power:analog-common"
    assert result["fabric"]["control_bits_required"] == 0
    assert result["status"]["solution"] == "conditional"
    assert "common voltage range" in " ".join(result["proofs"][0]["checks"])


def test_power_and_gpio_remain_default_open_selected_roles():
    refs = ["STM32F4TEST0000", "STM32F4TEST0001"]
    definition = _definition(
        2,
        [
            {
                "position": "30",
                "position_kind": "numeric",
                "lqfp_side": "bottom",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": [
                    _pin(
                        refs[0],
                        name="VDD",
                        electrical="power",
                        critical="power:vdd",
                    ),
                    _pin(refs[1], name="PA4", electrical="io"),
                ],
            }
        ],
    )

    result = compile_socket_solution_from_definition(definition)
    position = result["positions"][0]

    assert position["cell_type"] == "selected-roles"
    assert position["controlled"] is True
    assert position["safe_default"] == "open"
    assert len(position["branches"]) == 2
    assert all(branch["controlled"] for branch in position["branches"])
    assert position["hazard_contract"]["level"] == "critical"
    assert position["hazard_contract"]["category"] == "power-domain"
    assert position["cell_contract"]["architecture"] == ("fail-closed-universal-position-cell")
    assert (
        "hardware-enforced one-hot branch selection"
        in position["cell_contract"]["mandatory_features"]
    )
    assert result["bootstrap"]["status"] == "requires-declared-target"
    assert result["closure"]["zero_omission"] is True
    assert result["closure"]["supported_target_count"] == 2
    assert result["closure"]["configuration_errors"] == []
    assert result["closure"]["gates"][0]["value"] == "2/2"
    assert all(len(cohort["configuration"]) == 1 for cohort in result["target_cohorts"])


def test_required_access_measures_socket_routes_not_source_policy_rejections():
    refs = ["STM32F4TEST0000", "STM32F4TEST0001"]
    definition = _definition(
        2,
        [
            {
                "position": "1",
                "position_kind": "numeric",
                "lqfp_side": "left",
                "bga_row": None,
                "bga_col": None,
                "hazard": "",
                "per_target": [
                    _pin(refs[0], name="PA13", electrical="io"),
                    _pin(refs[1], name="PA13", electrical="io"),
                ],
            }
        ],
    )
    definition["requirements"] = [
        {
            "id": "swdio",
            "label": "SWD Data",
            "required": True,
            "routes": [{"ref": ref, "position": "1", "usable": False} for ref in refs],
            "missing_targets": [],
        },
        {
            "id": "boot1",
            "label": "Boot 1",
            "required": True,
            "routes": [{"ref": refs[0], "position": "1", "usable": False}],
            "missing_targets": [refs[1]],
        },
    ]

    result = compile_socket_solution_from_definition(definition)
    coverage = {
        requirement["id"]: requirement
        for requirement in result["closure"]["required_requirement_coverage"]
    }

    assert coverage["swdio"]["status"] == "pass"
    assert coverage["swdio"]["covered_targets"] == 2
    assert coverage["swdio"]["architecture_missing_targets"] == []
    assert coverage["boot1"]["status"] == "pass"
    assert coverage["boot1"]["covered_targets"] == 1
    assert coverage["boot1"]["available_target_count"] == 1
    assert coverage["boot1"]["missing_targets"] == [refs[1]]
    assert result["closure"]["gates"][3]["value"] == "2/2 Complete"
