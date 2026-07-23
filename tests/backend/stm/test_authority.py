"""stm/authority.py (Layer B) unit tests, stm-viewer workstream Phase 3, 03-02.

Uses the stm_conn/stm_refs fixtures from conftest.py: four MCUs, three sharing
(package=LQFP64, family=STM32F4) with a shared position, an AF-swappable
divergence, an un-swappable divergence, and a partial position, plus a fourth
in a different family sharing the same package_name (the scope-exclusion case).
"""

from __future__ import annotations

import pytest

from stockroom.stm.authority import (
    _cubemx_regex,
    af_conflicts,
    compatibility_suggestions,
    five_v,
    package_family_union,
    pin_signature,
    resolve_part,
    socket_union,
)


# ─────────────────────────────────────────────────────────────────────────────
# five_v
# ─────────────────────────────────────────────────────────────────────────────


def test_five_v_non_5v_gpio_returns_not_tolerant():
    # PA4 is in STM32F4's non-5V set
    result = five_v({("STM32F4", "PA4")}, [])
    assert result is not None
    assert result["tolerant"] is False
    assert result["by_family"] == {"STM32F4": False}


def test_five_v_ordinary_gpio_returns_tolerant():
    result = five_v({("STM32F4", "PA9")}, [])
    assert result is not None
    assert result["tolerant"] is True
    assert result["by_family"] == {"STM32F4": True}


def test_five_v_non_gpio_position_returns_none():
    assert five_v({("STM32F4", "VDD")}, []) is None
    assert five_v(set(), []) is None


def test_five_v_analog_caveat():
    result = five_v({("STM32F4", "PC4")}, ["ADC1"])
    assert result is not None
    assert result["tolerant"] is True
    assert result["caveat"] == "analog-mode"


def test_five_v_osc_caveat():
    result = five_v({("STM32F4", "PC14")}, [])
    assert result is not None
    assert result["caveat"] == "osc-mode"


def test_five_v_multi_family_ands_by_family():
    # two GPIOs under one family: tolerant only if BOTH are FT
    result = five_v({("STM32F4", "PA9"), ("STM32F4", "PA4")}, [])
    assert result["by_family"]["STM32F4"] is False
    assert result["tolerant"] is False


# ─────────────────────────────────────────────────────────────────────────────
# _cubemx_regex
# ─────────────────────────────────────────────────────────────────────────────


def test_cubemx_regex_expands_variant_and_wildcard():
    import re

    pattern = _cubemx_regex("STM32F407V(E-G)Tx")
    assert re.match(pattern, "STM32F407VGT6")
    assert re.match(pattern, "STM32F407VET6")
    assert not re.match(pattern, "STM32F407ZGT6")


def test_cubemx_regex_bare_x_matches_any_char():
    import re

    pattern = _cubemx_regex("STM32F103C8Tx")
    assert re.match(pattern, "STM32F103C8T6")
    assert re.match(pattern, "STM32F103C8TA")


# ─────────────────────────────────────────────────────────────────────────────
# resolve_part
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_part_exact_match(stm_conn, stm_refs):
    result = resolve_part(stm_conn, stm_refs["mcu1"])
    assert result is not None
    assert result["part"] == stm_refs["mcu1"]
    assert result["package"] == "LQFP64"
    assert result["family"] == "STM32F4"
    assert result["line"] == "STM32F401"
    positions = {p["position"]: p for p in result["pins"]}
    assert "12" in positions
    pin12 = positions["12"]
    assert {"role_name": "gpio", "role_class": "io"} in pin12["roles"]
    assert pin12["five_v"] is not None
    assert pin12["five_v"]["tolerant"] is True


def test_resolve_part_prefix_match(stm_conn, stm_refs):
    # "STM32F401VB" is a unique prefix of MCU1's ref_name only (MCU1B is "...RETx")
    result = resolve_part(stm_conn, "STM32F401VB")
    assert result is not None
    assert result["part"] == stm_refs["mcu1"]


def test_resolve_part_regex_match_on_real_mpn(stm_conn, stm_refs):
    result = resolve_part(stm_conn, "STM32F407VGT6")
    assert result is not None
    assert result["part"] == stm_refs["mcu2"]


def test_resolve_part_miss_returns_none(stm_conn):
    assert resolve_part(stm_conn, "NONEXISTENT999") is None


