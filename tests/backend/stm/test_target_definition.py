"""Hardware-aware target-definition compiler tests.

The compiler deliberately separates three questions that the legacy compatibility
surface mixed together:

1. What silicon facts differ at one physical package position?
2. Which service requirement selects a physical route?
3. Which selected routes consume controllable hardware channels?
"""

from __future__ import annotations

import sqlite3

import pytest

from stockroom.stm.db import _SCHEMA
from stockroom.stm.target_definition import (
    compile_target_definition,
    resolve_target_refs,
)


def _policy(**overrides) -> dict:
    policy = {
        "id": "test-profile",
        "revision": 1,
        "requirements": [],
        "safety_rules": [],
        "channel_fabric": {
            "part_mpn": "TEST-SWITCH-8",
            "channels_per_device": 8,
            "max_devices": 2,
            "default_state": "open",
            "reference_prefix": "U_ROUTE",
        },
        "declared_blockers": [],
    }
    policy.update(overrides)
    return policy


def _meta() -> dict:
    return {
        "source_sha256": "abc123",
        "built_at": "2026-07-23T00:00:00Z",
        "classifier_rev": "2",
        "af_schema_rev": "1",
        "geometry_rev": "3",
    }


def test_optional_af_differences_do_not_become_hardware_switches(stm_conn, stm_refs):
    result = compile_target_definition(
        stm_conn,
        refs=[stm_refs["mcu1"], stm_refs["mcu2"]],
        policy=_policy(),
        source_meta=_meta(),
    )

    positions = {row["position"]: row for row in result["positions"]}
    assert positions["13"]["silicon_class"] == "stable_io"
    assert positions["13"]["board_action"] == "breakout"
    assert positions["45"]["silicon_class"] == "stable_io"
    assert positions["45"]["board_action"] == "breakout"
    assert result["channel_fabric"]["required_channels"] == 0


def test_scope_selection_resolves_to_an_explicit_sorted_device_set(stm_conn, stm_refs):
    refs = resolve_target_refs(
        stm_conn,
        {"package": "LQFP64", "families": ["STM32F4", "STM32F1"]},
    )
    assert refs == sorted(
        [stm_refs["mcu1"], stm_refs["mcu1b"], stm_refs["mcu2"], stm_refs["mcu3"]]
    )


def test_required_signal_on_one_shared_position_is_a_direct_route(stm_conn, stm_refs):
    policy = _policy(
        requirements=[
            {
                "id": "uart_tx",
                "label": "Boot UART TX",
                "net": "UART_BOOT_TX",
                "required": True,
                "signal_patterns": [r"USART1_TX"],
                "evidence": ["STM32CubeMX signal table"],
            }
        ]
    )
    result = compile_target_definition(
        stm_conn,
        refs=[stm_refs["mcu1"], stm_refs["mcu2"]],
        policy=policy,
        source_meta=_meta(),
    )

    route = result["requirements"][0]
    assert route["route_kind"] == "direct"
    assert {row["position"] for row in route["routes"]} == {"12"}
    assert result["channel_fabric"]["required_channels"] == 0
    pos12 = next(row for row in result["positions"] if row["position"] == "12")
    assert pos12["board_action"] == "direct"
    assert pos12["route_ids"] == ["uart_tx"]


def test_missing_required_signal_is_a_readiness_blocker(stm_conn, stm_refs):
    policy = _policy(
        requirements=[
            {
                "id": "adc14",
                "label": "ADC channel 14",
                "net": "ADC14",
                "required": True,
                "signal_patterns": [r"ADC1_IN14"],
                "evidence": ["STM32CubeMX signal table"],
            }
        ]
    )
    result = compile_target_definition(
        stm_conn,
        refs=[stm_refs["mcu1"], stm_refs["mcu2"]],
        policy=policy,
        source_meta=_meta(),
    )

    assert result["requirements"][0]["route_kind"] == "blocked"
    assert result["readiness"]["status"] == "blocked"
    assert any("adc14" in item for item in result["readiness"]["blockers"])


