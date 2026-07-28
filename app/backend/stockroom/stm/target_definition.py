"""Compile STM silicon facts plus an explicit external policy into one artifact.

The compatibility workbench answers whether device descriptions look alike. A
hardware build needs a different contract: silicon variation, requested service
routes, safety handling, and controllable-channel allocation must remain separate
and auditable. This module performs that pure computation over the derived STM
SQLite index. It owns no filesystem writes and names no board-specific component.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable

from stockroom.stm.authority import _position_sort_key, _resolve_mcu_row, five_v
from stockroom.text import counted

FORMAT = "stm-target-definition/1"
COMPILER_REV = 4

_GPIO_NAME = re.compile(r"^(P[A-Z]\d+)")
_CLAIM_SCOPES = {
    "pin-capability",
    "documented-service",
    "validated-procedure",
}
_FOUNDATION_GROUPS: tuple[dict, ...] = (
    {
        "id": "digital-supply",
        "label": "Digital Supply",
        "identities": ("power:vdd",),
        "obligation": "Bias every VDD pin within its target limits and decouple it locally.",
        "applicability": "when-present",
    },
    {
        "id": "analog-supply",
        "label": "Analog Supply",
        "identities": ("power:vdda",),
        "obligation": "Bias VDDA within its target limits and provide its documented filtering.",
        "applicability": "when-present",
    },
    {
        "id": "backup-supply",
        "label": "Backup Supply",
        "identities": ("power:vbat",),
        "obligation": "Provide a valid VBAT bias, including the documented tie when no battery is used.",
        "applicability": "when-present",
    },
    {
        "id": "voltage-reference",
        "label": "Analog Reference",
        "identities": ("power:vref",),
        "obligation": "Provide the documented VREF bias and decoupling for each exposed reference pin.",
        "applicability": "when-present",
    },
    {
        "id": "ground-return",
        "label": "Ground Returns",
        "identities": ("ground",),
        "obligation": "Bond every digital and analog ground return to the intended low-impedance domain.",
        "applicability": "when-present",
    },
    {
        "id": "core-regulator",
        "label": "Core Regulator",
        "identities": ("vcap",),
        "obligation": "Implement the exact datasheet VCAP/regulator network without external loading.",
        "applicability": "when-present",
    },
    {
        "id": "reset-control",
        "label": "Reset Control",
        "identities": ("reset",),
        "obligation": "Expose and bias reset so power-up, debug, and recovery sequencing remain valid.",
        "applicability": "when-present",
    },
    {
        "id": "boot-configuration",
        "label": "Boot Configuration",
        "identities": ("boot",),
        "obligation": "Give every exposed boot strap a deterministic, target-correct state and access path.",
        "applicability": "when-present",
    },
    {
        "id": "high-speed-clock",
        "label": "High-Speed Clock Pins",
        "access_tags": ("osc",),
        "obligation": "Preserve the external high-speed clock pair when the board policy uses it.",
        "applicability": "design-policy",
    },
    {
        "id": "low-speed-clock",
        "label": "Low-Speed Clock Pins",
        "access_tags": ("osc32",),
        "obligation": "Preserve the external low-speed clock pair when the board policy uses it.",
        "applicability": "design-policy",
    },
    {
        "id": "reserved-no-connect",
        "label": "Reserved / No Connect",
        "identities": ("no-connect",),
        "obligation": "Leave reserved and no-connect pins isolated unless exact target evidence says otherwise.",
        "applicability": "when-present",
        "allowed_actions": ("isolate",),
    },
)
_ACCESS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("reset", re.compile(r"\bNRST\b|RESET", re.I)),
    ("boot0", re.compile(r"\bBOOT0\b", re.I)),
    ("boot1", re.compile(r"\bBOOT1\b", re.I)),
    ("swdio", re.compile(r"SWDIO|JTMS", re.I)),
    ("swclk", re.compile(r"SWCLK|JTCK", re.I)),
    ("swo", re.compile(r"\bSWO\b|JTDO", re.I)),
    ("jtag", re.compile(r"JTAG|JTDI|JTDO|JTMS|JTCK|NJTRST", re.I)),
    ("trace", re.compile(r"TRACE", re.I)),
    ("osc", re.compile(r"OSC_IN|OSC_OUT|RCC_OSC(?!32)", re.I)),
    ("osc32", re.compile(r"OSC32|RCC_OSC32", re.I)),
    ("usb", re.compile(r"\bUSB|USB_", re.I)),
    ("usart", re.compile(r"USART|UART", re.I)),
    ("i2c", re.compile(r"\bI2C|I2C_", re.I)),
    ("spi", re.compile(r"\bSPI|SPI_", re.I)),
    ("can", re.compile(r"\bCAN|FDCAN", re.I)),
    ("analog", re.compile(r"\bADC|DAC|COMP|OPAMP", re.I)),
)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _base_gpio(name: str) -> str | None:
    match = _GPIO_NAME.match(str(name or "").upper())
    return match.group(1) if match else None


def _pin_identity(pin: dict) -> str:
    return (
        pin.get("critical_identity")
        or _base_gpio(str(pin.get("canonical_pin_name", "")))
        or str(pin.get("canonical_pin_name", ""))
    )


def _critical_identity(pin: dict) -> str | None:
    electrical = str(pin["electrical_class"] or "").lower()
    canonical = str(pin["canonical_pin_name"] or "").upper()
    roles = [str(role).lower() for role in pin["roles"]]

    if electrical == "io":
        return None
    if electrical == "ground":
        return "ground"
    if electrical == "vcap":
        return "vcap"
    if electrical == "reset":
        return "reset"
    if electrical == "boot":
        return "boot"
    if electrical == "nc":
        return "no-connect"
    if electrical == "power":
        domain = next(
            (role.removeprefix("power_") for role in roles if role.startswith("power_")),
            "",
        )
        if not domain:
            domain = re.split(r"[/_-]", canonical, maxsplit=1)[0].lower()
        return f"power:{domain or 'unknown'}"
    return f"{electrical or 'unknown'}:{canonical.lower()}"


def _access_tags(pin: dict) -> list[str]:
    haystack = " ".join(
        [
            pin["canonical_pin_name"],
            pin["raw_pin_name"],
            *pin["roles"],
            *pin["functions"],
            *(row["signal"] for row in pin["alternate_functions"]),
        ]
    )
    return [tag for tag, pattern in _ACCESS_PATTERNS if pattern.search(haystack)]


def _read_targets(conn: sqlite3.Connection, refs: list[str]) -> list[dict]:
    if not refs:
        raise ValueError("target definition requires at least one device reference")

    rows: list[sqlite3.Row] = []
    seen: set[int] = set()
    for ref in refs:
        row = _resolve_mcu_row(conn, str(ref))
        if row is None:
            raise ValueError(f"unknown part: {ref}")
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        rows.append(row)

    packages = {row["package_name"] for row in rows}
    if len(packages) != 1:
        raise ValueError(
            "target definition requires one physical package; "
            f"got packages={sorted(packages)}"
        )

    targets = []
    for row in sorted(rows, key=lambda item: item["ref_name"]):
        pins = []
        for pin_row in conn.execute(
            "SELECT id, physical_pin_number, canonical_pin_name, raw_pin_name, "
            "pin_type, electrical_class, lqfp_side, bga_row, bga_col "
            "FROM mcu_package_pin WHERE mcu_id = ?",
            (row["id"],),
        ):
            pin_id = pin_row["id"]
            roles = [
                role["role_name"]
                for role in conn.execute(
                    "SELECT role_name FROM pin_role WHERE mcu_package_pin_id = ? "
                    "ORDER BY role_name",
                    (pin_id,),
                )
            ]
            functions = [
                function["signal"]
                for function in conn.execute(
                    "SELECT signal FROM pin_function WHERE mcu_package_pin_id = ? "
                    "AND signal IS NOT NULL AND signal <> '' ORDER BY signal",
                    (pin_id,),
                )
            ]
            alternate_functions = [
                {
                    "af_index": af["af_index"],
                    "signal": af["signal"],
                    "peripheral": af["peripheral"],
                }
                for af in conn.execute(
                    "SELECT af_index, signal, peripheral FROM pin_alternate_function "
                    "WHERE mcu_package_pin_id = ? ORDER BY af_index, signal",
                    (pin_id,),
                )
            ]
            pin = {
                "position": pin_row["physical_pin_number"],
                "position_kind": "alnum" if pin_row["bga_row"] else "numeric",
                "lqfp_side": pin_row["lqfp_side"],
                "bga_row": pin_row["bga_row"],
                "bga_col": pin_row["bga_col"],
                "canonical_pin_name": pin_row["canonical_pin_name"],
                "raw_pin_name": pin_row["raw_pin_name"],
                "pin_type": pin_row["pin_type"],
                "electrical_class": pin_row["electrical_class"],
                "roles": roles,
                "functions": functions,
                "alternate_functions": alternate_functions,
            }
            peripherals = {
                af["peripheral"] for af in alternate_functions if af["peripheral"]
            }
            if pin["electrical_class"] == "io":
                pin["five_v"] = five_v(
                    {(row["family"], pin["canonical_pin_name"])}, peripherals
                )
            else:
                pin["five_v"] = None
            pin["critical_identity"] = _critical_identity(pin)
            pin["access_tags"] = _access_tags(pin)
            pins.append(pin)

        targets.append(
            {
                "id": row["id"],
                "ref": row["ref_name"],
                "family": row["family"],
                "line": row["line"],
                "package": row["package_name"],
                "pins": sorted(pins, key=lambda item: _position_sort_key(item["position"])),
            }
        )
    return targets


def resolve_target_refs(conn: sqlite3.Connection, selection: dict) -> list[str]:
    """Resolve a reproducible selection request to explicit CubeMX device refs.

    Artifacts always compile an explicit set. This helper lets non-interactive
    callers select all indexed devices for one package and a named set of
    families, while the resulting artifact still records every resolved ref.
    """
    selection = dict(selection or {})
    explicit = _ordered_unique(selection.get("parts", []) or [])
    has_scope = bool(selection.get("package") or selection.get("families"))
    if explicit and has_scope:
        raise ValueError("target selection must use parts or package/families, not both")
    if explicit:
        return [target["ref"] for target in _read_targets(conn, explicit)]

    package = str(selection.get("package", "")).strip()
    families = _ordered_unique(selection.get("families", []) or [])
    if not package or not families:
        raise ValueError(
            "target selection needs explicit parts or one package plus one or more families"
        )
    placeholders = ",".join("?" for _ in families)
    rows = conn.execute(
        "SELECT ref_name FROM mcu WHERE package_name = ? "
        f"AND family IN ({placeholders}) ORDER BY ref_name",
        (package, *families),
    ).fetchall()
    refs = [str(row["ref_name"]) for row in rows]
    if not refs:
        raise ValueError(
            f"target selection resolved no devices for package={package}, "
            f"families={families}"
        )
    return refs


def _position_class(per_target: list[dict], target_count: int) -> tuple[str, str]:
    if len(per_target) != target_count:
        return "partial", "unsupported"

    critical = [pin["critical_identity"] for pin in per_target]
    if any(identity is not None for identity in critical):
        if len(set(critical)) == 1:
            if critical[0] == "no-connect":
                return "fixed_critical", "isolate"
            return "fixed_critical", "hardwire"
        return "safety_collision", "isolate"

    gpio_names = {_base_gpio(pin["canonical_pin_name"]) for pin in per_target}
    gpio_names.discard(None)
    if len(gpio_names) == 1 and len(gpio_names) == len(
        {_base_gpio(pin["canonical_pin_name"]) for pin in per_target}
    ):
        return "stable_io", "breakout"
    return "variant_io", "breakout"


def _compile_positions(targets: list[dict]) -> list[dict]:
    by_position: dict[str, list[dict]] = {}
    for target in targets:
        for pin in target["pins"]:
            by_position.setdefault(pin["position"], []).append(
                {
                    "ref": target["ref"],
                    "family": target["family"],
                    **pin,
                }
            )

    positions = []
    for position in sorted(by_position, key=_position_sort_key):
        per_target = sorted(by_position[position], key=lambda item: item["ref"])
        silicon_class, board_action = _position_class(per_target, len(targets))
        sample = per_target[0]
        identities = sorted({_pin_identity(pin) for pin in per_target})
        positions.append(
            {
                "position": position,
                "position_kind": sample["position_kind"],
                "lqfp_side": sample["lqfp_side"],
                "bga_row": sample["bga_row"],
                "bga_col": sample["bga_col"],
                "silicon_class": silicon_class,
                "board_action": board_action,
                "identities": identities,
                "access_tags": sorted(
                    set.intersection(
                        *(set(pin["access_tags"]) for pin in per_target)
                    )
                    if per_target
                    else set()
                ),
                "access_tags_union": sorted(
                    {tag for pin in per_target for tag in pin["access_tags"]}
                ),
                "present_on": len(per_target),
                "total_targets": len(targets),
                "route_ids": [],
                "hazard": (
                    "critical electrical identities differ at this physical position"
                    if silicon_class == "safety_collision"
                    else ""
                ),
                "per_target": per_target,
            }
        )
    return positions


def _matches_requirement(pin: dict, requirement: dict) -> tuple[str, int | None] | None:
    required_tags = {str(tag).lower() for tag in requirement.get("access_tags", [])}
    if required_tags and required_tags.intersection(pin["access_tags"]):
        return (sorted(required_tags.intersection(pin["access_tags"]))[0], None)

    patterns = [
        re.compile(str(pattern), re.I)
        for pattern in requirement.get("signal_patterns", [])
    ]
    if not patterns:
        return None

    for signal in pin["functions"]:
        if any(pattern.fullmatch(signal) for pattern in patterns):
            return signal, None
    for option in pin["alternate_functions"]:
        if any(pattern.fullmatch(option["signal"]) for pattern in patterns):
            return option["signal"], option["af_index"]
    return None


def _preferred_key(position: str, preferred: list[str]) -> tuple[int, tuple]:
    try:
        rank = preferred.index(position)
    except ValueError:
        rank = len(preferred)
    return rank, _position_sort_key(position)


def _target_applies(target: dict, applicability: dict) -> bool:
    applicability = dict(applicability or {})
    checks = (
        ("refs", target["ref"]),
        ("families", target["family"]),
        ("lines", target["line"]),
    )
    for key, value in checks:
        allowed = {str(item) for item in applicability.get(key, []) or []}
        if allowed and value not in allowed:
            return False
    return True


def _claim_scope(value: object, *, owner: str) -> str:
    scope = str(value or "pin-capability").strip()
    if scope not in _CLAIM_SCOPES:
        raise ValueError(
            f"{owner} claim_scope must be one of: {', '.join(sorted(_CLAIM_SCOPES))}"
        )
    return scope


def _route_safety(
    target_ref: str,
    position: dict,
    safety_rule: dict | None,
) -> tuple[bool, str | None]:
    """Return whether one selected route is physically usable under the safety policy."""
    if position["silicon_class"] == "partial":
        return False, None
    if position["silicon_class"] != "safety_collision":
        return True, None
    if safety_rule is None:
        return False, None

    branches = list(safety_rule.get("branches", []) or [])
    if not branches:
        return safety_rule.get("action") not in {"isolate", "unsupported"}, None
    matches = [
        branch
        for branch in branches
        if target_ref in set(branch.get("matched_targets", []) or [])
    ]
    if len(matches) != 1:
        return False, None
    branch = matches[0]
    return (
        branch.get("action") not in {"isolate", "unsupported"},
        str(branch.get("id", "")) or None,
    )


def _compile_requirements(
    targets: list[dict],
    positions: list[dict],
    requirements: list[dict],
    safety_rules: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    position_by_number = {row["position"]: row for row in positions}
    safety_by_position = {str(rule["position"]): rule for rule in safety_rules}
    compiled = []

    seen_ids: set[str] = set()
    for raw in requirements:
        requirement = dict(raw)
        req_id = str(requirement.get("id", "")).strip()
        if not req_id:
            raise ValueError("every target-definition requirement needs a non-empty id")
        if req_id in seen_ids:
            raise ValueError(f"duplicate target-definition requirement id: {req_id}")
        seen_ids.add(req_id)
        required = bool(requirement.get("required", True))
        implementation_required = bool(
            requirement.get("implementation_required", required)
        )
        preferred = [str(value) for value in requirement.get("preferred_positions", [])]
        candidates_by_ref: dict[str, list[dict]] = {}
        applicable = [
            target
            for target in targets
            if _target_applies(target, dict(requirement.get("applies_to", {}) or {}))
        ]
        not_applicable = sorted(
            {target["ref"] for target in targets}
            - {target["ref"] for target in applicable}
        )
        if not applicable:
            raise ValueError(f"requirement {req_id} applies to no selected target")

        for target in applicable:
            candidates = []
            for pin in target["pins"]:
                match = _matches_requirement(pin, requirement)
                if match is None:
                    continue
                candidates.append(
                    {
                        "ref": target["ref"],
                        "position": pin["position"],
                        "canonical_pin_name": pin["canonical_pin_name"],
                        "signal": match[0],
                        "af_index": match[1],
                    }
                )
            candidates_by_ref[target["ref"]] = sorted(
                candidates,
                key=lambda item: _preferred_key(item["position"], preferred),
            )

        missing = [
            target["ref"]
            for target in applicable
            if not candidates_by_ref[target["ref"]]
        ]
        available = [
            target for target in applicable if candidates_by_ref[target["ref"]]
        ]
        routes: list[dict] = []
        implementation_kind = "none"
        route_kind = "blocked" if required else "unavailable"
        if available:
            common = set.intersection(
                *(
                    {candidate["position"] for candidate in candidates_by_ref[target["ref"]]}
                    for target in available
                )
            )
            common_position = (
                min(common, key=lambda value: _preferred_key(value, preferred))
                if common
                else None
            )
            for target in available:
                candidates = candidates_by_ref[target["ref"]]
                selected = (
                    next(
                        candidate
                        for candidate in candidates
                        if candidate["position"] == common_position
                    )
                    if common_position
                    else candidates[0]
                )
                routes.append(selected)

            selected_positions = {route["position"] for route in routes}
            for route in routes:
                usable, safety_branch = _route_safety(
                    route["ref"],
                    position_by_number[route["position"]],
                    safety_by_position.get(route["position"]),
                )
                route["usable"] = usable
                route["safety_branch"] = safety_branch
            unsafe_routes = [route for route in routes if not route["usable"]]
            unsafe_positions = sorted(
                {route["position"] for route in unsafe_routes},
                key=_position_sort_key,
            )
            if unsafe_routes:
                route_kind = "blocked"
                (blockers if required else warnings).append(
                    f"requirement {req_id} selects "
                    f"{counted(len(unsafe_positions), 'unresolved position')}: "
                    + ", ".join(unsafe_positions)
                )
            else:
                implementation_kind = (
                    "direct" if len(selected_positions) == 1 else "switched"
                )
                route_kind = (
                    ("blocked" if required else "partial")
                    if missing
                    else implementation_kind
                )
                if implementation_required:
                    for position in selected_positions:
                        row = position_by_number[position]
                        row["route_ids"].append(req_id)
                        if row["silicon_class"] != "safety_collision":
                            row["board_action"] = implementation_kind

        if missing:
            message = f"requirement {req_id} has no route on: {', '.join(missing)}"
            (blockers if required else warnings).append(message)

        evidence = _ordered_unique(requirement.get("evidence", []))
        if not evidence:
            (blockers if required else warnings).append(
                f"requirement {req_id} has no cited route evidence"
            )

        blocked_targets = sorted(
            route["ref"] for route in routes if not route.get("usable", False)
        )
        usable_count = len(routes) - len(blocked_targets)
        coverage_status = (
            "unavailable"
            if usable_count == 0
            else "partial"
            if missing or blocked_targets
            else "complete"
        )

        claim_scope = _claim_scope(
            requirement.get("claim_scope", "pin-capability"),
            owner=f"requirement {req_id}",
        )
        compiled.append(
            {
                "id": req_id,
                "label": requirement.get("label", req_id),
                "net": requirement.get("net", req_id.upper()),
                "required": required,
                "implementation_required": implementation_required,
                "category": str(requirement.get("category", "general")),
                "service_group": str(requirement.get("service_group", "")),
                "protocol": str(requirement.get("protocol", "")),
                "direction": str(requirement.get("direction", "")),
                "access_plane": str(requirement.get("access_plane", "function")),
                "purposes": _ordered_unique(requirement.get("purposes", []) or []),
                "claim_scope": claim_scope,
                "route_kind": route_kind,
                "implementation_kind": implementation_kind,
                "coverage_status": coverage_status,
                "applicable_targets": [target["ref"] for target in applicable],
                "not_applicable_targets": not_applicable,
                "missing_targets": missing,
                "blocked_targets": blocked_targets,
                "routes": routes,
                "candidates_by_target": candidates_by_ref,
                "candidate_counts": {
                    ref: len(candidates) for ref, candidates in candidates_by_ref.items()
                },
                "onehot_group": (
                    str(requirement.get("onehot_group", req_id))
                    if implementation_kind == "switched"
                    else None
                ),
                "evidence": evidence,
            }
        )
    return compiled, blockers, warnings


def _compile_service_groups(
    targets: list[dict],
    requirements: list[dict],
    raw_groups: list[dict],
) -> tuple[list[dict], list[str], list[str]]:
    by_id = {requirement["id"]: requirement for requirement in requirements}
    blockers: list[str] = []
    warnings: list[str] = []
    compiled: list[dict] = []
    seen: set[str] = set()

    for raw in raw_groups:
        group = dict(raw)
        group_id = str(group.get("id", "")).strip()
        if not group_id:
            raise ValueError("every service group needs a non-empty id")
        if group_id in seen:
            raise ValueError(f"duplicate service group id: {group_id}")
        seen.add(group_id)
        requirement_ids = _ordered_unique(group.get("requirement_ids", []) or [])
        if not requirement_ids:
            raise ValueError(f"service group {group_id} has no requirement_ids")
        unknown = [req_id for req_id in requirement_ids if req_id not in by_id]
        if unknown:
            raise ValueError(
                f"service group {group_id} references unknown requirements: "
                + ", ".join(unknown)
            )

        required_members = set(
            _ordered_unique(group.get("required_requirement_ids", []) or [])
            or requirement_ids
        )
        unknown_required = sorted(required_members - set(requirement_ids))
        if unknown_required:
            raise ValueError(
                f"service group {group_id} requires non-member requirements: "
                + ", ".join(unknown_required)
            )
        applicable = [
            target
            for target in targets
            if _target_applies(target, dict(group.get("applies_to", {}) or {}))
        ]
        if not applicable:
            raise ValueError(f"service group {group_id} applies to no selected target")

        per_target = []
        for target in applicable:
            missing_members = []
            positions = {}
            for req_id in requirement_ids:
                requirement = by_id[req_id]
                if target["ref"] in requirement["not_applicable_targets"]:
                    if req_id in required_members:
                        missing_members.append(req_id)
                    continue
                route = next(
                    (
                        item
                        for item in requirement["routes"]
                        if item["ref"] == target["ref"]
                    ),
                    None,
                )
                if route is None or not route.get("usable", False):
                    if req_id in required_members:
                        missing_members.append(req_id)
                else:
                    positions[req_id] = route["position"]
            per_target.append(
                {
                    "ref": target["ref"],
                    "family": target["family"],
                    "line": target["line"],
                    "status": "complete" if not missing_members else "incomplete",
                    "missing_requirements": missing_members,
                    "positions": positions,
                }
            )

        complete_count = sum(item["status"] == "complete" for item in per_target)
        status = (
            "complete"
            if complete_count == len(per_target)
            else "unavailable"
            if complete_count == 0
            else "partial"
        )
        required_group = bool(group.get("required", False))
        claim_scope = _claim_scope(
            group.get("claim_scope", "pin-capability"),
            owner=f"service group {group_id}",
        )
        if status != "complete":
            message = (
                f"service group {group_id} is {status}: "
                f"{complete_count}/{len(per_target)} applicable targets complete"
            )
            (blockers if required_group else warnings).append(message)
        evidence = _ordered_unique(group.get("evidence", []) or [])
        if not evidence:
            (blockers if required_group else warnings).append(
                f"service group {group_id} has no cited evidence"
            )
        purposes = _ordered_unique(group.get("purposes", []) or [])
        sensitive_purposes = sorted(
            set(purposes).intersection({"recovery", "data-access"})
        )
        if claim_scope == "pin-capability" and sensitive_purposes:
            warnings.append(
                f"service group {group_id} is pin-capability only; "
                f"target-specific {'/'.join(sensitive_purposes)} support is unproven"
            )
        procedure_refs = _ordered_unique(group.get("procedure_refs", []) or [])
        if claim_scope == "validated-procedure" and not procedure_refs:
            (blockers if required_group else warnings).append(
                f"service group {group_id} claims a validated procedure without "
                "procedure_refs"
            )
        not_applicable = sorted(
            {target["ref"] for target in targets}
            - {target["ref"] for target in applicable}
        )
        compiled.append(
            {
                "id": group_id,
                "label": str(group.get("label", group_id)),
                "category": str(group.get("category", "general")),
                "protocol": str(group.get("protocol", "")),
                "required": required_group,
                "claim_scope": claim_scope,
                "purposes": purposes,
                "requirement_ids": requirement_ids,
                "required_requirement_ids": sorted(required_members),
                "status": status,
                "applicable_target_count": len(per_target),
                "complete_target_count": complete_count,
                "not_applicable_targets": not_applicable,
                "per_target": per_target,
                "entry_conditions": _ordered_unique(
                    group.get("entry_conditions", []) or []
                ),
                "protection_constraints": _ordered_unique(
                    group.get("protection_constraints", []) or []
                ),
                "side_effects": _ordered_unique(group.get("side_effects", []) or []),
                "procedure_refs": procedure_refs,
                "destructive": bool(group.get("destructive", False)),
                "evidence": evidence,
            }
        )
    return compiled, blockers, warnings


def _compile_functional_foundation(
    targets: list[dict],
    positions: list[dict],
    safety_rules: list[dict],
) -> dict:
    """Roll every run-critical pin class up by target and physical position.

    CubeMX identifies the pins; it does not authorize passive values or target
    operating limits. Those remain explicit external evidence obligations.
    """
    position_by_number = {position["position"]: position for position in positions}
    safety_by_position = {str(rule["position"]): rule for rule in safety_rules}
    groups: list[dict] = []

    for definition in _FOUNDATION_GROUPS:
        identities = set(definition.get("identities", ()))
        access_tags = set(definition.get("access_tags", ()))
        allowed_actions = set(
            definition.get(
                "allowed_actions",
                ("hardwire", "breakout", "direct", "switched", "selectable"),
            )
        )
        per_target = []
        all_positions: set[str] = set()
        unresolved_positions: set[str] = set()
        for target in targets:
            pins = []
            for pin in target["pins"]:
                identity = _pin_identity(pin)
                if identities and identity not in identities:
                    continue
                if access_tags and not access_tags.intersection(pin["access_tags"]):
                    continue
                position = position_by_number[pin["position"]]
                safety_resolved, _ = _route_safety(
                    target["ref"],
                    position,
                    safety_by_position.get(pin["position"]),
                )
                resolved = (
                    position["board_action"] in allowed_actions
                    and (
                        position["silicon_class"] != "safety_collision"
                        or safety_resolved
                    )
                )
                all_positions.add(pin["position"])
                if not resolved:
                    unresolved_positions.add(pin["position"])
                pins.append(
                    {
                        "position": pin["position"],
                        "canonical_pin_name": pin["canonical_pin_name"],
                        "electrical_class": pin["electrical_class"],
                        "identity": identity,
                        "board_action": position["board_action"],
                        "resolved": resolved,
                    }
                )
            per_target.append(
                {
                    "ref": target["ref"],
                    "family": target["family"],
                    "line": target["line"],
                    "present": bool(pins),
                    "resolved": bool(pins) and all(pin["resolved"] for pin in pins),
                    "pins": pins,
                }
            )

        applicable = [target for target in per_target if target["present"]]
        resolved_count = sum(target["resolved"] for target in applicable)
        status = (
            "unavailable"
            if not applicable
            else "complete"
            if resolved_count == len(applicable)
            else "partial"
        )
        groups.append(
            {
                "id": definition["id"],
                "label": definition["label"],
                "obligation": definition["obligation"],
                "applicability": definition["applicability"],
                "claim_scope": "pin-obligation",
                "network_evidence_required": True,
                "status": status,
                "present_target_count": len(applicable),
                "resolved_target_count": resolved_count,
                "positions": sorted(all_positions, key=_position_sort_key),
                "unresolved_positions": sorted(
                    unresolved_positions, key=_position_sort_key
                ),
                "per_target": per_target,
            }
        )

    unresolved = sorted(
        {
            position
            for group in groups
            for position in group["unresolved_positions"]
        },
        key=_position_sort_key,
    )
    return {
        "claim_scope": "pin-obligation",
        "network_values_authority": "external-target-documentation-required",
        "status": "complete" if not unresolved else "partial",
        "groups": groups,
        "unresolved_positions": unresolved,
    }


def _branch_matches(identity: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        try:
            if re.fullmatch(pattern, identity, re.I):
                return True
        except re.error as exc:
            raise ValueError(f"invalid safety-branch identity pattern {pattern!r}: {exc}") from exc
    return False


def _apply_safety_rules(
    positions: list[dict], safety_rules: list[dict]
) -> tuple[list[dict], list[dict], list[str], list[str]]:
    position_by_number = {row["position"]: row for row in positions}
    rules_by_position: dict[str, dict] = {}
    for raw_rule in safety_rules:
        if raw_rule.get("position") is None:
            raise ValueError("every target-definition safety rule needs a position")
        rule_position = str(raw_rule["position"])
        if rule_position in rules_by_position:
            raise ValueError(f"duplicate safety rule for position {rule_position}")
        rules_by_position[rule_position] = dict(raw_rule)
    channel_requests: list[dict] = []
    compiled_rules: list[dict] = []
    blockers: list[str] = []
    warnings: list[str] = []

    for position in positions:
        if position["silicon_class"] != "safety_collision":
            continue
        rule = rules_by_position.get(position["position"])
        if rule is None:
            blockers.append(
                f"position {position['position']} has a critical identity collision "
                "without a safety rule"
            )
            continue

        evidence = _ordered_unique(rule.get("evidence", []))
        safe_default = str(rule.get("safe_default", "")).lower()
        action = str(rule.get("action", "selectable")).lower()
        if not evidence:
            blockers.append(
                f"position {position['position']} safety rule has no cited evidence"
            )
        if safe_default not in {"open", "off", "high-z"}:
            blockers.append(
                f"position {position['position']} safety rule must default open/off/high-z"
            )
        if action not in {
            "hardwire",
            "breakout",
            "direct",
            "switched",
            "selectable",
            "isolate",
            "unsupported",
        }:
            blockers.append(
                f"position {position['position']} safety rule has unsupported action {action!r}"
            )
            action = "isolate"
        position["board_action"] = action
        position["hazard"] = str(rule.get("hazard", position["hazard"]))

        compiled_branches: list[dict] = []
        raw_branches = list(rule.get("branches", []) or [])
        identity_owners: dict[str, list[str]] = {
            identity: [] for identity in position["identities"]
        }
        for branch_index, raw_branch in enumerate(raw_branches, start=1):
            branch = dict(raw_branch)
            branch_id = str(branch.get("id", f"branch-{branch_index}")).strip()
            patterns = _ordered_unique(
                branch.get("identity_patterns", branch.get("identities", []))
            )
            if not patterns:
                blockers.append(
                    f"position {position['position']} branch {branch_id} has no identity patterns"
                )
            matched_identities = [
                identity
                for identity in position["identities"]
                if _branch_matches(identity, patterns)
            ]
            if patterns and not matched_identities:
                blockers.append(
                    f"position {position['position']} branch {branch_id} matches no silicon identity"
                )
            for identity in matched_identities:
                identity_owners[identity].append(branch_id)

            branch_action = str(branch.get("action", "switched")).lower()
            if branch_action not in {
                "hardwire",
                "breakout",
                "direct",
                "switched",
                "selectable",
                "isolate",
                "unsupported",
            }:
                blockers.append(
                    f"position {position['position']} branch {branch_id} has unsupported "
                    f"action {branch_action!r}"
                )
                branch_action = "unsupported"
            branch_evidence = _ordered_unique(branch.get("evidence", evidence))
            if not branch_evidence:
                blockers.append(
                    f"position {position['position']} branch {branch_id} has no cited evidence"
                )
            if branch_action == "unsupported":
                blockers.append(
                    f"position {position['position']} branch {branch_id} is unsupported"
                )

            matched_targets = sorted(
                pin["ref"]
                for pin in position["per_target"]
                if _pin_identity(pin) in matched_identities
            )
            uses_channel = bool(
                branch.get(
                    "uses_channel",
                    branch_action in {"switched", "selectable"},
                )
            )
            compiled_branch = {
                "id": branch_id,
                "identity_patterns": patterns,
                "matched_identities": matched_identities,
                "matched_targets": matched_targets,
                "action": branch_action,
                "net": str(branch.get("net", "")).strip(),
                "uses_channel": uses_channel,
                "safe_default": str(branch.get("safe_default", safe_default)).lower(),
                "evidence": branch_evidence,
            }
            compiled_branches.append(compiled_branch)
            if uses_channel:
                channel_requests.append(
                    {
                        "kind": "safety",
                        "position": position["position"],
                        "net": compiled_branch["net"]
                        or f"SAFETY_{position['position']}_{branch_id}",
                        "route_id": None,
                        "branch_id": branch_id,
                        "onehot_group": branch.get(
                            "onehot_group",
                            rule.get("onehot_group", f"position-{position['position']}"),
                        ),
                        "safe_default": compiled_branch["safe_default"],
                        "targets": matched_targets,
                        "identities": matched_identities,
                    }
                )

        if raw_branches:
            for identity, owners in identity_owners.items():
                if not owners:
                    blockers.append(
                        f"position {position['position']} identity {identity} has no safety branch"
                    )
                elif len(owners) > 1:
                    blockers.append(
                        f"position {position['position']} identity {identity} is claimed by "
                        f"multiple safety branches: {', '.join(owners)}"
                    )

        compiled = {
            "position": position["position"],
            "action": action,
            "safe_default": safe_default,
            "onehot_group": rule.get("onehot_group"),
            "evidence": evidence,
            "branches": compiled_branches,
        }
        compiled_rules.append(compiled)
        if not raw_branches and bool(
            rule.get("uses_channel", action in {"switched", "selectable"})
        ):
            channel_requests.append(
                {
                    "kind": "safety",
                    "position": position["position"],
                    "net": rule.get("net", f"SAFETY_{position['position']}"),
                    "route_id": None,
                    "onehot_group": rule.get("onehot_group"),
                    "safe_default": safe_default,
                }
            )

    for rule_position in sorted(rules_by_position, key=_position_sort_key):
        position = position_by_number.get(rule_position)
        if position is None:
            warnings.append(
                f"safety rule position {rule_position} is absent from this target set"
            )
        elif position["silicon_class"] != "safety_collision":
            warnings.append(
                f"safety rule position {rule_position} does not resolve a critical collision"
            )
    return compiled_rules, channel_requests, blockers, warnings


def _route_channel_requests(requirements: list[dict]) -> list[dict]:
    requests: list[dict] = []
    for requirement in requirements:
        if (
            not requirement["implementation_required"]
            or requirement["implementation_kind"] != "switched"
        ):
            continue
        by_position: dict[str, list[str]] = {}
        for route in requirement["routes"]:
            if not route.get("usable", False):
                continue
            by_position.setdefault(route["position"], []).append(route["ref"])
        for position in sorted(by_position, key=_position_sort_key):
            requests.append(
                {
                    "kind": "route",
                    "position": position,
                    "net": requirement["net"],
                    "route_id": requirement["id"],
                    "onehot_group": requirement["id"],
                    "safe_default": "open",
                    "targets": sorted(by_position[position]),
                }
            )
    return requests


def _allocate_channels(
    channel_requests: list[dict], fabric: dict
) -> tuple[dict, list[str]]:
    blockers: list[str] = []
    part_mpn = str(fabric.get("part_mpn", "")).strip()
    channels_per_device = int(fabric.get("channels_per_device", 0) or 0)
    max_devices = int(fabric.get("max_devices", 0) or 0)
    reference_prefix = str(fabric.get("reference_prefix", "U_ROUTE")).strip() or "U_ROUTE"
    default_state = str(fabric.get("default_state", "")).lower()

    if channel_requests and not part_mpn:
        blockers.append("channel fabric has no exact component MPN")
    if channel_requests and channels_per_device <= 0:
        blockers.append("channel fabric channels_per_device must be positive")
    if channel_requests and max_devices <= 0:
        blockers.append("channel fabric max_devices must be positive")
    if channel_requests and default_state != "open":
        blockers.append("channel fabric must default open")

    capacity = max(0, channels_per_device * max_devices)
    if len(channel_requests) > capacity:
        blockers.append(
            f"channel fabric capacity {capacity} is below required {len(channel_requests)}"
        )

    allocations = []
    if channels_per_device > 0:
        for index, request in enumerate(channel_requests):
            device = index // channels_per_device + 1
            channel = index % channels_per_device + 1
            allocations.append(
                {
                    **request,
                    "reference": f"{reference_prefix}_{device}",
                    "device_index": device,
                    "channel": channel,
                    "register_bit": channel - 1,
                    "register_label": f"DB{channel - 1}",
                }
            )

    used_devices = (
        (len(channel_requests) + channels_per_device - 1) // channels_per_device
        if channels_per_device > 0
        else 0
    )
    return (
        {
            "part_mpn": part_mpn,
            "channels_per_device": channels_per_device,
            "max_devices": max_devices,
            "default_state": default_state,
            "reference_prefix": reference_prefix,
            "required_channels": len(channel_requests),
            "capacity": capacity,
            "used_devices": used_devices,
            "allocations": allocations,
        },
        blockers,
    )


def _validate_target_mpns(
    targets: list[dict], target_mpns: dict
) -> tuple[list[dict], list[str]]:
    resolved = []
    warnings = []
    for target in targets:
        mpns = _ordered_unique(target_mpns.get(target["ref"], []))
        if not mpns:
            warnings.append(
                f"{target['ref']} is a CubeMX device mask with no verified ordering MPN list"
            )
        resolved.append(
            {
                "ref": target["ref"],
                "family": target["family"],
                "line": target["line"],
                "verified_mpns": mpns,
            }
        )
    return resolved, warnings


def compile_target_definition(
    conn: sqlite3.Connection,
    *,
    refs: list[str],
    policy: dict,
    source_meta: dict | None = None,
) -> dict:
    """Return a deterministic, content-addressed target-definition artifact."""
    source_meta = dict(source_meta or {})
    policy = dict(policy or {})
    profile_id = str(policy.get("id", "")).strip()
    if not profile_id:
        raise ValueError("target-definition policy needs a non-empty id")
    try:
        profile_revision = int(policy.get("revision", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("target-definition policy revision must be a positive integer") from exc
    if profile_revision <= 0:
        raise ValueError("target-definition policy revision must be a positive integer")

    targets = _read_targets(conn, refs)
    positions = _compile_positions(targets)

    safety_rules, safety_channels, safety_blockers, safety_warnings = _apply_safety_rules(
        positions, list(policy.get("safety_rules", []) or [])
    )
    requirements, route_blockers, route_warnings = _compile_requirements(
        targets,
        positions,
        list(policy.get("requirements", []) or []),
        safety_rules,
    )
    service_groups, group_blockers, group_warnings = _compile_service_groups(
        targets,
        requirements,
        list(policy.get("service_groups", []) or []),
    )
    functional_foundation = _compile_functional_foundation(
        targets, positions, safety_rules
    )
    channel_requests = safety_channels + _route_channel_requests(requirements)
    channel_fabric, channel_blockers = _allocate_channels(
        channel_requests, dict(policy.get("channel_fabric", {}) or {})
    )
    target_scope, mpn_warnings = _validate_target_mpns(
        targets, dict(policy.get("target_mpns", {}) or {})
    )

    route_claim_blockers = []
    for position in positions:
        route_ids = _ordered_unique(position["route_ids"])
        position["route_ids"] = route_ids
        if len(route_ids) > 1:
            route_claim_blockers.append(
                f"position {position['position']} is claimed by multiple required routes: "
                + ", ".join(route_ids)
            )

    provenance_blockers = []
    for field in ("source_sha256", "classifier_rev", "af_schema_rev", "geometry_rev"):
        if not source_meta.get(field):
            provenance_blockers.append(f"silicon provenance is missing {field}")

    blockers = _ordered_unique(
        [
            *route_blockers,
            *route_claim_blockers,
            *group_blockers,
            *safety_blockers,
            *channel_blockers,
            *provenance_blockers,
            *(str(item) for item in policy.get("declared_blockers", []) or []),
        ]
    )
    for position in positions:
        if position["silicon_class"] == "partial":
            blockers.append(
                f"position {position['position']} is absent from one or more selected targets"
            )
    blockers = _ordered_unique(blockers)

    warnings = _ordered_unique(
        [*route_warnings, *group_warnings, *safety_warnings, *mpn_warnings]
    )
    summary: dict[str, int] = {}
    action_summary: dict[str, int] = {}
    for position in positions:
        summary[position["silicon_class"]] = summary.get(position["silicon_class"], 0) + 1
        action_summary[position["board_action"]] = action_summary.get(
            position["board_action"], 0
        ) + 1

    policy_digest = _sha256(policy)
    artifact = {
        "format": FORMAT,
        "compiler_rev": COMPILER_REV,
        "profile": {
            "id": profile_id,
            "revision": profile_revision,
            "coverage_mode": policy.get("coverage_mode", "explicit-device-set"),
            "policy_digest": policy_digest,
        },
        "scope": {
            "package": targets[0]["package"],
            "families": sorted({target["family"] for target in targets}),
            "target_count": len(targets),
            "targets": target_scope,
        },
        "provenance": {
            "silicon_source": "STM32CubeMX XML",
            "source_sha256": str(source_meta.get("source_sha256", "")),
            "source_built_at": str(source_meta.get("built_at", "")),
            "classifier_rev": int(source_meta.get("classifier_rev", 0) or 0),
            "af_schema_rev": int(source_meta.get("af_schema_rev", 0) or 0),
            "geometry_rev": int(source_meta.get("geometry_rev", 0) or 0),
            "policy_digest": policy_digest,
        },
        "readiness": {
            "status": "ready" if not blockers else "blocked",
            "blockers": blockers,
            "warnings": warnings,
        },
        "summary": {
            "silicon_classes": dict(sorted(summary.items())),
            "board_actions": dict(sorted(action_summary.items())),
            "required_routes": sum(1 for item in requirements if item["required"]),
            "switched_routes": sum(
                1 for item in requirements if item["implementation_kind"] == "switched"
            ),
            "safety_rules": len(safety_rules),
            "service_groups": len(service_groups),
            "foundation_groups": len(functional_foundation["groups"]),
        },
        "requirements": requirements,
        "service_groups": service_groups,
        "functional_foundation": functional_foundation,
        "safety_rules": safety_rules,
        "channel_fabric": channel_fabric,
        "positions": positions,
    }
    artifact["artifact_digest"] = _sha256(artifact)
    return artifact
