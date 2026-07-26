"""stm/authority.py - Layer B: pure, computed-on-read facts over a Layer A
sqlite3.Connection (stm-viewer workstream, Phase 3, INTERFACES.md sections 2/7).

This file is owned entirely by Phase 3 (Phase 1 does not create it). It ports
`_five_v`, `_cubemx_regex`, and `resolve_part` from legacy/tools/stm32_authority.py
(the last stripped of every board/switch-fabric field per INTERFACES.md section 6's
DO-NOT-REUSE row, and rebased on the Phase-1 `ref_name` column), and writes five
NEW functions the compatibility surface needs:
`pin_signature`, `package_family_union`, `socket_union`, `af_conflicts`, and
`compatibility_suggestions`. No API, no SVG, no switch semantics - pure Python +
parameterized SQL against the frozen Phase-1/2 schema. Every computation stays at
(mcu, package, position) grain; every union is scoped by ONE package plus an
explicit family scope - one family or several (owner amendment 2026-07-23: a
cross-family set on one footprint IS the build-card goal), never a bare package
string sweeping in families nobody named. socket_union still raises on a
cross-package set (a socket is a physical footprint).
"""

from __future__ import annotations

import re
import sqlite3

from stockroom.stm.families import FAMILY_NOT_5V

_OSC_CAVEAT_PINS = {"PC14", "PC15", "PH0", "PH1"}  # FT except in oscillator mode
_GPIO_NAME = re.compile(r"^P[A-Z]\d+$")


# ─────────────────────────────────────────────────────────────────────────────
# Ported verbatim (pure, no schema dependency)
# ─────────────────────────────────────────────────────────────────────────────


def five_v(fam_gpios: set, peripherals) -> dict | None:
    """Per-position 5V-tolerance across the parts present. A GPIO is structurally FT
    (5V-tolerant, digital mode) unless it is in its family's non-5V set - which
    differs by family, so a socket position can be 5V-safe under one part and not
    another. `tolerant` is the conservative answer (safe on ALL parts present).
    PORT of legacy/tools/stm32_authority.py:474 `_five_v`, verbatim logic."""
    by_fam: dict = {}
    gpios: set = set()
    for fam, nm in fam_gpios:
        if fam not in FAMILY_NOT_5V or not _GPIO_NAME.match(str(nm)):
            continue
        gpios.add(nm)
        ft = nm not in FAMILY_NOT_5V[fam]
        by_fam[fam] = by_fam.get(fam, True) and ft  # AND when >1 GPIO/family here
    if not by_fam:
        return None  # non-GPIO position (power/ground/reset/boot)
    tolerant = all(by_fam.values())
    caveat = ""
    if gpios & _OSC_CAVEAT_PINS:
        caveat = "osc-mode"
    elif tolerant and any(str(p).startswith("ADC") for p in peripherals):
        caveat = "analog-mode"
    return {"tolerant": tolerant, "by_family": dict(sorted(by_fam.items())), "caveat": caveat}