def _tiny_connection() -> tuple[sqlite3.Connection, list[str], list[int]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    artifact = conn.execute(
        "INSERT INTO source_artifact (path, imported_at) VALUES (?, ?)",
        ("/fixture", "2026-07-23T00:00:00Z"),
    ).lastrowid

    refs = ["STM32TESTA", "STM32TESTB"]
    mcu_ids = []
    for ref in refs:
        mcu_ids.append(
            conn.execute(
                "INSERT INTO mcu (source_artifact_id, ref_name, family, line, "
                "package_name, pin_count, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (artifact, ref, "STM32TEST", "STM32TEST", "LQFP2", 2, "2026-07-23T00:00:00Z"),
            ).lastrowid
        )
    return conn, refs, mcu_ids


def _insert_pin(
    conn: sqlite3.Connection,
    mcu_id: int,
    position: str,
    name: str,
    electrical_class: str,
    *,
    signal: str | None = None,
) -> None:
    pin_id = conn.execute(
        "INSERT INTO mcu_package_pin (mcu_id, package_name, physical_pin_number, "
        "position_kind, canonical_pin_name, raw_pin_name, pin_type, electrical_class) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (mcu_id, "LQFP2", position, "numeric", name, name, electrical_class, electrical_class),
    ).lastrowid
    if signal:
        conn.execute(
            "INSERT INTO pin_function (mcu_package_pin_id, function_name, signal, io_modes) "
            "VALUES (?, ?, ?, ?)",
            (pin_id, signal, signal, "In/Out"),
        )
        conn.execute(
            "INSERT INTO pin_alternate_function "
            "(mcu_package_pin_id, af_index, signal, peripheral) VALUES (?, ?, ?, ?)",
            (pin_id, 1, signal, signal.split("_", 1)[0]),
        )


def test_safety_collision_requires_an_evidenced_rule():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "VSS", "ground")
    _insert_pin(conn, mcu_ids[1], "1", "VCAP_1", "vcap")
    conn.commit()

    blocked = compile_target_definition(conn, refs=refs, policy=_policy(), source_meta=_meta())
    pos1 = blocked["positions"][0]
    assert pos1["silicon_class"] == "safety_collision"
    assert pos1["board_action"] == "isolate"
    assert blocked["readiness"]["status"] == "blocked"
    ground = next(
        group
        for group in blocked["functional_foundation"]["groups"]
        if group["id"] == "ground-return"
    )
    assert ground["status"] == "partial"
    assert ground["unresolved_positions"] == ["1"]

    resolved = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            safety_rules=[
                {
                    "position": "1",
                    "action": "selectable",
                    "safe_default": "open",
                    "uses_channel": True,
                    "onehot_group": "collision-ground",
                    "evidence": ["TEST datasheet table 1"],
                }
            ]
        ),
        source_meta=_meta(),
    )
    pos1 = resolved["positions"][0]
    assert pos1["board_action"] == "selectable"
    assert resolved["channel_fabric"]["required_channels"] == 1
    assert resolved["channel_fabric"]["allocations"][0]["position"] == "1"
    assert resolved["readiness"]["status"] == "ready"
    assert resolved["functional_foundation"]["status"] == "complete"


def test_safety_branches_cover_each_identity_and_allocate_each_controlled_endpoint():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "VSS", "ground")
    _insert_pin(conn, mcu_ids[1], "1", "VCAP_1", "vcap")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            safety_rules=[
                {
                    "position": "1",
                    "action": "selectable",
                    "safe_default": "open",
                    "onehot_group": "position-1",
                    "evidence": ["TEST pin table"],
                    "branches": [
                        {
                            "id": "ground",
                            "identity_patterns": [r"ground"],
                            "action": "switched",
                            "net": "GROUND_BRANCH",
                        },
                        {
                            "id": "vcap",
                            "identity_patterns": [r"vcap"],
                            "action": "switched",
                            "net": "VCAP_BRANCH",
                        },
                    ],
                }
            ]
        ),
        source_meta=_meta(),
    )

    assert result["readiness"]["status"] == "ready"
    assert result["channel_fabric"]["required_channels"] == 2
    assert [row["branch_id"] for row in result["channel_fabric"]["allocations"]] == [
        "ground",
        "vcap",
    ]
    branches = result["safety_rules"][0]["branches"]
    assert branches[0]["matched_targets"] == ["STM32TESTA"]
    assert branches[1]["matched_targets"] == ["STM32TESTB"]


def test_uncovered_collision_identity_is_a_blocker():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "VSS", "ground")
    _insert_pin(conn, mcu_ids[1], "1", "VCAP_1", "vcap")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            safety_rules=[
                {
                    "position": "1",
                    "action": "selectable",
                    "safe_default": "open",
                    "evidence": ["TEST pin table"],
                    "branches": [
                        {
                            "id": "ground",
                            "identity_patterns": [r"ground"],
                            "action": "switched",
                        }
                    ],
                }
            ]
        ),
        source_meta=_meta(),
    )

    assert result["readiness"]["status"] == "blocked"
    assert any(
        "identity vcap has no safety branch" in item
        for item in result["readiness"]["blockers"]
    )