def test_resolve_part_shape_has_no_switch_fabric_fields(stm_conn, stm_refs):
    result = resolve_part(stm_conn, stm_refs["mcu1"])
    assert "close_switches" not in result
    assert "rail_conflicts" not in result
    assert "boot_straps" not in result
    assert "debug_positions" not in result
    assert "part_number" not in result


def test_resolve_part_non_gpio_position_has_no_five_v(stm_conn, stm_refs):
    result = resolve_part(stm_conn, stm_refs["mcu3"])
    positions = {p["position"]: p for p in result["pins"]}
    assert positions["12"]["electrical_class"] == "reset"
    assert positions["12"]["five_v"] is None


# ─────────────────────────────────────────────────────────────────────────────
# pin_signature
# ─────────────────────────────────────────────────────────────────────────────


def test_pin_signature_combines_and_dedupes():
    sig = pin_signature(
        {
            "roles": ["gpio"],
            "functions": ["USART1_TX"],
            "af_signals": ["USART1_TX", "TIM2_CH1"],
            "peripherals": ["USART1", "TIM2"],
        }
    )
    assert sig == frozenset({"gpio", "USART1_TX", "TIM2_CH1", "USART1", "TIM2"})


def test_pin_signature_order_independent():
    a = pin_signature({"roles": ["gpio", "analog"], "functions": [], "af_signals": [], "peripherals": []})
    b = pin_signature({"roles": ["analog", "gpio"], "functions": [], "af_signals": [], "peripherals": []})
    assert a == b


def test_pin_signature_empty_facts_yields_empty_frozenset():
    assert pin_signature({}) == frozenset()


# ─────────────────────────────────────────────────────────────────────────────
# package_family_union
# ─────────────────────────────────────────────────────────────────────────────


def test_package_family_union_shared_position_single_key_histogram(stm_conn):
    result = package_family_union(stm_conn, "LQFP64", "STM32F4")
    assert result["total_mcus"] == 3
    pos12 = next(p for p in result["positions"] if p["position"] == "12")
    assert len(pos12["histogram"]) == 1
    assert list(pos12["histogram"].values())[0] == 3


def test_package_family_union_divergent_position_multi_key_histogram(stm_conn):
    result = package_family_union(stm_conn, "LQFP64", "STM32F4")
    pos13 = next(p for p in result["positions"] if p["position"] == "13")
    assert len(pos13["histogram"]) == 2


