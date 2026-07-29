"""Scalable, implementation-neutral socket support synthesis.

The target-definition compiler remains the detailed silicon/evidence authority.
This module compacts that evidence into the hardware answer an engineer needs:
unique electrical modes, reusable support-cell archetypes, target cohorts, and
safe control states. Target membership is carried as bitsets so the result
scales with unique behavior rather than repeating one record per target.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

from stockroom.stm.families import FAMILY_ELECTRICAL, FAMILY_NOT_5V
from stockroom.stm.target_definition import compile_target_definition

SOCKET_SOLUTION_COMPILER_REV = 3


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _ordered_unique(values) -> list:
    return list(dict.fromkeys(value for value in values if value not in (None, "")))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "mode"


def _target_mask(indices: list[int]) -> str:
    bits = 0
    for index in indices:
        bits |= 1 << index
    return f"0x{bits:x}"


def _mask_contains(mask: str, index: int) -> bool:
    try:
        return bool(int(mask, 16) & (1 << index))
    except (TypeError, ValueError):
        return False


def _mode_for_pin(pin: dict | None) -> dict[str, Any]:
    if pin is None:
        return {
            "id": "absent",
            "label": "Position Absent",
            "kind": "absent",
            "conductive": False,
            "endpoint": "none",
        }

    electrical = str(pin.get("electrical_class", "") or "").lower()
    identity = str(pin.get("critical_identity", "") or "")
    canonical = str(pin.get("canonical_pin_name", "") or "")

    if electrical == "io" and not identity:
        return {
            "id": "universal-io",
            "label": "Universal I/O",
            "kind": "signal",
            "conductive": True,
            "endpoint": "universal-lane",
        }

    identity = identity or canonical or electrical or "unknown"
    normalized = identity.lower()
    labels = {
        "ground": "Ground Return",
        "vcap": "Core Regulator",
        "reset": "Reset Control",
        "boot": "Boot Control",
        "no-connect": "Reserved Open",
    }
    if normalized.startswith("power:"):
        label = normalized.removeprefix("power:").upper() + " Supply"
    elif normalized.startswith("power-control:"):
        label = normalized.removeprefix("power-control:").replace("-", " ").title()
    elif normalized.startswith("regulator-control:"):
        label = normalized.removeprefix("regulator-control:").replace("-", " ").title()
    else:
        label = labels.get(normalized, identity.replace(":", " ").replace("-", " ").title())

    conductive = normalized != "no-connect"
    return {
        "id": _slug(identity),
        "label": label,
        "kind": "reserved" if not conductive else "critical",
        "conductive": conductive,
        "endpoint": "none" if not conductive else f"fixed:{normalized}",
    }


def _electrical_envelope(pins: list[dict]) -> dict[str, Any]:
    families = sorted({str(pin.get("family", "")) for pin in pins if pin.get("family")})
    limits = [FAMILY_ELECTRICAL[family] for family in families if family in FAMILY_ELECTRICAL]
    canonical_names = {str(pin.get("canonical_pin_name", "") or "") for pin in pins}
    five_v_by_family = {
        family: all(
            not name.startswith("P") or name not in FAMILY_NOT_5V.get(family, set())
            for name in canonical_names
        )
        for family in families
    }
    if not limits:
        return {
            "authority": "target-documentation-required",
            "families": families,
            "operating_v": None,
            "per_pin_current_ma": None,
            "injection_current_ma": None,
            "five_v_tolerant": None,
            "citations": [],
        }

    operating_min = max(float(limit["vdd_v"][0]) for limit in limits)
    operating_max = min(float(limit["vdd_v"][1]) for limit in limits)
    return {
        "authority": "family-datasheet-conservative-intersection",
        "families": families,
        "operating_v": [operating_min, operating_max],
        "per_pin_current_ma": min(int(limit["io_ma"]) for limit in limits),
        "injection_current_ma": min(int(limit["inj_ma"]) for limit in limits),
        "five_v_tolerant": all(five_v_by_family.values()) if families else None,
        "five_v_by_family": five_v_by_family,
        "citations": sorted({str(limit["ds"]) for limit in limits}),
    }


def _topology_resolution(modes: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = {mode["kind"] for mode in modes}
    conductive = [mode for mode in modes if mode["conductive"]]
    critical_ids = {mode["id"] for mode in conductive if mode["kind"] == "critical"}
    signal_present = "signal" in kinds
    passive_control_roles = {"reset", "boot"}
    analog_endpoints = {
        "fixed:power:vdda",
        "fixed:power:vref",
        "fixed:power:vref+",
    }

    if kinds == {"signal"}:
        return {
            "cell_type": "universal-io",
            "controlled": False,
            "shared_endpoint": None,
            "reason": "Every selected target uses this position as software-defined I/O.",
            "network_requirements": [],
            "validation_checks": [],
        }
    if kinds <= {"reserved", "absent"}:
        cell_type = "reserved-open" if "reserved" in kinds else "optional-absent"
        return {
            "cell_type": cell_type,
            "controlled": False,
            "shared_endpoint": None,
            "reason": "No selected target requires a conductive common path.",
            "network_requirements": [],
            "validation_checks": [],
        }
    if (
        signal_present
        and critical_ids
        and critical_ids <= passive_control_roles
        and kinds <= {"signal", "critical", "absent", "reserved"}
    ):
        return {
            "cell_type": "passive-compatible-lane",
            "controlled": False,
            "shared_endpoint": "universal-lane",
            "reason": (
                "Reset or boot control can share the signal lane when bias is weak, "
                "control is open-drain, and every selected target passes the loading proof."
            ),
            "network_requirements": [
                "one bidirectional observation and breakout lane",
                "weak bias only; no hard rail drive",
                "open-drain external control for reset or strap assertion",
                "any capacitive load must be optional or isolated",
            ],
            "validation_checks": [
                "prove bias current against every target output-low limit",
                "prove logic-high margin and rise time across every target",
                "prove reset or boot pulse width and power-up state",
                "prove optional capacitance does not block the GPIO bandwidth requirement",
            ],
        }
    if (
        not signal_present
        and len(conductive) > 1
        and {mode["endpoint"] for mode in conductive} <= analog_endpoints
    ):
        return {
            "cell_type": "shared-analog-network",
            "controlled": False,
            "shared_endpoint": "fixed:power:analog-common",
            "reason": (
                "The alternate identities are analog-supply or reference inputs that may "
                "share one filtered analog rail when exact target documentation permits it."
            ),
            "network_requirements": [
                "one filtered analog supply rail",
                "per-position decoupling footprint",
                "no independent external reference unless the common tie is opened",
            ],
            "validation_checks": [
                "prove every target permits its reference input tied to the analog supply",
                "prove the common voltage range across every target",
                "prove decoupling, noise, and startup requirements for every identity",
            ],
        }
    if "absent" in kinds:
        cell_type = "selected-roles"
    elif len(conductive) == 1 and len(modes) == 1:
        cell_type = "fixed-network"
    elif signal_present:
        cell_type = "selected-roles"
    else:
        cell_type = "critical-role-island"
    return {
        "cell_type": cell_type,
        "controlled": cell_type in {"selected-roles", "critical-role-island"},
        "shared_endpoint": None,
        "reason": (
            "Electrically incompatible roles remain on mutually exclusive, default-open branches."
            if cell_type in {"selected-roles", "critical-role-island"}
            else "Every selected target requires the same fixed electrical network."
        ),
        "network_requirements": [],
        "validation_checks": [],
    }


def _hazard_contract(
    modes: list[dict[str, Any]], *, controlled: bool, proof_required: bool
) -> dict[str, Any]:
    conductive = [mode for mode in modes if mode["conductive"]]
    endpoints = {str(mode["endpoint"]) for mode in conductive}
    mode_ids = {str(mode["id"]) for mode in modes}
    has_signal = any(mode["kind"] == "signal" for mode in modes)
    has_ground = "fixed:ground" in endpoints
    power_endpoints = {endpoint for endpoint in endpoints if endpoint.startswith("fixed:power:")}
    regulator_ids = {
        mode_id
        for mode_id in mode_ids
        if mode_id == "vcap"
        or mode_id.startswith("regulator-control")
        or mode_id.startswith("power-control")
    }
    has_reserved = any(mode["kind"] in {"reserved", "absent"} for mode in modes)

    if controlled and has_ground and (power_endpoints or has_signal):
        level = "critical"
        category = "power-ground-signal"
        label = "Power, Ground, And Signal Collision"
        reason = "A wrong state can short a rail or drive an MCU pin against a supply return."
    elif controlled and power_endpoints and (has_signal or len(power_endpoints) > 1):
        level = "critical"
        category = "power-domain"
        label = "Power-Domain Collision"
        reason = "A wrong state can back-power the target or connect the wrong supply domain."
    elif controlled and regulator_ids:
        level = "critical"
        category = "regulator"
        label = "Regulator-Network Collision"
        reason = (
            "The internal regulator pin requires a target-specific external network and "
            "must never share an energized branch."
        )
    elif controlled and has_reserved:
        level = "high"
        category = "reserved-isolation"
        label = "Reserved-Pin Isolation"
        reason = "At least one target requires this physical position to remain open."
    elif controlled:
        level = "high"
        category = "exclusive-roles"
        label = "Mutually Exclusive Electrical Roles"
        reason = "Only the branch declared for the installed target may conduct."
    elif proof_required:
        level = "medium"
        category = "verification"
        label = "Electrical Verification Required"
        reason = "The common network is usable only after its loading envelope is proven."
    else:
        level = "none"
        category = "none"
        label = "No Cross-Target Hazard"
        reason = "All selected targets use a compatible fixed or signal network."

    rank = {"none": 0, "medium": 1, "high": 2, "critical": 3}[level]
    return {
        "level": level,
        "rank": rank,
        "category": category,
        "label": label,
        "reason": reason,
    }


def _branch_plane(mode: dict[str, Any]) -> str:
    endpoint = str(mode["endpoint"])
    mode_id = str(mode["id"])
    if not mode["conductive"]:
        return "open"
    if endpoint == "fixed:ground":
        return "ground-return"
    if endpoint.startswith("fixed:power:"):
        return "power-source"
    if mode_id == "vcap" or mode_id.startswith("regulator-control"):
        return "regulator-network"
    if mode_id in {"reset", "boot"}:
        return "open-drain-control"
    if endpoint == "universal-lane":
        return "signal"
    return "dedicated-network"


def _position_cell_contract(
    modes: list[dict[str, Any]],
    resolution: dict[str, Any],
    hazard: dict[str, Any],
) -> dict[str, Any]:
    controlled = bool(resolution["controlled"])
    planes = _ordered_unique(_branch_plane(mode) for mode in modes)
    if controlled:
        architecture = "fail-closed-universal-position-cell"
        selection = "declared-target-profile"
        default_state = "all-branches-open"
        mandatory_features = [
            "hardware-enforced one-hot branch selection",
            "all branch controls default inactive without controller power",
            "break-before-make on every state transition",
            "branch-state readback before target power enable",
            "fault detection forces every branch open",
            "target profile is declared and locked before any target rail is enabled",
            "power and ground branches include backfeed isolation",
            "power branches include current limiting and controlled precharge",
            "signal branches are high impedance while unselected or unpowered",
        ]
        sequence = [
            "hold every target-facing source and return branch open",
            "load and verify the exact target cohort",
            "apply the one-hot position configuration",
            "read back every controlled branch",
            "enable ground returns before source rails",
            "enable source rails with current-limited precharge",
            "release reset and signal access only after rail validation",
        ]
    else:
        architecture = (
            "passive-common-network" if resolution["shared_endpoint"] else "fixed-or-signal-network"
        )
        selection = "not-required"
        default_state = "connected"
        mandatory_features = [
            "network remains within every selected target electrical envelope",
            "unpowered target cannot be back-powered through the network",
        ]
        sequence = ["no target-specific branch state is required"]

    plane_requirements = {
        "ground-return": [
            "low-impedance bidirectional return path",
            "never enabled against a source or signal branch",
        ],
        "power-source": [
            "target-rated source with current limit and precharge",
            "reverse-current and unpowered-target isolation",
            "rail-good feedback before dependent branches close",
        ],
        "signal": [
            "bidirectional high-impedance signal path",
            "voltage, injection-current, bandwidth, and power-off limits enforced",
        ],
        "regulator-network": [
            "isolated target-specific capacitor or regulator support network",
            "discharge to a verified safe state before profile changes",
        ],
        "open-drain-control": [
            "weak target-compatible bias",
            "open-drain assertion with a high-impedance released state",
        ],
        "dedicated-network": [
            "electrically isolated target-specific support network",
            "no conductive path while unselected",
        ],
        "open": ["no conductive path in every operating and fault state"],
    }
    return {
        "architecture": architecture,
        "selection_authority": selection,
        "default_state": default_state,
        "planes": [
            {
                "id": plane,
                "requirements": plane_requirements.get(
                    plane, ["target-specific isolated support network"]
                ),
            }
            for plane in planes
        ],
        "mandatory_features": mandatory_features,
        "power_sequence": sequence,
        "failure_response": "force-all-branches-open",
        "hazard": hazard,
    }


def _requirement_coverage(
    definition: dict,
    target_refs: list[str],
    position_contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    target_set = set(target_refs)
    target_number = {ref: index for index, ref in enumerate(target_refs)}
    position_by_id = {str(position["position"]): position for position in position_contracts}
    coverage: list[dict[str, Any]] = []
    for requirement in definition.get("requirements", []) or []:
        if not requirement.get("required"):
            continue
        source_missing = sorted(
            {str(ref) for ref in requirement.get("missing_targets", []) or [] if ref}
        )
        available = target_set - set(source_missing)
        routed: set[str] = set()
        for route in requirement.get("routes", []) or []:
            ref = str(route.get("ref", ""))
            position = position_by_id.get(str(route.get("position", "")))
            if not ref or ref not in target_number or position is None:
                continue
            if any(
                _mask_contains(str(mode["target_mask"]), target_number[ref])
                for mode in position["modes"]
            ):
                routed.add(ref)
        architecture_missing = sorted(available - routed)
        coverage.append(
            {
                "id": str(requirement.get("id", "")),
                "label": str(requirement.get("label") or requirement.get("id") or "Requirement"),
                "covered_targets": len(available & routed),
                "available_target_count": len(available),
                "target_count": len(target_refs),
                "coverage_percentage": (
                    round((len(available & routed) / len(available)) * 100, 3) if available else 100
                ),
                "silicon_available_percentage": (
                    round((len(available) / len(target_refs)) * 100, 3) if target_refs else 0
                ),
                "missing_targets": source_missing,
                "architecture_missing_targets": architecture_missing,
                "status": "pass" if not architecture_missing else "fail",
            }
        )
    return coverage


def _cell_label(cell_type: str, mode_labels: list[str]) -> str:
    labels = {
        "universal-io": "Universal I/O Lane",
        "reserved-open": "Reserved Open",
        "optional-absent": "Optional Position",
        "fixed-network": f"Fixed {mode_labels[0]}" if mode_labels else "Fixed Network",
        "critical-role-island": "Isolated Critical Roles",
        "selected-roles": "Selected Socket Roles",
        "passive-compatible-lane": "Passive-Compatible Control Lane",
        "shared-analog-network": "Shared Analog Supply Network",
    }
    return labels[cell_type]


def _support_signature(position: dict) -> str:
    value = {
        "cell_type": position["cell_type"],
        "modes": [
            {
                "id": mode["id"],
                "kind": mode["kind"],
                "conductive": mode["conductive"],
                "endpoint": mode["endpoint"],
            }
            for mode in position["modes"]
        ],
        "safe_default": position["safe_default"],
        "controlled": position["controlled"],
        "hazard_category": position["hazard_contract"]["category"],
        "cell_architecture": position["cell_contract"]["architecture"],
    }
    return _digest(value)[:16]


def compile_socket_solution_from_definition(definition: dict) -> dict:
    targets = list(definition.get("scope", {}).get("targets", []) or [])
    target_refs = [str(target["ref"]) for target in targets]
    target_index = {ref: index for index, ref in enumerate(target_refs)}
    total_targets = len(target_refs)

    position_contracts: list[dict[str, Any]] = []
    target_position_modes: dict[str, list[str]] = {ref: [] for ref in target_refs}
    controlled_branches = 0
    universal_lanes = 0
    proofs = []

    strategy_by_position = {
        str(strategy["position"]): strategy
        for strategy in definition.get("universalization", {}).get("strategies", [])
    }

    for source_position in definition.get("positions", []):
        position_id = str(source_position["position"])
        pins_by_ref = {str(pin["ref"]): pin for pin in source_position.get("per_target", [])}
        mode_members: dict[str, list[int]] = defaultdict(list)
        mode_pins: dict[str, list[dict]] = defaultdict(list)
        mode_templates: dict[str, dict[str, Any]] = {}

        for ref in target_refs:
            pin = pins_by_ref.get(ref)
            mode = _mode_for_pin(pin)
            mode_id = mode["id"]
            mode_templates[mode_id] = mode
            mode_members[mode_id].append(target_index[ref])
            if pin is not None:
                mode_pins[mode_id].append(pin)
            target_position_modes[ref].append(mode_id)

        modes: list[dict[str, Any]] = []
        for mode_id in sorted(
            mode_templates,
            key=lambda key: (
                -len(mode_members[key]),
                mode_templates[key]["label"],
            ),
        ):
            template = mode_templates[mode_id]
            pins = mode_pins[mode_id]
            functions = _ordered_unique(
                signal
                for pin in pins
                for signal in [
                    *(pin.get("functions", []) or []),
                    *(
                        option.get("signal", "")
                        for option in pin.get("alternate_functions", []) or []
                    ),
                ]
            )
            members = mode_members[mode_id]
            modes.append(
                {
                    **template,
                    "target_mask": _target_mask(members),
                    "target_count": len(members),
                    "percentage": (
                        round((len(members) / total_targets) * 100, 3) if total_targets else 0
                    ),
                    "target_examples": [target_refs[index] for index in members[:8]],
                    "functions": functions,
                    "access_tags": sorted(
                        {str(tag) for pin in pins for tag in pin.get("access_tags", []) or []}
                    ),
                    "electrical_envelope": _electrical_envelope(pins),
                }
            )

        resolution = _topology_resolution(modes)
        cell_type = resolution["cell_type"]
        controlled = bool(resolution["controlled"])
        branches: list[dict[str, Any]] = []
        shared_endpoint = resolution["shared_endpoint"]
        if shared_endpoint:
            conductive_members = sorted(
                index for mode in modes if mode["conductive"] for index in mode_members[mode["id"]]
            )
            branches.append(
                {
                    "id": f"position-{_slug(position_id)}-shared-network",
                    "mode_id": "shared-network",
                    "label": _cell_label(cell_type, [str(mode["label"]) for mode in modes]),
                    "endpoint": shared_endpoint,
                    "target_mask": _target_mask(conductive_members),
                    "controlled": False,
                    "default_state": "connected",
                    "direction": "bidirectional",
                    "break_before_make": False,
                    "plane": "dedicated-network",
                    "electrical_envelope": _electrical_envelope(
                        [pin for pins in mode_pins.values() for pin in pins]
                    ),
                }
            )
        else:
            for mode in modes:
                if not mode["conductive"]:
                    continue
                branch_id = f"position-{_slug(position_id)}-{mode['id']}"
                branches.append(
                    {
                        "id": branch_id,
                        "mode_id": mode["id"],
                        "label": mode["label"],
                        "endpoint": mode["endpoint"],
                        "target_mask": mode["target_mask"],
                        "controlled": controlled,
                        "default_state": "open" if controlled else "connected",
                        "direction": "bidirectional",
                        "break_before_make": controlled,
                        "plane": _branch_plane(mode),
                        "electrical_envelope": mode["electrical_envelope"],
                    }
                )
                if controlled:
                    controlled_branches += 1

        if any(mode["kind"] == "signal" for mode in modes):
            universal_lanes += 1

        strategy = strategy_by_position.get(position_id, {})
        validation = dict(strategy.get("validation", {}) or {})
        required_checks = _ordered_unique(
            [
                *list(resolution["validation_checks"]),
                *list(validation.get("required_checks", []) or []),
            ]
        )
        if required_checks or validation.get("status") in {
            "required",
            "policy-evidence-required",
        }:
            proofs.append(
                {
                    "position": position_id,
                    "status": "needed",
                    "checks": required_checks,
                    "failure_action": validation.get(
                        "failure_action",
                        (
                            "replace-common-network-with-default-open-isolation"
                            if resolution["shared_endpoint"]
                            else "keep-independent-paths-open"
                        ),
                    ),
                }
            )

        hazard_contract = _hazard_contract(
            modes,
            controlled=controlled,
            proof_required=bool(required_checks),
        )
        cell_contract = _position_cell_contract(modes, resolution, hazard_contract)
        agreement_count = max((mode["target_count"] for mode in modes), default=0)
        contract = {
            "position": position_id,
            "position_kind": source_position.get("position_kind", "numeric"),
            "lqfp_side": source_position.get("lqfp_side"),
            "bga_row": source_position.get("bga_row"),
            "bga_col": source_position.get("bga_col"),
            "cell_type": cell_type,
            "cell_label": _cell_label(cell_type, [str(mode["label"]) for mode in modes]),
            "solution_reason": resolution["reason"],
            "network_requirements": list(resolution["network_requirements"]),
            "validation_checks": required_checks,
            "cell_contract": cell_contract,
            "hazard_contract": hazard_contract,
            "controlled": controlled,
            "safe_default": "open" if controlled else "connected",
            "observation_node": any(mode["kind"] == "signal" for mode in modes),
            "universal_lane": any(mode["kind"] == "signal" for mode in modes),
            "modes": modes,
            "branches": branches,
            "mode_count": len(modes),
            "agreement_count": agreement_count,
            "agreement_percentage": (
                round((agreement_count / total_targets) * 100, 3) if total_targets else 0
            ),
            "support_cell_id": "",
            "hazard": source_position.get("hazard", ""),
        }
        position_contracts.append(contract)

    grouped_cells: dict[str, list[dict]] = defaultdict(list)
    for position in position_contracts:
        signature = _support_signature(position)
        grouped_cells[signature].append(position)

    support_cells: list[dict[str, Any]] = []
    for index, (signature, positions) in enumerate(
        sorted(grouped_cells.items(), key=lambda item: item[0]), start=1
    ):
        first = positions[0]
        cell_id = f"cell-{index:03d}"
        for position in positions:
            position["support_cell_id"] = cell_id
        support_cells.append(
            {
                "id": cell_id,
                "signature": signature,
                "type": first["cell_type"],
                "label": first["cell_label"],
                "positions": [position["position"] for position in positions],
                "position_count": len(positions),
                "mode_count": first["mode_count"],
                "controlled": first["controlled"],
                "safe_default": first["safe_default"],
                "hazard_contract": first["hazard_contract"],
                "cell_contract": first["cell_contract"],
                "branch_pattern": [
                    {
                        "mode_id": branch["mode_id"],
                        "label": branch["label"],
                        "endpoint": branch["endpoint"],
                        "controlled": branch["controlled"],
                        "plane": branch["plane"],
                    }
                    for branch in first["branches"]
                ],
                "implementation_capabilities": {
                    "default_open": first["controlled"],
                    "hardware_reset": first["controlled"],
                    "readback": first["controlled"],
                    "break_before_make": first["controlled"],
                    "bidirectional": bool(first["branches"]),
                    "passive_conditioning": (first["cell_type"] == "passive-compatible-lane"),
                    "shared_supply": (first["cell_type"] == "shared-analog-network"),
                    "proof_required": bool(first["validation_checks"]),
                },
            }
        )

    cohort_groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for ref in target_refs:
        cohort_groups[tuple(target_position_modes[ref])].append(ref)

    cohorts: list[dict[str, Any]] = []
    for index, (signature, refs) in enumerate(
        sorted(cohort_groups.items(), key=lambda item: (-len(item[1]), item[1][0])),
        start=1,
    ):
        member_indices = [target_index[ref] for ref in refs]
        states = {}
        for position, mode_id in zip(position_contracts, signature):
            if not position["controlled"]:
                continue
            branch = next(
                (branch for branch in position["branches"] if branch["mode_id"] == mode_id),
                None,
            )
            states[position["position"]] = branch["id"] if branch else "open"
        families = sorted(
            {
                str(targets[target_index[ref]].get("family", ""))
                for ref in refs
                if targets[target_index[ref]].get("family")
            }
        )
        cohorts.append(
            {
                "id": f"cohort-{index:03d}",
                "target_mask": _target_mask(member_indices),
                "target_count": len(refs),
                "percentage": (round((len(refs) / total_targets) * 100, 3) if total_targets else 0),
                "families": families,
                "target_examples": refs[:8],
                "configuration": states,
            }
        )

    configuration_errors: list[dict[str, str]] = []
    supported_targets = 0
    for target_number, ref in enumerate(target_refs):
        matching_cohorts = [
            cohort
            for cohort in cohorts
            if _mask_contains(str(cohort["target_mask"]), target_number)
        ]
        target_errors: list[dict[str, str]] = []
        if len(matching_cohorts) != 1:
            target_errors.append(
                {
                    "target": ref,
                    "position": "",
                    "reason": (
                        f"target belongs to {len(matching_cohorts)} configuration cohorts; "
                        "exactly one is required"
                    ),
                }
            )
        cohort = matching_cohorts[0] if len(matching_cohorts) == 1 else None
        for position in position_contracts:
            modes = [
                mode
                for mode in position["modes"]
                if _mask_contains(str(mode["target_mask"]), target_number)
            ]
            if len(modes) != 1:
                target_errors.append(
                    {
                        "target": ref,
                        "position": str(position["position"]),
                        "reason": (
                            f"target resolves to {len(modes)} electrical modes; "
                            "exactly one is required"
                        ),
                    }
                )
                continue
            mode = modes[0]
            if position["controlled"] and cohort is not None:
                state = str(cohort["configuration"].get(position["position"], ""))
                branch = next(
                    (branch for branch in position["branches"] if branch["mode_id"] == mode["id"]),
                    None,
                )
                expected_state = branch["id"] if branch is not None else "open"
                if state != expected_state:
                    target_errors.append(
                        {
                            "target": ref,
                            "position": str(position["position"]),
                            "reason": (
                                f"cohort selects {state or 'no state'} but target requires "
                                f"{expected_state}"
                            ),
                        }
                    )
            elif mode["conductive"] and not position["branches"]:
                target_errors.append(
                    {
                        "target": ref,
                        "position": str(position["position"]),
                        "reason": "conductive mode has no physical network",
                    }
                )
        if target_errors:
            configuration_errors.extend(target_errors)
        else:
            supported_targets += 1

    position_count = len(position_contracts)
    configurable_positions = sum(bool(position["controlled"]) for position in position_contracts)
    direct_positions = position_count - configurable_positions
    critical_positions = sum(
        any(mode["kind"] == "critical" for mode in position["modes"])
        for position in position_contracts
    )
    naive_branches = sum(
        mode["target_count"]
        for position in position_contracts
        if position["controlled"]
        for mode in position["modes"]
        if mode["conductive"]
    )
    shared_savings = (1 - (controlled_branches / naive_branches)) * 100 if naive_branches else 100.0
    critical_hazard_positions = sum(
        position["hazard_contract"]["level"] == "critical" for position in position_contracts
    )
    high_hazard_positions = sum(
        position["hazard_contract"]["level"] == "high" for position in position_contracts
    )
    proof_positions = {str(proof["position"]) for proof in proofs}
    zero_omission = bool(target_refs) and supported_targets == total_targets
    required_coverage = _requirement_coverage(definition, target_refs, position_contracts)
    incomplete_required = [
        requirement for requirement in required_coverage if requirement["status"] != "pass"
    ]

    debug_positions = {
        position["position"]
        for position in position_contracts
        if any(
            tag.lower() in {"swdio", "swclk"}
            for mode in position["modes"]
            for tag in mode["access_tags"]
        )
    }
    declared_target_required = any(
        position["controlled"] and position["hazard_contract"]["level"] == "critical"
        for position in position_contracts
    )
    automatic_bootstrap = (
        not declared_target_required
        and definition.get("functional_foundation", {}).get("status") == "complete"
        and len(debug_positions) >= 2
    )
    solution_status = (
        "impossible"
        if not target_refs or not position_contracts or not zero_omission
        else "conditional"
        if definition.get("readiness", {}).get("blockers") or proofs or incomplete_required
        else "solved"
    )
    closure_gates = [
        {
            "id": "target-coverage",
            "label": "Target Coverage",
            "status": "pass" if zero_omission else "fail",
            "value": f"{supported_targets}/{total_targets}",
            "detail": (
                "Every selected MCU resolves to one complete physical configuration."
                if zero_omission
                else "At least one selected MCU has an incomplete physical configuration."
            ),
        },
        {
            "id": "configuration-integrity",
            "label": "Configuration Integrity",
            "status": "pass" if not configuration_errors else "fail",
            "value": "0 Errors"
            if not configuration_errors
            else f"{len(configuration_errors)} Errors",
            "detail": (
                "Every target belongs to one target profile and every controlled position "
                "selects exactly its required branch."
            ),
        },
        {
            "id": "safe-before-power",
            "label": "Safe Before Power",
            "status": "pass",
            "value": (
                "Declared Target Required"
                if declared_target_required
                else "Automatic Bootstrap Available"
            ),
            "detail": (
                "All configurable branches default open. The exact target profile must be "
                "loaded, applied, and read back before target power is enabled."
                if declared_target_required
                else "The common run/debug foundation is available before target-specific "
                "branches are applied."
            ),
        },
        {
            "id": "required-access",
            "label": "Required Access",
            "status": "pass" if not incomplete_required else "fail",
            "value": (
                f"{len(required_coverage)}/{len(required_coverage)} Complete"
                if not incomplete_required
                else f"{len(required_coverage) - len(incomplete_required)}/"
                f"{len(required_coverage)} Complete"
            ),
            "detail": (
                "Every required run, reset, boot, or debug function exposed by the "
                "selected silicon has a usable socket route."
                if not incomplete_required
                else "The socket architecture omits one or more available required routes."
            ),
        },
        {
            "id": "electrical-verification",
            "label": "Electrical Verification",
            "status": "pass" if not proofs else "open",
            "value": "Closed" if not proofs else f"{len(proof_positions)} Positions Open",
            "detail": (
                "All common-network electrical checks are closed."
                if not proofs
                else "The architecture covers every target, but these position contracts "
                "still need exact electrical evidence."
            ),
        },
    ]

    solution = {
        "format": "stm-socket-solution/1",
        "compiler_rev": SOCKET_SOLUTION_COMPILER_REV,
        "artifact_digest": "",
        "source_definition_digest": definition.get("artifact_digest", ""),
        "scope": {
            **dict(definition.get("scope", {}) or {}),
            "target_index": [
                {
                    "index": index,
                    "ref": target["ref"],
                    "family": target.get("family", ""),
                    "line": target.get("line", ""),
                }
                for index, target in enumerate(targets)
            ],
        },
        "provenance": {
            **dict(definition.get("provenance", {}) or {}),
            "source_definition_format": definition.get("format", ""),
            "source_definition_compiler_rev": definition.get("compiler_rev", 0),
        },
        "status": {
            "solution": solution_status,
            "evidence": "needs-source" if proofs or incomplete_required else "complete",
            "bootstrap": ("automatic" if automatic_bootstrap else "requires-declared-target"),
            "blockers": [
                *list(definition.get("readiness", {}).get("blockers", []) or []),
                *[
                    (
                        f"{requirement['label']} has no socket route on "
                        f"{len(requirement['architecture_missing_targets'])} "
                        "selected targets"
                    )
                    for requirement in incomplete_required
                ],
                *[
                    (
                        f"{error['target']} position {error['position'] or 'scope'}: "
                        f"{error['reason']}"
                    )
                    for error in configuration_errors[:50]
                ],
            ],
            "warnings": list(definition.get("readiness", {}).get("warnings", []) or []),
        },
        "closure": {
            "verdict": ("architecture-complete" if zero_omission else "unsupported"),
            "release": (
                "ready"
                if all(gate["status"] == "pass" for gate in closure_gates)
                else "verification-open"
            ),
            "zero_omission": zero_omission,
            "supported_target_count": supported_targets,
            "unsupported_target_count": total_targets - supported_targets,
            "target_coverage_percentage": (
                round((supported_targets / total_targets) * 100, 3) if total_targets else 0
            ),
            "gates": closure_gates,
            "required_requirement_coverage": required_coverage,
            "configuration_errors": configuration_errors[:200],
        },
        "summary": {
            "target_count": total_targets,
            "target_cohort_count": len(cohorts),
            "position_count": position_count,
            "support_cell_count": len(support_cells),
            "direct_positions": direct_positions,
            "configurable_positions": configurable_positions,
            "critical_positions": critical_positions,
            "universal_lanes": universal_lanes,
            "observation_nodes": universal_lanes,
            "controlled_branches": controlled_branches,
            "critical_hazard_positions": critical_hazard_positions,
            "high_hazard_positions": high_hazard_positions,
            "proof_open_positions": len(proof_positions),
            "supported_targets": supported_targets,
            "direct_percentage": (
                round((direct_positions / position_count) * 100, 3) if position_count else 0
            ),
            "configurable_percentage": (
                round((configurable_positions / position_count) * 100, 3) if position_count else 0
            ),
            "shared_route_savings_percentage": round(shared_savings, 3),
        },
        "safe_state_contract": {
            "unknown_target": "all-controlled-branches-open",
            "controller_startup": "all-controlled-branches-open",
            "controller_reset": "all-controlled-branches-open",
            "power_loss": "all-controlled-branches-open",
            "target_change": "open-before-reconfigure",
            "identity_mismatch": "refuse-activation",
            "configured": "only-cohort-permitted-branches-conduct",
        },
        "bootstrap": {
            "status": ("automatic" if automatic_bootstrap else "requires-declared-target"),
            "debug_positions": sorted(
                debug_positions,
                key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
            ),
            "rule": (
                "Use the common debug foundation before applying cohort-specific branches."
                if automatic_bootstrap
                else "Declare or externally identify the exact target before enabling controlled branches."
            ),
        },
        "fabric": {
            "strategy": "declared-target-fail-closed-cell-fabric",
            "universal_lanes": universal_lanes,
            "observation_nodes": universal_lanes,
            "controlled_branches": controlled_branches,
            "control_bits_required": controlled_branches,
            "cohort_configurations": len(cohorts),
            "capacity_limit": None,
            "configuration_authority": (
                "declared-target-before-power"
                if declared_target_required
                else "common-bootstrap-then-target-profile"
            ),
            "mandatory_interlocks": [
                "all branches default open",
                "hardware one-hot selection per position",
                "break before make",
                "branch-state readback",
                "fault forces all branches open",
                "ground returns close before source rails",
                "source rails use current-limited precharge",
                "target power remains disabled until configuration readback passes",
            ],
        },
        "target_cohorts": cohorts,
        "support_cells": support_cells,
        "positions": position_contracts,
        "proofs": proofs,
    }
    unsigned = dict(solution)
    unsigned.pop("artifact_digest", None)
    solution["artifact_digest"] = _digest(unsigned)
    return solution


def compile_socket_solution(
    conn: sqlite3.Connection,
    *,
    refs: list[str],
    policy: dict,
    source_meta: dict,
) -> dict:
    definition = compile_target_definition(
        conn,
        refs=refs,
        policy=policy,
        source_meta=source_meta,
    )
    return compile_socket_solution_from_definition(definition)