def test_family_variable_required_route_allocates_one_channel_per_endpoint():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SERVICE_TX")
    _insert_pin(conn, mcu_ids[0], "2", "PB0", "io")
    _insert_pin(conn, mcu_ids[1], "1", "PA0", "io")
    _insert_pin(conn, mcu_ids[1], "2", "PB0", "io", signal="SERVICE_TX")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": "service_tx",
                    "label": "Service TX",
                    "net": "SERVICE_TX",
                    "required": True,
                    "signal_patterns": [r"SERVICE_TX"],
                    "evidence": ["TEST datasheet table 2"],
                }
            ]
        ),
        source_meta=_meta(),
    )

    assert result["requirements"][0]["route_kind"] == "switched"
    assert result["channel_fabric"]["required_channels"] == 2
    allocations = result["channel_fabric"]["allocations"]
    assert [(row["reference"], row["channel"], row["register_bit"]) for row in allocations] == [
        ("U_ROUTE_1", 1, 0),
        ("U_ROUTE_1", 2, 1),
    ]
    assert {row["onehot_group"] for row in allocations} == {"service_tx"}


def test_optional_service_keeps_partial_routes_and_reports_group_coverage():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SERVICE_TX")
    _insert_pin(conn, mcu_ids[1], "1", "PA0", "io")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": "service_tx",
                    "label": "Service TX",
                    "net": "SERVICE_TX",
                    "required": False,
                    "category": "recovery",
                    "service_group": "service-uart",
                    "protocol": "UART",
                    "purposes": ["recovery", "data-access"],
                    "signal_patterns": [r"SERVICE_TX"],
                    "evidence": ["TEST capability table"],
                }
            ],
            service_groups=[
                {
                    "id": "service-uart",
                    "label": "Service UART",
                    "category": "recovery",
                    "protocol": "UART",
                    "required": False,
                    "claim_scope": "pin-capability",
                    "purposes": ["recovery", "data-access"],
                    "requirement_ids": ["service_tx"],
                    "evidence": ["TEST capability table"],
                }
            ],
        ),
        source_meta=_meta(),
    )

    requirement = result["requirements"][0]
    assert requirement["route_kind"] == "partial"
    assert requirement["implementation_kind"] == "direct"
    assert requirement["coverage_status"] == "partial"
    assert [route["ref"] for route in requirement["routes"]] == ["STM32TESTA"]
    group = result["service_groups"][0]
    assert group["status"] == "partial"
    assert group["complete_target_count"] == 1
    assert result["readiness"]["status"] == "ready"


def test_capability_only_routes_can_share_a_breakout_without_claiming_board_nets():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SHARED_SIGNAL")
    _insert_pin(conn, mcu_ids[1], "1", "PA0", "io", signal="SHARED_SIGNAL")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": req_id,
                    "label": req_id,
                    "net": req_id.upper(),
                    "required": False,
                    "implementation_required": False,
                    "signal_patterns": [r"SHARED_SIGNAL"],
                    "evidence": ["TEST capability table"],
                }
                for req_id in ("audit_a", "audit_b")
            ]
        ),
        source_meta=_meta(),
    )

    assert result["readiness"]["status"] == "ready"
    assert all(route["route_kind"] == "direct" for route in result["requirements"])
    position = result["positions"][0]
    assert position["board_action"] == "breakout"
    assert position["route_ids"] == []
    assert result["channel_fabric"]["required_channels"] == 0


def test_no_connect_pins_are_isolated_and_reported_as_a_functional_obligation():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "NC", "nc")
    _insert_pin(conn, mcu_ids[1], "1", "NC", "nc")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(),
        source_meta=_meta(),
    )

    position = result["positions"][0]
    assert position["silicon_class"] == "fixed_critical"
    assert position["board_action"] == "isolate"
    reserved = next(
        group
        for group in result["functional_foundation"]["groups"]
        if group["id"] == "reserved-no-connect"
    )
    assert reserved["status"] == "complete"
    assert reserved["resolved_target_count"] == 2