def _cubemx_regex(ref_name: str) -> str:
    """Expand a CubeMX ref name into a prefix regex against a real ordering part
    number: '(E-G)' -> a char set [EG], 'x' -> any char. E.g. 'STM32F407V(E-G)Tx'
    matches 'STM32F407VGT6'. PORT of legacy/tools/stm32_authority.py:1874,
    verbatim (pure string/regex expansion, no schema dependency)."""
    out, i, s = [], 0, ref_name.upper()
    while i < len(s):
        c = s[i]
        if c == "(":
            j = s.find(")", i)
            if j == -1:
                out.append(re.escape(c))
                i += 1
                continue
            out.append("[" + re.escape(s[i + 1 : j].replace("-", "")) + "]")
            i = j + 1
        elif c == "X":
            out.append(".")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "^" + "".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_part (schema + semantic adaptation - PORT with every board/switch-
# fabric field stripped per INTERFACES.md section 6, and the legacy MCU-
# identity column renamed to ref_name per INTERFACES.md section 1)
# ─────────────────────────────────────────────────────────────────────────────


def _resolve_mcu_row(conn: sqlite3.Connection, mpn: str) -> sqlite3.Row | None:
    """The MPN-resolution ladder (exact ref_name, then a unique prefix, then a
    regex-expanded scan), shared by resolve_part/af_conflicts/socket_union so the
    "how do I turn a ref-or-MPN string into one mcu row" logic lives in ONE place."""
    row = conn.execute(
        "SELECT id, package_name, family, line, ref_name FROM mcu WHERE ref_name = ?",
        (mpn,),
    ).fetchone()
    if row is not None:
        return row
    q = mpn.strip().upper()
    cand = conn.execute(
        "SELECT id, package_name, family, line, ref_name FROM mcu "
        "WHERE UPPER(ref_name) LIKE ? ORDER BY ref_name LIMIT 2",
        (q + "%",),
    ).fetchall()
    if len(cand) == 1:
        return cand[0]
    for candidate in conn.execute("SELECT id, package_name, family, line, ref_name FROM mcu"):
        if re.match(_cubemx_regex(candidate["ref_name"]), q):
            return candidate
    return None


def _peripheral_roots(signals) -> list[str]:
    """The distinct peripheral-instance root of each signal (e.g. 'ADC1_IN14' ->
    'ADC1'), sorted. Mirrors the legacy tool's `re.split(r"[_-]", sig)[0].upper()`
    convention, used here only for five_v's ADC-caveat check."""
    roots = {re.split(r"[_-]", str(sig))[0].upper() for sig in signals if sig}
    return sorted(roots)


def resolve_part(conn: sqlite3.Connection, mpn: str) -> dict | None:
    """Resolve one exact MCU (by ref_name, a unique prefix, or a real MPN matched
    against the ref_name's expanded pattern) down to its per-pin story: roles,
    declared functions, and a five_v value per GPIO pin. STRIPPED of every
    board/switch-fabric field the legacy tool returned, and of the internal
    switch-fabric identity/net-mapping helper calls those depended on (see
    INTERFACES.md section 6's DO-NOT-REUSE row for the full excluded list) -
    this is a per-pin facts view, not a switch-fabric resolution. Returns None
    on a miss."""
    row = _resolve_mcu_row(conn, mpn)
    if row is None:
        return None

    mcu_id, package, family, line, part = (
        row["id"],
        row["package_name"],
        row["family"],
        row["line"],
        row["ref_name"],
    )

    pins: list[dict] = []
    for pin_row in conn.execute(
        "SELECT id, physical_pin_number, canonical_pin_name, raw_pin_name, electrical_class "
        "FROM mcu_package_pin WHERE mcu_id = ? ORDER BY physical_pin_number",
        (mcu_id,),
    ):
        pin_id = pin_row["id"]
        roles_rows = [
            {"role_name": r["role_name"], "role_class": r["role_class"]}
            for r in conn.execute(
                "SELECT role_name, role_class FROM pin_role WHERE mcu_package_pin_id = ?",
                (pin_id,),
            )
        ]
        func_rows = conn.execute(
            "SELECT signal, io_modes FROM pin_function WHERE mcu_package_pin_id = ?",
            (pin_id,),
        ).fetchall()
        functions_rows = [{"signal": f["signal"], "io_modes": f["io_modes"]} for f in func_rows]
        peripherals = _peripheral_roots(f["signal"] for f in func_rows)

        fv = None
        if pin_row["electrical_class"] == "io":
            fv = five_v({(family, pin_row["canonical_pin_name"])}, peripherals)

        pins.append(
            {
                "position": pin_row["physical_pin_number"],
                "canonical_pin_name": pin_row["canonical_pin_name"],
                "raw_pin_name": pin_row["raw_pin_name"],
                "electrical_class": pin_row["electrical_class"],
                "roles": roles_rows,
                "functions": functions_rows,
                "five_v": fv,
            }
        )

    return {"part": part, "package": package, "family": family, "line": line, "pins": pins}


# ─────────────────────────────────────────────────────────────────────────────
# pin_signature (NEW - replaces the legacy board-identity helper)
# ─────────────────────────────────────────────────────────────────────────────


def pin_signature(pin_facts: dict) -> frozenset[str]:
    """A pin's drop-in identity at one position: the frozenset of its role names,
    its declared function signal names (pin_function - CubeMX's per-device default
    assignment), its AF-mux signal names (pin_alternate_function - every
    alternative the mux offers, not just the active one), and its AF peripheral
    names. Replaces the legacy board-identity helper (INTERFACES.md section 6's
    DO-NOT-REUSE row) with a plain, switch-free identity - no electrical/switch
    semantics. `pin_facts` is {"roles": [...],
    "functions": [...], "af_signals": [...], "peripherals": [...]} (any key may be
    omitted/empty). Function signals are folded in alongside the AF menu so a
    divergence in a part's DECLARED assignment (e.g. one part's ADC1_IN14 vs.
    another's ADC1_IN15 at the same physical position, where neither AF-mux menu
    differs at all) is visible to package_family_union/socket_union, not only an
    AF-swappable divergence."""
    names: set[str] = set()
    names.update(pin_facts.get("roles") or [])
    names.update(pin_facts.get("functions") or [])
    names.update(pin_facts.get("af_signals") or [])
    names.update(pin_facts.get("peripherals") or [])
    return frozenset(names)


def _pin_facts(conn: sqlite3.Connection, mcu_package_pin_id: int) -> dict:
    """The raw per-pin facts pin_signature needs, read from Layer A for one
    mcu_package_pin row."""
    roles = [
        r["role_name"]
        for r in conn.execute(
            "SELECT role_name FROM pin_role WHERE mcu_package_pin_id = ?",
            (mcu_package_pin_id,),
        )
    ]
    functions = [
        r["signal"]
        for r in conn.execute(
            "SELECT signal FROM pin_function WHERE mcu_package_pin_id = ? "
            "AND signal IS NOT NULL AND signal <> ''",
            (mcu_package_pin_id,),
        )
    ]
    af_signals = [
        r["signal"]
        for r in conn.execute(
            "SELECT DISTINCT signal FROM pin_alternate_function WHERE mcu_package_pin_id = ?",
            (mcu_package_pin_id,),
        )
    ]
    peripherals = [
        r["peripheral"]
        for r in conn.execute(
            "SELECT DISTINCT peripheral FROM pin_alternate_function "
            "WHERE mcu_package_pin_id = ? AND peripheral IS NOT NULL",
            (mcu_package_pin_id,),
        )
    ]
    return {"roles": roles, "functions": functions, "af_signals": af_signals, "peripherals": peripherals}


def _signature_key(signature: frozenset[str]) -> str:
    """A stable, sorted string key for a pin_signature frozenset - used as a dict
    key (histograms, vectors) since a frozenset itself is not a useful/JSON-stable
    key for test assertions or DTO serialization."""
    return "|".join(sorted(signature))


def _position_sort_key(position: str):
    """Numeric positions sort numerically; alnum (BGA) positions sort after every
    numeric position, then lexicographically - so a mixed numeric/alnum position
    set (never both on one real package, but harmless to support) is still
    deterministic."""
    try:
        return (0, int(position))
    except ValueError:
        return (1, position)


# ─────────────────────────────────────────────────────────────────────────────
# package_family_union + compatibility_suggestions
# ─────────────────────────────────────────────────────────────────────────────


def package_family_union(conn: sqlite3.Connection, package: str, family: str) -> dict:
    """GENERALIZES legacy `pin_identity_histograms` (stm32_db.py:683): reuses its
    SELECT-DISTINCT + GROUP-BY aggregation SHAPE, but scopes by package AND family
    TOGETHER (never a bare package string) and uses `pin_signature` in place of
    the legacy board-identity helper. Returns {positions: [{position, side,
    bga_row, bga_col, histogram: {signature_key: distinct_mcu_count}}], total_mcus}."""
    mcu_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM mcu WHERE package_name = ? AND family = ?", (package, family)
        )
    ]
    total_mcus = len(mcu_ids)

    positions: dict[str, dict] = {}
    for mcu_id in mcu_ids:
        for pin in conn.execute(
            "SELECT id, physical_pin_number, lqfp_side, bga_row, bga_col "
            "FROM mcu_package_pin WHERE mcu_id = ?",
            (mcu_id,),
        ):
            pos = pin["physical_pin_number"]
            entry = positions.setdefault(
                pos,
                {
                    "position": pos,
                    "side": pin["lqfp_side"],
                    "bga_row": pin["bga_row"],
                    "bga_col": pin["bga_col"],
                    "histogram": {},
                },
            )
            key = _signature_key(pin_signature(_pin_facts(conn, pin["id"])))
            entry["histogram"][key] = entry["histogram"].get(key, 0) + 1

    ordered = sorted(positions.values(), key=lambda e: _position_sort_key(e["position"]))
    return {"positions": ordered, "total_mcus": total_mcus}


