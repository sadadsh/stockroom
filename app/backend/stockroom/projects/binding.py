"""Durable placement bindings: which Stockroom library part a PLACED component is bound to.

Punch 17's last gap. Before this, assigning a library part to a placement only wrote identity
FIELDS into the schematic, so the link existed nowhere: a re-annotate renumbered the reference
the assignment was made against, a Value edit changed what the matcher would guess next time,
and nothing could be re-verified later. A binding is the link itself, stored durably.

Two facts decide the design, and both are registry DATA rather than a branch in this module
(owner, 2026-07-24: "a capability a tool lacks is data on the adapter"):

  1. WHAT IDENTIFIES A PLACEMENT. Not the reference designator, which annotation rewrites. A
     KiCad placed `(symbol ...)` carries a `(uuid ...)` that annotation never touches (verified
     against a real KiCad V10 sheet); Altium's counterpart is a component's `UNIQUEID`. A
     placement that supplies neither falls back to a key that SAYS it is weak (`ref:R1`), so a
     weak key can never be mistaken for a strong one.

  2. WHERE THE BINDING LIVES. Wherever the tool's own placements can carry it. Stockroom writes
     `.kicad_sch` through the byte-preserving sexp layer, so a KiCad binding is a hidden field
     ON the placement: written in the same transaction as the fill that created it, carried to a
     peer by the project's own git, and impossible to disagree with the design because it IS the
     design. Stockroom never writes Altium binary, so an Altium binding is kept on the Stockroom
     project record instead -- while a component placed from Stockroom's own DbLib still arrives
     carrying the field, because Altium copies the DbLib column onto the placement.

The READ path below therefore needs no per-tool branch at all: prefer the placement's own field,
fall back to the record. Only `writes_into_design` is consulted on the write side.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from stockroom.eda.registry import get_tool

# Reserved private keys stamped into a placement's `props`. `props` is a dict built fresh by each
# reader and consumed by field-name lookups, so a key that is not a real EDA field name cannot
# collide with one and is never written back into a design file (every writer writes an explicit
# field list). Mirrors the existing `_sr_library_part_id` convention in projects/bom.py.
PLACEMENT_KEY = "_sr_placement_key"
BOUND_PART = "_sr_bound_part_id"

# The prefix that marks a fallback key derived from a reference designator. Self-describing on
# purpose: such a key does NOT survive a re-annotate, and code (or a human) reading the stored
# map has to be able to tell that without knowing how it was produced.
WEAK_PREFIX = "ref:"


def field_for(tool_key: str) -> str:
    """The placement field carrying the Stockroom part id for `tool_key`."""
    return get_tool(tool_key).placement_binding.field


def writes_into_design(tool_key: str) -> bool:
    """Whether Stockroom can stamp a binding onto this tool's placements. False means the
    binding is stored on the project record instead; it is never a silent no-op."""
    return get_tool(tool_key).placement_binding.writable


def unwritable_reason(tool_key: str) -> str:
    """Why this tool's design cannot carry the binding, for the user rather than silence."""
    return get_tool(tool_key).placement_binding.reason


def is_weak_key(key: str) -> bool:
    """True for a key derived from a reference designator, which a re-annotate invalidates."""
    return str(key or "").startswith(WEAK_PREFIX)


def placement_key(comp: dict) -> str:
    """The durable identity of one placement: the tool's own per-placement id when it has one,
    else a self-describing `ref:<designator>` fallback, else "" for a placement with neither.

    A key already stamped into `props` wins, because downstream stages hand components on as
    (ref, lib_id, props) triples that have dropped the uuid; without this, a second pass would
    silently degrade a strong key to a weak one.
    """
    props = comp.get("props") or {}
    stamped = str(props.get(PLACEMENT_KEY, "") or "").strip()
    if stamped:
        return stamped
    uid = str(comp.get("uuid") or "").strip()
    if uid:
        return uid
    ref = str(comp.get("ref") or props.get("Reference", "") or "").strip()
    return f"{WEAK_PREFIX}{ref}" if ref else ""


def bound_part_id(comp: dict) -> str:
    """The library part id this placement is bound to, after `resolve`. "" when unbound."""
    return str((comp.get("props") or {}).get(BOUND_PART, "") or "").strip()


def stored_for(rec, tool_key: str) -> dict[str, str]:
    """The project record's stored bindings for one tool (a copy; never the live dict)."""
    return dict((getattr(rec, "bindings", None) or {}).get(tool_key, {}))


def merged_bindings(rec, tool_key: str, updates: dict[str, str]) -> dict[str, dict[str, str]]:
    """The record's whole bindings map with `updates` applied to `tool_key`.

    A blank part id UNBINDS that placement rather than storing an empty string, so "assign
    nothing" and "assigned to a part whose id happens to be empty" cannot be confused. Returns a
    new map and never mutates the record: persisting is the caller's decision, inside its own
    transaction.
    """
    out = {tool: dict(m) for tool, m in (getattr(rec, "bindings", None) or {}).items()}
    tool_map = out.setdefault(tool_key, {})
    for key, part_id in (updates or {}).items():
        key = str(key or "").strip()
        if not key:
            continue
        part_id = str(part_id or "").strip()
        if part_id:
            tool_map[key] = part_id
        else:
            tool_map.pop(key, None)
    return out


def resolve(comps, tool_key: str, stored: dict[str, str] | None = None) -> list[dict]:
    """Stamp every placement's durable key and its resolved binding into its `props`, in place.

    Precedence is the whole point: the placement's OWN field wins over the project record. The
    design file is the truth, so a record entry that disagrees with it is stale by definition,
    and preferring the record would silently overrule what the user's schematic actually says.

    Returns the same list so it can be used inline.
    """
    field = field_for(tool_key)
    stored = stored or {}
    for comp in comps or []:
        props = comp.setdefault("props", {})
        key = placement_key(comp)
        if key:
            props[PLACEMENT_KEY] = key
        native = str(props.get(field, "") or "").strip()
        part_id = native or (str(stored.get(key, "") or "").strip() if key else "")
        if part_id:
            props[BOUND_PART] = part_id
        else:
            props.pop(BOUND_PART, None)
    return list(comps or [])