def test_safety_branch_can_make_a_target_specific_service_route_usable():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SERVICE_TX")
    _insert_pin(conn, mcu_ids[1], "1", "VSS", "ground")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": "service_tx",
                    "label": "Service TX",
                    "net": "SERVICE_TX",
                    "required": True,
                    "applies_to": {"refs": [refs[0]]},
                    "signal_patterns": [r"SERVICE_TX"],
                    "evidence": ["TEST signal table"],
                }
            ],
            safety_rules=[
                {
                    "position": "1",
                    "action": "selectable",
                    "safe_default": "open",
                    "evidence": ["TEST pin table"],
                    "branches": [
                        {
                            "id": "gpio",
                            "identity_patterns": [r"PA0"],
                            "action": "breakout",
                            "net": "TARGET_PIN_1",
                            "uses_channel": False,
                        },
                        {
                            "id": "ground",
                            "identity_patterns": [r"ground"],
                            "action": "switched",
                            "net": "GROUND",
                            "uses_channel": True,
                        },
                    ],
                }
            ],
        ),
        source_meta=_meta(),
    )

    requirement = result["requirements"][0]
    assert requirement["route_kind"] == "direct"
    assert requirement["coverage_status"] == "complete"
    assert requirement["blocked_targets"] == []
    assert requirement["routes"][0]["usable"] is True
    assert requirement["routes"][0]["safety_branch"] == "gpio"
    assert result["positions"][0]["board_action"] == "selectable"
    assert result["readiness"]["status"] == "ready"


def test_claim_scope_is_strict_and_sensitive_pin_only_services_warn():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SERVICE_TX")
    _insert_pin(conn, mcu_ids[1], "1", "PA0", "io", signal="SERVICE_TX")
    conn.commit()

    with pytest.raises(ValueError, match="claim_scope"):
        compile_target_definition(
            conn,
            refs=refs,
            policy=_policy(
                requirements=[
                    {
                        "id": "service_tx",
                        "label": "Service TX",
                        "net": "SERVICE_TX",
                        "required": False,
                        "claim_scope": "probably-supported",
                        "signal_patterns": [r"SERVICE_TX"],
                        "evidence": ["TEST table"],
                    }
                ]
            ),
            source_meta=_meta(),
        )

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": "service_tx",
                    "label": "Service TX",
                    "net": "SERVICE_TX",
                    "required": False,
                    "signal_patterns": [r"SERVICE_TX"],
                    "evidence": ["TEST table"],
                }
            ],
            service_groups=[
                {
                    "id": "recovery-uart",
                    "label": "Recovery UART",
                    "category": "recovery",
                    "required": False,
                    "claim_scope": "pin-capability",
                    "purposes": ["recovery", "data-access"],
                    "requirement_ids": ["service_tx"],
                    "evidence": ["TEST table"],
                }
            ],
        ),
        source_meta=_meta(),
    )
    assert any(
        "target-specific data-access/recovery support is unproven" in warning
        for warning in result["readiness"]["warnings"]
    )


def test_requirement_applicability_separates_unsupported_from_missing():
    conn, refs, mcu_ids = _tiny_connection()
    _insert_pin(conn, mcu_ids[0], "1", "PA0", "io", signal="SERVICE_TX")
    _insert_pin(conn, mcu_ids[1], "1", "PA0", "io")
    conn.commit()

    result = compile_target_definition(
        conn,
        refs=refs,
        policy=_policy(
            requirements=[
                {
                    "id": "service_tx",
                    "label": "Service TX",
                    "net": "SERVICE_TX",
                    "required": True,
                    "applies_to": {"refs": ["STM32TESTA"]},
                    "signal_patterns": [r"SERVICE_TX"],
                    "evidence": ["TEST external applicability table"],
                }
            ]
        ),
        source_meta=_meta(),
    )

    requirement = result["requirements"][0]
    assert requirement["coverage_status"] == "complete"
    assert requirement["missing_targets"] == []
    assert requirement["not_applicable_targets"] == ["STM32TESTB"]
    assert result["readiness"]["status"] == "ready"


def test_definition_digest_is_deterministic(stm_conn, stm_refs):
    args = {
        "refs": [stm_refs["mcu1"], stm_refs["mcu1b"]],
        "policy": _policy(),
        "source_meta": _meta(),
    }
    first = compile_target_definition(stm_conn, **args)
    second = compile_target_definition(stm_conn, **args)
    assert first["artifact_digest"] == second["artifact_digest"]
    assert first == second
    assert first["provenance"]["source_sha256"] == "abc123"
