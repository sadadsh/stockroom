"""M7h KiField bulk-field editor: a derived rows-by-fields grid over a project's placed
schematic components, editable and reinserted byte-preservingly.

Read side (`build_field_grid`): turn the placed components (read across every sheet via
`projects.fill.read_components`) into a table. One row per unique reference designator, one
column per field name that appears on ANY component (canonical KiCad fields ordered first,
then the common identity fields, then the rest alphabetically), every row normalized to carry
every column (blank when the component lacks the field) so the grid header is uniform.

Reference is the row identity and is READ-ONLY: a designator is renamed by annotation, which
also keeps each `(instances (project (path (reference ...))))` atom in sync; a plain property
write here would move the display value while leaving the netlist path reference stale. A ref
that maps to more than one component whose fields DISAGREE is a duplicate-designator anomaly
the health audit owns; that row is surfaced non-editable so a bulk write is never silently
applied to two distinct components at once. An unannotated ref (ends with "?") is likewise
non-editable (annotate first). Multi-unit symbols and hierarchical reuse (nodes that share a
ref with identical fields) merge into one editable row: `fill_document` writes the same value
onto every node of that ref, which is the correct KiCad component-level semantics.

Write side (`field_changes_by_ref`): validate a batch of {ref, field, value} cell edits against
the grid (a blank field name, the read-only Reference field, or a non-editable/unknown ref is
refused with a ValueError the router maps to 400) and return {ref: {field: value}} for
`projects.fill.fill_document`, which performs the byte-preserving write (inserting an absent
property, rewriting only a genuinely changed atom, skipping the lib_symbols cache and power
pseudo-symbols). Adding a brand-new field is just an edit whose field name is not yet a column.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re

# Column display order: KiCad's own built-in fields first, then the common identity fields,
# then every remaining field alphabetically. Reference leads (it is the row identity) but is
# never editable.
_PRIORITY = ("Reference", "Value", "Footprint", "Datasheet", "Description", "MPN", "Manufacturer")
_PRIORITY_SET = frozenset(_PRIORITY)
READONLY_FIELDS = frozenset({"Reference"})

# A value that reads as "no real value" (empty or a KiCad placeholder). Two nodes of one
# component that carry a field where one is a real value and the other is blank/placeholder are
# NOT in conflict: a blank and an absent field are the same thing. Mirrors identity._PLACEHOLDERS
# + fill._BLANKS so the grid, the BOM, and Complete-All agree on what counts as filled.
_BLANK_VALUES = {"", "~", "*", "-", "n/a", "na", "none", "value"}


def _is_blank(value) -> bool:
    return str(value or "").strip().lower() in _BLANK_VALUES

_NUM = re.compile(r"(\d+)")


def _natural_key(ref: str):
    """Sort references the human way: alpha prefix then numeric suffix (R2 before R10). Each
    chunk is a (type-rank, value) pair so a digit run (rank 0) never compares against a letter
    run (rank 1); an unannotated 'R?' sorts after the numbered refs of its prefix."""
    return tuple(
        (0, int(p)) if p.isdigit() else (1, p)
        for p in _NUM.split(ref or "")
        if p != ""
    )


def _order_columns(names) -> list[str]:
    present = set(names)
    ordered = [n for n in _PRIORITY if n in present]
    ordered += sorted(n for n in present if n not in _PRIORITY_SET)
    return ordered


def build_field_grid(components) -> dict:
    """Build the derived {columns, readonly_columns, rows, summary} grid from placed components.

    `components` is the concatenation of `projects.fill.read_components` across every sheet, each
    dict optionally carrying a `_sheet` (its relative sheet path). Rows are natural-sorted by ref.
    """
    groups: dict[str, list[dict]] = {}
    for c in components or []:
        groups.setdefault(c.get("ref", ""), []).append(c)

    all_fields: set[str] = set()
    rows: list[dict] = []
    for ref, nodes in groups.items():
        names: set[str] = set()
        for n in nodes:
            names |= set((n.get("props") or {}).keys())
        all_fields |= names
        merged: dict[str, str] = {}
        conflicts: list[str] = []
        for name in names:
            # Compare only the REAL (non-blank / non-placeholder) values across the ref's nodes: a
            # field carried by only some unit-nodes, or blank on some and filled on others, is not a
            # conflict (a blank and an absent field are the same). Genuinely DIFFERING real values
            # across a shared ref are (a duplicate-designator anomaly), which locks the row.
            vals = {
                str((n.get("props") or {}).get(name)).strip()
                for n in nodes
                if name in (n.get("props") or {}) and not _is_blank((n.get("props") or {}).get(name))
            }
            if len(vals) <= 1:
                merged[name] = next(iter(vals)) if vals else ""
            else:
                merged[name] = ""
                conflicts.append(name)
        unannotated = ref.endswith("?")
        editable = bool(ref) and not unannotated and not conflicts
        rows.append({
            "ref": ref,
            "sheet": nodes[0].get("_sheet", ""),
            "lib_id": nodes[0].get("lib_id", ""),
            "unannotated": unannotated,
            "editable": editable,
            "conflicts": sorted(conflicts),
            "instances": len(nodes),
            "fields": merged,
        })

    columns = _order_columns(all_fields)
    for row in rows:  # normalize every row to carry every column (blank when absent)
        row["fields"] = {col: row["fields"].get(col, "") for col in columns}
    rows.sort(key=lambda r: _natural_key(r["ref"]))
    summary = {
        "components": len(rows),
        "editable": sum(1 for r in rows if r["editable"]),
        "unannotated": sum(1 for r in rows if r["unannotated"]),
        "duplicate": sum(1 for r in rows if r["conflicts"] and not r["unannotated"]),
    }
    return {
        "columns": columns,
        "readonly_columns": [c for c in columns if c in READONLY_FIELDS],
        "rows": rows,
        "summary": summary,
    }


def field_changes_by_ref(rows, edits) -> dict:
    """Validate a batch of {ref, field, value} cell edits against the grid `rows` and return the
    {ref: {field: value}} map for `fill_document`. Raises ValueError (mapped to 400) for a blank
    field name, the read-only Reference field, or an unknown / non-editable reference. `value`
    None becomes an empty string (clearing a field). Adding a not-yet-a-column field is allowed."""
    by_ref = {r["ref"]: r for r in rows}
    # Map case-folded field name -> its canonical existing spelling, so an edit that case-collides
    # with an existing column ("mpn" vs "MPN") UPDATES that column instead of inserting a SECOND,
    # duplicate property (KiCad keeps both; identity._normalize_keys then case-folds them into one
    # order-dependent slot, masking the value). Reference's variants also canonicalize, so the
    # read-only guard below catches "reference" too.
    canon: dict[str, str] = {}
    for r in rows:
        for name in (r.get("fields") or {}):
            canon.setdefault(name.casefold(), name)
    changes: dict[str, dict[str, str]] = {}
    for edit in edits or []:
        ref = str(edit.get("ref") or "").strip()
        field = str(edit.get("field") or "").strip()
        value = edit.get("value", "")
        value = "" if value is None else str(value)
        if not field:
            raise ValueError("a field name must not be blank")
        field = canon.get(field.casefold(), field)  # snap to an existing column's exact case
        if field in READONLY_FIELDS:
            raise ValueError(f"the {field} field is set by annotation, not the field editor")
        row = by_ref.get(ref)
        if row is None:
            raise ValueError(f"no component {ref!r} in this project")
        if not row["editable"]:
            if row["unannotated"]:
                raise ValueError(f"component {ref!r} is not annotated; annotate the project first")
            raise ValueError(
                f"component {ref!r} shares its designator with another; resolve the duplicate first"
            )
        changes.setdefault(ref, {})[field] = value
    return changes
