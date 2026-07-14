"""M7f-D Library Fill + Prepare/Complete-All: annotate a project's references and fill each
placed schematic component's identity fields from the shared Stockroom library, byte-preservingly.

The compute is ported by behavior from the retired PyQt `nd_library_fill.py` (the one hard-Qt
module, which is why its ~25 name/text helpers were re-homed into `library_core` first), but it is
re-homed onto Stockroom's own layers, with two faithful changes the rewrite forces:

  1. The match library is Stockroom's one-JSON-per-part `PartRecord` set (via `library_match_records`),
     NOT the retired flat `MySymbols` symbol file. Every complete Stockroom part carries an MPN and a
     symbol name (the complete-to-add gate), so a component matches EXACTLY by its lib_id symbol name
     or by a real MPN. (Fuzzy value+footprint auto-matching, which the retired flat library supported
     via a symbol Value that Stockroom does not store on the record, is intentionally out of the auto
     pass; the per-ref manual fill covers that residual by letting the user pick the library part.)
  2. Every `.kicad_sch` write routes through Stockroom's byte-preserving `SexpDocument` (via the
     existing `kicad.schematic` `Schematic`/`SymbolInstance` seam and, for annotation, a direct node
     walk), never `LM.set_symbol_*` + `os.replace`. Only the atoms that actually change are rewritten,
     so a re-run is a byte-identical no-op and the diff is minimal.

Annotation sets the reference in BOTH forms KiCad keeps in sync on a placed instance: the display
`(property "Reference" "R?")` value AND every `(instances (project (path (reference "R?")))))` atom.
Missing the instances form would leave KiCad showing the new number while the netlist path still
carries "R?". Only a reference whose prefix is `[A-Za-z_]+` (so `#PWR?` / `#FLG?` power+flag symbols
are left to KiCad's own power-ref handling, matching the retired reference) is numbered, project-wide
unique against every already-used designator.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re
from typing import Iterable

from stockroom.kicad.schematic import Schematic
from stockroom.library_core import qualify_footprint, qualify_symbol, symbol_name_ref
from stockroom.model.category import category_nickname
from stockroom.sexp.document import SexpDocument, SexpNode

# Field key -> the property name carried in the PROJECT schematic (KiCad's own field names). Value
# is deliberately absent: a fill never rewrites a component's Value (that is the user's design intent).
FILL_PROPERTY: dict[str, str] = {
    "mpn": "MPN",
    "manufacturer": "Manufacturer",
    "datasheet": "Datasheet",
    "description": "Description",
    "footprint": "Footprint",
}

# The identity properties a placed component needs to be "complete" for the completion passport, in
# passport order. Footprint + the four identity fields; the 3D-model / footprint-file DISK resolution
# is a library concern (the audit measures it), so the schematic passport measures the directly
# readable set, mirroring the retired reference's M0 passport.
COMPLETION_FIELDS: tuple[tuple[str, str], ...] = (
    ("Footprint", "Footprint"),
    ("MPN", "MPN"),
    ("Manufacturer", "Manufacturer"),
    ("Datasheet", "Datasheet"),
    ("Description", "Description"),
)

# A value counts as "blank" (so filling it is a fill, not an overwrite) when it is empty or one of
# KiCad's placeholder tokens. Mirrors identity._PLACEHOLDERS + the retired _BLANKS.
_BLANKS = {"", "~", "*", "-", "n/a", "na", "none", "value"}

# An unannotated reference is "<prefix>?" with an alphabetic/underscore prefix; an annotated one is
# "<prefix><digits>". A "#PWR?" power reference is deliberately NOT matched (KiCad annotates power
# refs itself), matching the retired nd_project_health annotate scope.
_UNANNOTATED = re.compile(r"^([A-Za-z_]+)\?$")
_ANNOTATED_INSTANCE = re.compile(r'\(\s*reference\s+"([A-Za-z_]+\d+)"')
_ANNOTATED_PROPERTY = re.compile(r'\(property\s+"Reference"\s+"([A-Za-z_]+\d+)"')


def _is_blank(val) -> bool:
    return str(val or "").strip().lower() in _BLANKS


# -- shared library match index (from Stockroom PartRecords) -------------------


def library_match_records(parts: Iterable) -> list[dict]:
    """Build the fill match index from the shared library's `PartRecord`s.

    Each record is flattened to what matching + filling need: the symbol name a placed instance's
    lib_id resolves against, the real MPN, and the identity values a match would write. The footprint
    is carried as its bare stem plus the category nickname so a fill can qualify it to
    `SR-<slug>:<stem>` (the KiCad-correct link into Stockroom's per-category footprint library). The
    datasheet value is the source URL (what a schematic Datasheet property should hold), never the
    on-disk file name. A part missing a symbol name is still indexed for MPN matching.
    """
    out: list[dict] = []
    for p in parts:
        try:
            nickname = category_nickname(p.category)
        except ValueError:
            # A record with a category outside the fixed taxonomy cannot yield a valid KiCad library
            # link (the nickname qualifies the footprint + lib_id). Keep the part for its identity
            # fills (MPN/Manufacturer/Datasheet/Description, which do NOT need the nickname) but drop
            # its symbol/footprint so a fill never writes a bogus ":name" lib_id or footprint. A
            # corrupt category is a library-side problem the doctor surfaces; it must not silently
            # discard the whole part nor crash the Prepare.
            nickname = ""
        symbol = getattr(p, "symbol", None)
        footprint = getattr(p, "footprint", None)
        datasheet = getattr(p, "datasheet", None)
        # The schematic Datasheet property holds a URL or a local file path; prefer the source URL,
        # falling back to the on-disk file name (what the complete-to-add gate actually requires) so
        # a part with a datasheet file but no URL can still complete the component.
        ds = ""
        if datasheet is not None:
            ds = (datasheet.source_url or datasheet.file or "").strip()
        out.append({
            "id": p.id,
            # Without a nickname the symbol cannot be qualified into a valid lib_id, so drop it (an
            # MPN match + identity fills still work); the footprint stem is dropped for the same reason.
            "name": ((symbol.name if symbol else "") or "") if nickname else "",
            "mpn": (p.mpn or "").strip(),
            "manufacturer": (p.manufacturer or "").strip(),
            "datasheet": ds,
            "description": (p.description or "").strip(),
            "footprint_stem": ((footprint.name if footprint else "") or "") if nickname else "",
            "nickname": nickname,
            "category": p.category,
            "display_name": p.display_name,
        })
    return out


def match_component(comp: dict, index: list[dict]) -> dict:
    """Match one placed project component against the library index.

    Returns {"ref", "part": dict|None, "confidence"}:
      - "symbol" - the component's lib_id symbol name equals a library part's symbol name;
      - "mpn"    - else its strict MPN equals a library part's MPN;
      - "none"   - otherwise (part is None).
    A symbol match wins over an MPN match (a placed instance's symbol identity is the strongest link).
    """
    ref = comp.get("ref", "")
    sym_name = symbol_name_ref(comp.get("lib_id") or "")
    if sym_name:
        for part in index:
            if part["name"] and part["name"] == sym_name:
                return {"ref": ref, "part": part, "confidence": "symbol"}
    props = comp.get("props") or {}
    smpn = _strict_mpn(props)
    if smpn:
        for part in index:
            if part["mpn"] and part["mpn"] == smpn:
                return {"ref": ref, "part": part, "confidence": "mpn"}
    return {"ref": ref, "part": None, "confidence": "none"}


def _strict_mpn(props: dict) -> str | None:
    # A component's real MPN from a dedicated property (never the Value fallback), reusing the
    # projects.identity rule so audit / BOM / fill read a component's part number identically.
    from stockroom.projects.identity import strict_mpn

    return strict_mpn(props)


def proposed_changes(part: dict, props: dict) -> list[dict]:
    """The per-field changes a matched library `part` would make to a component with `props`.

    A change is proposed for each identity field the library carries whose value differs from the
    component's current property value. `kind` is "fill" when the current value is blank/placeholder,
    else "overwrite". The footprint is qualified to `SR-<slug>:<stem>` so the fill lands the KiCad
    library link, not a bare stem.
    """
    proposed = {
        "MPN": part.get("mpn"),
        "Manufacturer": part.get("manufacturer"),
        "Datasheet": part.get("datasheet"),
        "Description": part.get("description"),
        "Footprint": (qualify_footprint(part["footprint_stem"], part["nickname"])
                      if part.get("footprint_stem") else ""),
    }
    # A component may already carry its part number under an ALTERNATE KiCad field (e.g. "Manufacturer
    # Part Number" instead of "MPN"). Completion measures MPN via the strict multi-key rule, so the
    # MPN "old" value must use that same rule: otherwise an existing MPN under another key reads as
    # blank here and Complete-All inserts a SECOND, duplicate "MPN" property.
    strict = _strict_mpn(props)
    changes: list[dict] = []
    for prop, new in proposed.items():
        new = str(new or "").strip()
        if not new:
            continue
        old = str(props.get(prop, "") or "")
        if prop == "MPN" and strict:
            old = strict  # a part number under any recognized key counts as already present
        if old.strip() == new:
            continue
        changes.append({
            "prop": prop, "old": old, "new": new,
            "kind": "fill" if _is_blank(old) else "overwrite",
        })
    return changes


def build_fill_plan(components: list[dict], index: list[dict], sheet_of: dict) -> dict:
    """Turn matched components into a reviewable plan.

    Returns {"items": [item], "summary": {...}} where each item is
    {ref, sheet, confidence, part_id, changes: [FieldChange], default_selected}. `default_selected` is
    True only when the match is confident and every proposed change is a fill (never an overwrite), so
    a headless Complete-All fills blanks without clobbering user-set values. `sheet_of` maps ref ->
    sheet display path. Unmatched components (no library part) contribute to `summary.no_match`.
    """
    items: list[dict] = []
    no_match = 0
    for comp in components or []:
        ref = comp.get("ref", "")
        match = match_component(comp, index)
        part = match["part"]
        if part is None:
            no_match += 1
            continue
        changes = proposed_changes(part, comp.get("props") or {})
        if not changes:
            continue
        default_selected = all(c["kind"] == "fill" for c in changes)
        items.append({
            "ref": ref, "sheet": sheet_of.get(ref, ""),
            "confidence": match["confidence"], "part_id": part["id"],
            "changes": changes, "default_selected": default_selected,
        })
    return {
        "items": items,
        "summary": {
            "components": len(components or []),
            "matched": len(items),
            "no_match": no_match,
            "fields": sum(len(i["changes"]) for i in items),
        },
    }


# -- completion passport (schematic-instance scoped) --------------------------


def component_completion(comp: dict) -> dict:
    """Per-component completeness passport: {ref, missing: [prop], score, total, is_complete}. A field
    is present when its schematic property is non-blank (MPN via the strict rule so a Value fallback
    never counts). The 3D-model + footprint-file disk resolution is a library concern measured by the
    audit, not here."""
    props = comp.get("props") or {}
    present = {
        "Footprint": not _is_blank(comp.get("footprint") or props.get("Footprint")),
        "MPN": bool(_strict_mpn(props)),
        "Manufacturer": not _is_blank(props.get("Manufacturer")),
        "Datasheet": not _is_blank(props.get("Datasheet")),
        "Description": not _is_blank(props.get("Description")),
    }
    missing = [label for key, label in COMPLETION_FIELDS if not present[key]]
    return {"ref": comp.get("ref", ""), "missing": missing,
            "score": len(COMPLETION_FIELDS) - len(missing), "total": len(COMPLETION_FIELDS),
            "is_complete": not missing}


def project_completion(components: list[dict]) -> dict:
    """Roll up `component_completion` over every fillable component:
    {total, complete, incomplete_refs, missing_counts:{label:count}}."""
    passports = [component_completion(c) for c in (components or [])]
    miss: dict[str, int] = {}
    for p in passports:
        for label in p["missing"]:
            miss[label] = miss.get(label, 0) + 1
    return {
        "total": len(passports),
        "complete": sum(1 for p in passports if p["is_complete"]),
        "incomplete_refs": [p["ref"] for p in passports if not p["is_complete"]],
        "missing_counts": miss,
    }


def project_readiness(components: list[dict]) -> dict:
    """`project_completion` extended for the M7g Buildability verdict: adds `unannotated`
    (references still on a `<prefix>?` placeholder) and `missing_footprint` (components with
    no footprint). Those two are the PHYSICAL-BOARD hard blockers Buildability gates READY on,
    kept separate from orderability (MPN / stock), which the BOM signal owns. Pure; the current
    residual needs no library, so the verdict agrees with the Prepare section by construction."""
    comp = project_completion(components)
    comps = components or []
    comp["unannotated"] = sum(1 for c in comps if _UNANNOTATED.match((c.get("ref") or "")))
    comp["missing_footprint"] = comp["missing_counts"].get("Footprint", 0)
    return comp


# -- schematic read (placed instances only) -----------------------------------


def _is_power(ref: str, lib_id: str) -> bool:
    """A power / power-flag pseudo-symbol: not a fillable BOM part. Its reference starts with '#'
    (#PWR / #FLG) or its lib_id is in KiCad's `power:` library."""
    return ref.startswith("#") or lib_id.lower().startswith("power:")


def read_components(doc: SexpDocument, *, include_power: bool = False) -> list[dict]:
    """Every PLACED symbol instance in one parsed `.kicad_sch` as {ref, lib_id, value, footprint,
    props}. A placed instance carries a `(lib_id ...)` child; the `(lib_symbols ...)` cache symbols do
    not, so they are never returned (they must never be filled). Power/flag pseudo-symbols are excluded
    unless `include_power` (annotation may still want to see them, though their `#` refs are not
    numbered)."""
    out: list[dict] = []
    for sym in doc.root.find_all("symbol"):
        lib_node = sym.find("lib_id")
        if lib_node is None:
            continue  # a lib_symbols cache entry, never a placed instance
        lib_id = lib_node.children[1].value if len(lib_node.children) > 1 else ""
        props: dict = {}
        for prop in sym.find_all("property"):
            kids = prop.children
            if len(kids) >= 3:
                props[kids[1].value] = kids[2].value
        ref = props.get("Reference", "")
        if not include_power and _is_power(ref, lib_id):
            continue
        out.append({"ref": ref, "lib_id": lib_id, "value": props.get("Value", ""),
                    "footprint": props.get("Footprint", ""), "props": props})
    return out


# -- annotation (byte-preserving, both reference forms) -----------------------


def used_references(texts: Iterable[str]) -> set[str]:
    """Every already-assigned reference designator across the given sheet texts, seeded from BOTH
    forms KiCad keeps in sync: the display `(property "Reference" "R1")` and the instance
    `(reference "R1")`. Seeding from both prevents a fresh R? from reusing a number that only appears
    in one form (a duplicate designator on a legacy / instances-less file)."""
    used: set[str] = set()
    for text in texts:
        used |= set(_ANNOTATED_INSTANCE.findall(text))
        used |= set(_ANNOTATED_PROPERTY.findall(text))
    return used


def _reference_property(sym: SexpNode) -> SexpNode | None:
    for prop in sym.find_all("property"):
        kids = prop.children
        if len(kids) >= 3 and kids[1].value == "Reference":
            return prop
    return None


def _instance_reference_atoms(sym: SexpNode, value: str) -> list[SexpNode]:
    """Every `(instances (project (path (reference "<value>"))))` atom node inside one placed symbol
    whose current value equals `value` (the display reference KiCad keeps in sync per instance)."""
    return [n.children[1] for n in sym.iter_descendants()
            if n.name == "reference" and len(n.children) >= 2 and n.children[1].value == value]


def _symbol_unit(sym: SexpNode) -> str:
    unit = sym.find("unit")
    return unit.children[1].value if unit is not None and len(unit.children) >= 2 else "1"


def annotate_document(doc: SexpDocument, used: set[str]) -> int:
    """Assign the next free `<prefix><n>` to every unannotated single-unit, single-instance placed
    symbol in one parsed sheet, byte-preservingly, updating BOTH the display `(property "Reference")`
    value AND its `(instances (project (path (reference ...)))))` atom. `used` is the project-wide set
    of taken designators; each assigned reference is added to it so a later sheet cannot collide.
    Returns the count of instances annotated. Only a reference whose prefix is `[A-Za-z_]+` is numbered
    (a `#PWR?` power reference is left to KiCad); an already-numbered reference is a no-op.

    Two KiCad cases are DEFERRED to KiCad's own annotator rather than guessed (a wrong designator is
    worse than an unnumbered one, and KiCad annotates both correctly on open):

      - MULTI-UNIT: a multi-unit component is stored as separate `(symbol)` nodes sharing one
        designator, linked ONLY by that shared reference string, which does not exist yet while every
        unit reads "<prefix>?". Two "U?" nodes of the same lib_id are then indistinguishable from two
        independent single-unit uses, so packing them is genuinely ambiguous. A lib_id that appears
        with MORE THAN ONE distinct unit number among the unannotated symbols is left untouched.
      - REPEATED HIERARCHY: a symbol on a sub-sheet instantiated N times carries N distinct
        instance-path references that must each get a DIFFERENT designator; a symbol with more than one
        unannotated instance-path atom is left untouched.
    """
    placed = []
    unit_numbers: dict[str, set[str]] = {}
    for sym in doc.root.find_all("symbol"):
        lib_node = sym.find("lib_id")
        if lib_node is None:
            continue  # lib_symbols cache entry, never annotated
        ref_prop = _reference_property(sym)
        if ref_prop is None:
            continue
        cur = ref_prop.children[2].value
        m = _UNANNOTATED.match(cur)
        if not m:
            continue
        lib_id = lib_node.children[1].value if len(lib_node.children) > 1 else ""
        placed.append((sym, m.group(1), cur, lib_id, ref_prop))
        unit_numbers.setdefault(lib_id, set()).add(_symbol_unit(sym))
    # A lib_id used with >1 distinct unit among unannotated symbols is a multi-unit part in use.
    multi_unit_libs = {lib for lib, units in unit_numbers.items() if len(units) > 1}

    count = 0
    for sym, prefix, cur, lib_id, ref_prop in placed:
        atoms = _instance_reference_atoms(sym, cur)
        if lib_id in multi_unit_libs or len(atoms) > 1:
            continue  # multi-unit or repeated-hierarchy: defer to KiCad rather than mis-number
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        new_ref = f"{prefix}{n}"
        used.add(new_ref)
        ref_prop.children[2].set_value(new_ref, quote=True)
        for atom in atoms:  # keep the single instance-path reference in sync with the display value
            atom.set_value(new_ref, quote=True)
        count += 1
    return count


# -- fill (byte-preserving property + lib_id writes) --------------------------


def fill_document(doc: SexpDocument, changes_by_ref: dict[str, dict[str, str]],
                  lib_id_by_ref: dict[str, str] | None = None) -> int:
    """Write property changes (and, optionally, a repointed `(lib_id ...)`) onto the placed instances
    of one parsed `.kicad_sch`, byte-preservingly.

    `changes_by_ref` = {ref: {prop: new_value}}. `lib_id_by_ref` = {ref: lib_id} repoints a placed
    instance's symbol link. Only an atom whose current value actually differs is rewritten (so a
    re-fill is a byte-identical no-op), and a property absent on the instance is inserted (via the
    schematic seam). Returns the count of instances that changed. The `(lib_symbols ...)` cache is
    never touched: `Schematic.instances` yields only nodes carrying a `(lib_id ...)`.
    """
    lib_id_by_ref = lib_id_by_ref or {}
    sch = Schematic(doc)
    changed = 0
    for inst in sch.instances:
        ref = inst.reference
        props = changes_by_ref.get(ref)
        new_lib = lib_id_by_ref.get(ref)
        did = False
        if new_lib and inst.lib_id != new_lib:
            inst.set_lib_id(new_lib)
            did = True
        for prop, val in (props or {}).items():
            if (inst.get_property(prop) or "") != val:
                inst.set_property(prop, val)
                did = True
        if did:
            changed += 1
    return changed


def lib_id_for(part: dict) -> str:
    """The qualified schematic `(lib_id ...)` for a matched library part: `SR-<slug>:<symbol name>`,
    or "" when the part carries no symbol name (only an MPN)."""
    return qualify_symbol(part["name"], part["nickname"]) if part.get("name") else ""