def compatibility_suggestions(
    conn: sqlite3.Connection,
    package: str,
    family: str | None = None,
    tolerance: int = 0,
    families: list[str] | None = None,
) -> list[dict]:
    """Groups the MCUs in the (package, families) scope by their FULL per-position
    pin-divergence vector (COMPAT-04). The largest exact-match group is the
    "baseline" tier; every other group is "divergent", carrying the count of
    positions where its vector differs from the baseline. `tolerance` merges a
    divergent group into the baseline when its divergence count is <= tolerance.
    The scope may span several families (owner amendment 2026-07-23) - a group is
    then free to mix families, which is exactly the cross-family drop-in discovery
    the build-card concept wants; the echoed `family` field joins the scope names."""
    scope_families = list(families or ([family] if family else []))
    if not scope_families:
        raise ValueError("compatibility_suggestions requires at least one family")
    family = " + ".join(sorted(scope_families))
    marks = ",".join("?" for _ in scope_families)
    mcu_rows = list(
        conn.execute(
            "SELECT id, ref_name FROM mcu "
            f"WHERE package_name = ? AND family IN ({marks}) ORDER BY ref_name",
            (package, *scope_families),
        )
    )
    all_positions = sorted(
        {
            r["physical_pin_number"]
            for r in conn.execute(
                "SELECT DISTINCT p.physical_pin_number FROM mcu_package_pin p "
                f"JOIN mcu m ON m.id = p.mcu_id WHERE m.package_name = ? AND m.family IN ({marks})",
                (package, *scope_families),
            )
        },
        key=_position_sort_key,
    )

    vectors: dict[str, tuple] = {}
    for row in mcu_rows:
        mcu_id, ref_name = row["id"], row["ref_name"]
        per_position: dict[str, str] = {}
        for pin in conn.execute(
            "SELECT id, physical_pin_number FROM mcu_package_pin WHERE mcu_id = ?", (mcu_id,)
        ):
            per_position[pin["physical_pin_number"]] = _signature_key(
                pin_signature(_pin_facts(conn, pin["id"]))
            )
        vectors[ref_name] = tuple(per_position.get(pos, "") for pos in all_positions)

    groups: dict[tuple, list[str]] = {}
    for ref_name, vector in vectors.items():
        groups.setdefault(vector, []).append(ref_name)

    def _group_sort_key(vector: tuple):
        members = sorted(groups[vector])
        return (-len(members), members[0])

    baseline_vector = min(groups, key=_group_sort_key) if groups else ()
    merged_refs = list(groups.get(baseline_vector, []))

    divergent_groups = []
    for vector, refs in groups.items():
        if vector == baseline_vector:
            continue
        divergence = sum(1 for a, b in zip(vector, baseline_vector) if a != b)
        if divergence <= tolerance:
            merged_refs.extend(refs)
        else:
            divergent_groups.append((vector, sorted(refs), divergence))

    import hashlib

    def _sig_id(vector: tuple) -> str:
        return hashlib.sha1("||".join(vector).encode("utf-8")).hexdigest()[:12]

    out = [
        {
            "signature_id": _sig_id(baseline_vector),
            "tier": "baseline",
            "package": package,
            "family": family,
            "refs": sorted(merged_refs),
            "divergent_positions": 0,
        }
    ]
    for vector, refs, divergence in sorted(divergent_groups, key=lambda g: g[1][0]):
        out.append(
            {
                "signature_id": _sig_id(vector),
                "tier": "divergent",
                "package": package,
                "family": family,
                "refs": refs,
                "divergent_positions": divergence,
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# socket_union (NEW) + af_conflicts (NEW)
# ─────────────────────────────────────────────────────────────────────────────


def _reconcile_divergence(by_mcu: dict, ref_by_mcu_id: dict) -> dict:
    """For one divergent position, decide the union's "required" declared signal
    (the mode across the parts present; a tie breaks to the alphabetically-first
    ref's own signal - a deterministic, documented convention, not a hardware
    rule), then check each non-conforming part's AF-mux menu for an option that
    carries that signal. swappable=True (with one swap entry per part that must
    change) only when EVERY non-conforming part has such an option."""
    functions_by_mcu = {
        mcu_id: (facts["functions"][0] if facts["functions"] else None)
        for mcu_id, facts in by_mcu.items()
    }
    counts: dict[str, int] = {}
    for sig in functions_by_mcu.values():
        if sig:
            counts[sig] = counts.get(sig, 0) + 1
    if not counts:
        return {
            "swappable": False,
            "swaps": [],
            "required_signal": "",
            "reason": "no declared signal to reconcile at this position",
        }
    max_count = max(counts.values())
    candidates = sorted(sig for sig, c in counts.items() if c == max_count)
    required_signal = candidates[0]
    if len(candidates) > 1:
        tied_refs = sorted(
            ref_by_mcu_id[mcu_id]
            for mcu_id, sig in functions_by_mcu.items()
            if sig in candidates
        )
        winner_mcu_id = next(
            mcu_id for mcu_id in by_mcu if ref_by_mcu_id[mcu_id] == tied_refs[0]
        )
        required_signal = functions_by_mcu[winner_mcu_id]

    swaps = []
    for mcu_id, facts in sorted(by_mcu.items(), key=lambda kv: ref_by_mcu_id[kv[0]]):
        if functions_by_mcu[mcu_id] == required_signal:
            continue
        match = next((af for af in facts["af_rows"] if af[1] == required_signal), None)
        if match is None:
            return {
                "swappable": False,
                "swaps": [],
                "required_signal": required_signal,
                "reason": (
                    f"{ref_by_mcu_id[mcu_id]} offers no alternate function carrying "
                    f"{required_signal} at this position"
                ),
            }
        swaps.append(
            {"ref": ref_by_mcu_id[mcu_id], "target_signal": required_signal, "via_af_index": match[0]}
        )
    return {"swappable": True, "swaps": swaps, "required_signal": required_signal, "reason": None}


def socket_union(
    conn: sqlite3.Connection,
    refs: list[str] | None = None,
    family: str | None = None,
    package: str | None = None,
    families: list[str] | None = None,
) -> dict:
    """The socket-union computation (INTERFACES.md section 2, COMPAT-01/02/03/05)
    at (mcu, package, position) grain. Resolves an explicit `refs` list (each via
    the same MPN-resolution ladder as resolve_part) OR selects a whole
    (families, package) group. Every part MUST share ONE package (a socket is a
    physical footprint) - raises ValueError on a cross-package set. Families MAY
    mix (owner amendment 2026-07-23: the build-card goal is exactly a cross-family
    socket on one footprint); each part keeps its own per-part grain, so a
    cross-family identity difference classifies divergent, never a silent merge.
    The result carries `families` (the sorted real scope) plus `family` (a
    joined display string, the single name when the scope is one family)."""
    if refs:
        rows = []
        for ref in refs:
            row = _resolve_mcu_row(conn, ref)
            if row is None:
                raise ValueError(f"unknown part: {ref}")
            rows.append(row)
    else:
        scope_families_in = list(families or ([family] if family else []))
        if not scope_families_in or not package:
            raise ValueError(
                "socket_union requires either refs or a package plus at least one family"
            )
        marks = ",".join("?" for _ in scope_families_in)
        rows = list(
            conn.execute(
                "SELECT id, package_name, family, line, ref_name FROM mcu "
                f"WHERE package_name = ? AND family IN ({marks}) ORDER BY ref_name",
                (package, *scope_families_in),
            )
        )
        if not rows:
            raise ValueError(
                f"no MCUs found for package={package} families={scope_families_in}"
            )

    scope_packages = {r["package_name"] for r in rows}
    if len(scope_packages) > 1:
        raise ValueError(
            "socket_union requires every part to share ONE package (a socket is a "
            f"physical footprint): got packages={sorted(scope_packages)}"
        )
    scope_package = next(iter(scope_packages))
    scope_family_list = sorted({r["family"] for r in rows})
    scope_family = " + ".join(scope_family_list)

    ref_by_mcu_id = {r["id"]: r["ref_name"] for r in rows}
    mcu_ids = list(ref_by_mcu_id)
    total = len(mcu_ids)

    per_position: dict[str, dict[int, dict]] = {}
    for mcu_id in mcu_ids:
        for pin in conn.execute(
            "SELECT id, physical_pin_number, canonical_pin_name, lqfp_side, bga_row, bga_col "
            "FROM mcu_package_pin WHERE mcu_id = ?",
            (mcu_id,),
        ):
            pos = pin["physical_pin_number"]
            functions = [
                r["signal"]
                for r in conn.execute(
                    "SELECT signal FROM pin_function WHERE mcu_package_pin_id = ? "
                    "AND signal IS NOT NULL AND signal <> ''",
                    (pin["id"],),
                )
            ]
            roles = [
                r["role_name"]
                for r in conn.execute(
                    "SELECT role_name FROM pin_role WHERE mcu_package_pin_id = ?", (pin["id"],)
                )
            ]
            af_rows = [
                (r["af_index"], r["signal"], r["peripheral"])
                for r in conn.execute(
                    "SELECT af_index, signal, peripheral FROM pin_alternate_function "
                    "WHERE mcu_package_pin_id = ?",
                    (pin["id"],),
                )
            ]
            per_position.setdefault(pos, {})[mcu_id] = {
                "canonical_pin_name": pin["canonical_pin_name"],
                "lqfp_side": pin["lqfp_side"],
                "bga_row": pin["bga_row"],
                "bga_col": pin["bga_col"],
                "roles": roles,
                "functions": functions,
                "af_rows": af_rows,
            }

    positions_out = []
    for pos in sorted(per_position, key=_position_sort_key):
        by_mcu = per_position[pos]
        present_on = len(by_mcu)
        geo_sample = next(iter(by_mcu.values()))
        signatures = {
            mcu_id: pin_signature(
                {
                    "roles": facts["roles"],
                    "functions": facts["functions"],
                    "af_signals": [s for _, s, _ in facts["af_rows"]],
                    "peripherals": [p for _, _, p in facts["af_rows"] if p],
                }
            )
            for mcu_id, facts in by_mcu.items()
        }
        distinct_sigs = set(signatures.values())

        if present_on < total:
            classification = "partial"
        elif len(distinct_sigs) <= 1:
            classification = "shared"
        else:
            classification = "divergent"

        per_part = [
            {
                "ref": ref_by_mcu_id[mcu_id],
                "canonical_pin_name": facts["canonical_pin_name"],
                "roles": facts["roles"],
                "functions": facts["functions"],
            }
            for mcu_id, facts in sorted(by_mcu.items(), key=lambda kv: ref_by_mcu_id[kv[0]])
        ]

        reconcile = None
        if classification == "divergent":
            reconcile = _reconcile_divergence(by_mcu, ref_by_mcu_id)

        positions_out.append(
            {
                "position": pos,
                "position_kind": "alnum" if geo_sample["bga_row"] else "numeric",
                "lqfp_side": geo_sample["lqfp_side"],
                "bga_row": geo_sample["bga_row"],
                "bga_col": geo_sample["bga_col"],
                "classification": classification,
                "present_on": present_on,
                "total": total,
                "per_part": per_part,
                "reconcile": reconcile,
            }
        )

    blocking = []
    swaps_required = 0
    for entry in positions_out:
        if entry["classification"] != "divergent":
            continue
        rec = entry["reconcile"] or {}
        if rec.get("swappable"):
            swaps_required += 1
        else:
            blocking.append(
                {
                    "position": entry["position"],
                    "signal": rec.get("required_signal", ""),
                    "reason": rec.get("reason", "unreconciled divergence"),
                }
            )
    verdict = {
        "interchangeable": len(blocking) == 0,
        "swaps_required": swaps_required,
        "blocking": blocking,
    }

    return {
        "parts": [ref_by_mcu_id[mcu_id] for mcu_id in mcu_ids],
        "resolved": [{"ref": ref_by_mcu_id[mcu_id]} for mcu_id in mcu_ids],
        "package": scope_package,
        "family": scope_family,
        "families": scope_family_list,
        "grain": "per-part",
        "positions": positions_out,
        "verdict": verdict,
    }


def af_conflicts(conn: sqlite3.Connection, ref: str, assignment: dict) -> list[dict]:
    """Given one resolved part and a client-held {position: {signal, af_index}}
    map, returns conflicts for (a) the same (peripheral, signal) pair claimed at
    more than one position, and (b) an (af_index, signal) a position's
    pin_alternate_function rows do not actually offer. No electrical/switch
    semantics - a pure AF-mux availability/collision check. Raises ValueError on
    an unresolvable `ref` (fail honestly, never a fabricated result)."""
    row = _resolve_mcu_row(conn, ref)
    if row is None:
        raise ValueError(f"unknown part: {ref}")
    mcu_id = row["id"]

    conflicts: list[dict] = []
    claims: dict[tuple[str, str], list[str]] = {}

    for position, want in assignment.items():
        signal = want.get("signal")
        af_index = want.get("af_index")
        pin_row = conn.execute(
            "SELECT id FROM mcu_package_pin WHERE mcu_id = ? AND physical_pin_number = ?",
            (mcu_id, position),
        ).fetchone()
        if pin_row is None:
            conflicts.append(
                {
                    "kind": "unknown_position",
                    "position": position,
                    "signal": signal,
                    "message": f"{ref} has no pin at position {position}",
                }
            )
            continue
        af_row = conn.execute(
            "SELECT peripheral FROM pin_alternate_function "
            "WHERE mcu_package_pin_id = ? AND af_index = ? AND signal = ?",
            (pin_row["id"], af_index, signal),
        ).fetchone()
        if af_row is None:
            conflicts.append(
                {
                    "kind": "unavailable_af",
                    "position": position,
                    "signal": signal,
                    "message": f"position {position} does not offer AF{af_index}={signal} on {ref}",
                }
            )
            continue
        key = (af_row["peripheral"], signal)
        claims.setdefault(key, []).append(position)

    for (peripheral, signal), positions in claims.items():
        if len(positions) > 1:
            conflicts.append(
                {
                    "kind": "double_claim",
                    "positions": sorted(positions),
                    "peripheral": peripheral,
                    "signal": signal,
                    "message": (
                        f"{peripheral} signal {signal} is assigned to more than one "
                        f"position: {', '.join(sorted(positions))}"
                    ),
                }
            )
    return conflicts