def test_package_family_union_excludes_out_of_family_mcu(stm_conn):
    # MCU3 shares package_name "LQFP64" but is family STM32F1 - must NOT be unioned
    # into the STM32F4 scope (never a bare-package union).
    result = package_family_union(stm_conn, "LQFP64", "STM32F4")
    assert result["total_mcus"] == 3  # not 4

    f1_result = package_family_union(stm_conn, "LQFP64", "STM32F1")
    assert f1_result["total_mcus"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# compatibility_suggestions
# ─────────────────────────────────────────────────────────────────────────────


def test_compatibility_suggestions_baseline_and_divergent_tiers(stm_conn, stm_refs):
    groups = compatibility_suggestions(stm_conn, "LQFP64", "STM32F4", tolerance=0)
    baseline = next(g for g in groups if g["tier"] == "baseline")
    assert set(baseline["refs"]) == {stm_refs["mcu1"], stm_refs["mcu1b"]}

    divergent = [g for g in groups if g["tier"] == "divergent"]
    assert len(divergent) == 1
    assert divergent[0]["refs"] == [stm_refs["mcu2"]]
    assert divergent[0]["divergent_positions"] > 0


def test_compatibility_suggestions_tolerance_merges_groups(stm_conn, stm_refs):
    baseline_only = compatibility_suggestions(stm_conn, "LQFP64", "STM32F4", tolerance=0)
    divergence = next(g for g in baseline_only if g["tier"] == "divergent")["divergent_positions"]

    merged = compatibility_suggestions(stm_conn, "LQFP64", "STM32F4", tolerance=divergence)
    assert len(merged) == 1
    assert merged[0]["tier"] == "baseline"
    assert set(merged[0]["refs"]) == {stm_refs["mcu1"], stm_refs["mcu1b"], stm_refs["mcu2"]}


# ─────────────────────────────────────────────────────────────────────────────
# socket_union
# ─────────────────────────────────────────────────────────────────────────────


def test_socket_union_shared_position(stm_conn, stm_refs):
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu2"]])
    pos12 = next(p for p in result["positions"] if p["position"] == "12")
    assert pos12["classification"] == "shared"
    assert pos12["present_on"] == 2
    assert pos12["total"] == 2


def test_socket_union_divergent_swappable_reconcile(stm_conn, stm_refs):
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu2"]])
    pos13 = next(p for p in result["positions"] if p["position"] == "13")
    assert pos13["classification"] == "divergent"
    reconcile = pos13["reconcile"]
    assert reconcile["swappable"] is True
    assert reconcile["swaps"] == [
        {"ref": stm_refs["mcu2"], "target_signal": "USART1_RX", "via_af_index": 8}
    ]


def test_socket_union_divergent_unswappable_reconcile(stm_conn, stm_refs):
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu2"]])
    pos45 = next(p for p in result["positions"] if p["position"] == "45")
    assert pos45["classification"] == "divergent"
    reconcile = pos45["reconcile"]
    assert reconcile["swappable"] is False
    assert reconcile["swaps"] == []
    assert reconcile["reason"]


def test_socket_union_partial_position(stm_conn, stm_refs):
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu2"]])
    pos34 = next(p for p in result["positions"] if p["position"] == "34")
    assert pos34["classification"] == "partial"
    assert pos34["present_on"] == 1
    assert pos34["total"] == 2


def test_socket_union_verdict_incompatible_due_to_unswappable_divergence(stm_conn, stm_refs):
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu2"]])
    verdict = result["verdict"]
    assert verdict["interchangeable"] is False
    assert any(b["position"] == "45" for b in verdict["blocking"])


def test_socket_union_verdict_interchangeable_when_only_swappable_divergences(stm_conn, stm_refs):
    # MCU1 vs MCU1B: identical everywhere -> zero divergences -> interchangeable.
    result = socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu1b"]])
    assert result["verdict"]["interchangeable"] is True
    assert result["verdict"]["swaps_required"] == 0
    assert result["verdict"]["blocking"] == []


def test_socket_union_raises_on_mixed_scope(stm_conn, stm_refs):
    with pytest.raises(ValueError):
        socket_union(stm_conn, refs=[stm_refs["mcu1"], stm_refs["mcu3"]])


def test_socket_union_by_family_package_group(stm_conn):
    result = socket_union(stm_conn, family="STM32F4", package="LQFP64")
    assert len(result["parts"]) == 3
    assert result["package"] == "LQFP64"
    assert result["family"] == "STM32F4"


# ─────────────────────────────────────────────────────────────────────────────
# af_conflicts
# ─────────────────────────────────────────────────────────────────────────────


def test_af_conflicts_double_claim(stm_conn, stm_refs):
    conflicts = af_conflicts(
        stm_conn,
        stm_refs["mcu1"],
        {
            "29": {"signal": "USART3_TX", "af_index": 7},
            "30": {"signal": "USART3_TX", "af_index": 7},
        },
    )
    double_claims = [c for c in conflicts if c["kind"] == "double_claim"]
    assert len(double_claims) == 1
    assert double_claims[0]["positions"] == ["29", "30"]
    assert double_claims[0]["peripheral"] == "USART3"


def test_af_conflicts_unavailable_af(stm_conn, stm_refs):
    conflicts = af_conflicts(
        stm_conn, stm_refs["mcu1"], {"12": {"signal": "USART1_TX", "af_index": 99}}
    )
    assert len(conflicts) == 1
    assert conflicts[0]["kind"] == "unavailable_af"
    assert conflicts[0]["position"] == "12"


def test_af_conflicts_conflict_free_assignment(stm_conn, stm_refs):
    conflicts = af_conflicts(
        stm_conn,
        stm_refs["mcu1"],
        {
            "12": {"signal": "USART1_TX", "af_index": 7},
            "13": {"signal": "USART1_RX", "af_index": 7},
        },
    )
    assert conflicts == []


def test_af_conflicts_raises_on_unknown_ref(stm_conn):
    with pytest.raises(ValueError):
        af_conflicts(stm_conn, "NONEXISTENT999", {})
