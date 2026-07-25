"""M7f-D Library Fill + Prepare/Complete-All: annotate a project's references and fill each
placed schematic component's identity fields from the shared Stockroom library, byte-preservingly.

The compute is ported by behavior from the retired PyQt `nd_library_fill.py` (the one hard-Qt
module, which is why its ~25 name/text helpers were re-homed into `library_core` first), but it is
re-homed onto Stockroom's own layers, with two faithful changes the rewrite forces:

  1. The match library is Stockroom's one-JSON-per-part `PartRecord` set (via `library_match_records`),
     NOT the retired flat `MySymbols` symbol file. A component matches by its lib_id symbol name, but
     ONLY when that name identifies exactly one part (see `library_match_records`), else by a real MPN.
     A part that reuses a shared KiCad stock symbol -- every passive does, because
     `resolve_passive_assets` files passives against the installed stock libraries rather than copying
     files -- therefore matches by MPN only. Value+package matching for those generic placements is a
     separate tier, not yet built; until it is, such a component is an honest `no_match` that the
     per-ref manual fill covers by letting the user pick the library part.
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

from stockroom.component_value import parse_component_value, same_component_value
from stockroom.kicad.schematic import Schematic
from stockroom.library_core import symbol_name_ref
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


def _lib_id(ref) -> str:
    """The `<lib>:<name>` reference a record's `AssetRef` actually holds, or "" when it does not hold
    a container-plus-entry reference (a file-shaped asset such as a 3D model, or an empty slot).

    Never re-derived from the part's category: a passive's symbol and footprint are KiCad STOCK
    references (`Device:R`, `Resistor_SMD:R_0402_1005Metric`) that live in the installed KiCad
    libraries, NOT in Stockroom's `SR-<slug>` category libraries, so qualifying them with the category
    nickname produced a reference KiCad cannot resolve at all. Building the reference here from the
    ref's own `lib` + `name` also makes a bogus `":name"` structurally impossible, which is what the
    old nickname-dropping guard existed to prevent.
    """
    if ref is None:
        return ""
    lib = (ref.lib or "").strip()
    name = (ref.name or "").strip()
    return f"{lib}:{name}" if lib and name else ""


# The spec rows a passive's value can live under, most specific first. These are the exact Title Case
# labels `PassiveSpec.to_specs` emits, so the reader and the writer cannot drift apart.
_VALUE_SPEC_KEYS: tuple[str, ...] = ("Resistance", "Capacitance", "Inductance", "Value")


def _value_spec(specs) -> str:
    for key in _VALUE_SPEC_KEYS:
        val = str((specs or {}).get(key, "") or "").strip()
        if val:
            return val
    return ""


# The ratings that separate two parts of the SAME value and package. Two library resistors can both be
# genuinely "10k 0402" and differ only here, which is why value plus package can never be an identity;
# it is also the information a person needs in order to choose between them, so the candidate list
# carries it and shows whichever of these actually differ.
_DISCRIMINATING_SPEC_KEYS: tuple[str, ...] = (
    "Tolerance", "Power", "Voltage", "Dielectric", "Temperature Coefficient",
)


def _discriminating_specs(specs) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _DISCRIMINATING_SPEC_KEYS:
        val = str((specs or {}).get(key, "") or "").strip()
        if val:
            out[key] = val
    return out


def library_match_records(parts: Iterable) -> list[dict]:
    """Build the fill match index from the shared library's `PartRecord`s.

    Each record is flattened to what matching + filling need: the symbol name a placed instance's
    lib_id resolves against, the real MPN, the identity values a match would write, and the exact
    `<lib>:<name>` references the record holds for its symbol and footprint (what a fill writes into
    the schematic verbatim). The datasheet value is the source URL (what a schematic Datasheet
    property should hold), never the on-disk file name. A part missing a symbol name is still indexed
    for MPN matching.

    `symbol_is_identity` is the flag matching turns on: True only when this part's symbol name
    genuinely names THIS part. That needs two things at once, and the first is the one that matters:

      - OWNERSHIP: the symbol lives in the Stockroom category library this part's own assets are
        filed into (`SR-<slug>`). A stock library entry such as `Device:R` is shared by every
        resistor in existence, so it cannot identify a part no matter how the library is populated.
      - UNIQUENESS: no other part in this library carries the same symbol name. A secondary guard
        only; uniqueness alone is naive, because a library holding exactly one resistor makes the
        stock name `R` unique and would restore the wrong-part match.
    """
    out: list[dict] = []
    for p in parts:
        try:
            nickname = category_nickname(p.category)
        except ValueError:
            # A category outside the fixed taxonomy has no Stockroom library, so this part cannot own
            # its symbol and forfeits the symbol tier (it still matches by MPN and still fills every
            # identity field, and its stored references are still written verbatim, because they do
            # not depend on the category). A corrupt category is a library-side problem the doctor
            # surfaces; it must not silently discard the part nor crash the Prepare.
            nickname = ""
        # The KiCad bundle explicitly: a project fill writes KiCad lib_ids into a
        # `.kicad_sch`, so it must read the KiCad assets, not whatever the record happens
        # to carry first. (This was `getattr(p, "symbol", None)`, which after the per-EDA
        # cutover would return None forever and silently match NOTHING.)
        kicad = p.assets_for("kicad")
        symbol = kicad.symbol
        footprint = kicad.footprint
        datasheet = getattr(p, "datasheet", None)
        # The schematic Datasheet property holds a URL or a local file path; prefer the source URL,
        # falling back to the on-disk file name (what the complete-to-add gate actually requires) so
        # a part with a datasheet file but no URL can still complete the component.
        ds = ""
        if datasheet is not None:
            ds = (datasheet.source_url or datasheet.file or "").strip()
        out.append({
            "id": p.id,
            "name": (symbol.name if symbol else "") or "",
            "mpn": (p.mpn or "").strip(),
            "manufacturer": (p.manufacturer or "").strip(),
            "datasheet": ds,
            "description": (p.description or "").strip(),
            "symbol_lib_id": _lib_id(symbol),
            "footprint_lib_id": _lib_id(footprint),
            # A record has no dedicated value field: a passive's value is a display spec row that
            # `PassiveSpec.to_specs` writes ("Resistance": "10 kOhm"), so the candidate tier reads it
            # from there. "Value" is accepted last for a record whose specs came from a vendor pull.
            "value": _value_spec(getattr(p, "specs", None)),
            "package": _eia_case((getattr(p, "specs", None) or {}).get("Package", "")),
            "specs": _discriminating_specs(getattr(p, "specs", None)),
            # Ownership on its own; uniqueness is folded in below, once the whole index is known.
            "symbol_is_identity": bool(nickname and symbol and (symbol.lib or "").strip() == nickname),
            "nickname": nickname,
            "category": p.category,
            "passive": bool(getattr(p, "passive", False)),
            "display_name": p.display_name,
        })
    # UNIQUENESS, library-wide: a symbol name carried by more than one owning part names none of them.
    owned: dict[str, int] = {}
    for rec in out:
        if rec["symbol_is_identity"]:
            owned[rec["name"]] = owned.get(rec["name"], 0) + 1
    for rec in out:
        if rec["symbol_is_identity"] and owned.get(rec["name"], 0) > 1:
            rec["symbol_is_identity"] = False
    return out


def match_component(comp: dict, index: list[dict]) -> dict:
    """Match one placed project component against the library index.

    Returns {"ref", "part": dict|None, "confidence"}:
      - "symbol" - the component's lib_id symbol name equals the symbol name of a library part that
                   IDENTIFIES itself by that name (see `symbol_is_identity`);
      - "mpn"    - else its strict MPN equals a library part's MPN;
      - "none"   - otherwise (part is None).
    A symbol match wins over an MPN match (a placed instance's symbol identity is the strongest link).

    The symbol tier deliberately compares the BARE name across libraries, not the whole lib_id, so a
    component still placed from an older library is matched and its `(lib_id ...)` repointed at the
    Stockroom entry. That is only safe because the tier now requires the library part to own its
    symbol: matching bare names alone gave every generic `Device:R` in a project the first Stockroom
    resistor at the highest confidence tier, which silently wrote a wrong MPN into the schematic (and,
    through `bom.library_enrich`, a wrong manufacturer, price and stock into the BOM).
    """
    ref = comp.get("ref", "")
    sym_name = symbol_name_ref(comp.get("lib_id") or "")
    if sym_name:
        for part in index:
            if part["symbol_is_identity"] and part["name"] == sym_name:
                return {"ref": ref, "part": part, "confidence": "symbol"}
    props = comp.get("props") or {}
    smpn = _strict_mpn(props)
    if smpn:
        for part in index:
            if part["mpn"] and part["mpn"] == smpn:
                return {"ref": ref, "part": part, "confidence": "mpn"}
    return {"ref": ref, "part": None, "confidence": "none"}


# -- candidate tier (a filtered PICK list, never an auto-assignment) -----------
#
# A generic placement cannot be identified, but it can be NARROWED, and that is what turns the owner's
# scenario ("a bunch of passives from the default library") into one safe decision instead of dozens of
# manual picks. Value plus package is deliberately NOT promoted to an identity: a library can hold
# several parts that are all genuinely "10k 0402" and differ only in tolerance, power rating or
# manufacturer, so any auto-pick among them is a coin flip written into the user's schematic.

# Ranked strongest first. The rank is the tier's index, so ordering and naming cannot drift apart.
CANDIDATE_TIERS: tuple[str, ...] = ("value+footprint", "value+package", "value")

# A standalone 4-digit run in a footprint name or package spec is the EIA case code
# ("Resistor_SMD:R_0402_1005Metric" -> "0402"). Anchored on non-digits so the 5-digit 01005 case is not
# silently truncated to a wrong 4-digit code, and taken leftmost so the EIA code wins over the metric
# code that follows it. Both sides of a comparison run through this same extractor, so they cannot
# disagree about what "the package" means.
_EIA_CASE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _eia_case(text: str) -> str:
    m = _EIA_CASE.search(str(text or ""))
    return m.group(1) if m else ""


def candidate_matches(comp: dict, index: list[dict]) -> list[dict]:
    """Ranked library parts a user could reasonably assign to a placement the identity tiers could not
    match, as [{part_id, display_name, mpn, description, confidence}] strongest first.

    Empty for a component that IS identified (there is nothing to guess), for an unreadable Value, and
    for every part whose symbol reference differs from the one the schematic already places. That last
    filter is the safety property: a candidate carries the SAME symbol, so accepting it repoints
    nothing and only fills identity fields, and it cannot offer a capacitor for a resistor symbol
    however well the numbers happen to line up.
    """
    if match_component(comp, index)["part"] is not None:
        return []
    lib_id = (comp.get("lib_id") or "").strip()
    props = comp.get("props") or {}
    value = props.get("Value", "")
    if not lib_id or parse_component_value(value) is None:
        return []
    placed_fp = str(props.get("Footprint") or comp.get("footprint") or "").strip()
    placed_case = _eia_case(placed_fp)
    out: list[dict] = []
    for part in index:
        if part["symbol_lib_id"] != lib_id:
            continue
        if not same_component_value(value, part.get("value")):
            continue
        part_fp = part.get("footprint_lib_id") or ""
        if placed_fp and part_fp and placed_fp == part_fp:
            tier = "value+footprint"
        elif placed_case and placed_case == (part.get("package") or _eia_case(part_fp)):
            tier = "value+package"
        else:
            tier = "value"
        out.append({
            "part_id": part["id"], "display_name": part["display_name"], "mpn": part["mpn"],
            "description": part["description"], "confidence": tier,
            "_specs": part.get("specs") or {},
        })
    # Tier first, then display name, so the list is stable across runs and across machines (never
    # insertion order, which follows whatever order the store happened to yield records in).
    out.sort(key=lambda c: (CANDIDATE_TIERS.index(c["confidence"]), c["display_name"], c["part_id"]))
    # What DISTINGUISHES these candidates from each other. Several library parts can be equally good
    # matches on value and package (all genuinely "10k 0402") and differ only in tolerance or power
    # rating, in which case the evidence tier is identical on every row and tells the user nothing.
    # Surfacing exactly the ratings that DIFFER is what makes the choice possible rather than a
    # coin flip: a rating every candidate shares is noise and is left out.
    varying = [key for key in _DISCRIMINATING_SPEC_KEYS
               if len({c["_specs"].get(key, "") for c in out}) > 1]
    for cand in out:
        specs = cand.pop("_specs")
        # A rating the part's own name already states is not repeated: a row reading "10k 0402 1%" next
        # to a separate "1%" says the same thing twice. Compared as whole whitespace-separated tokens,
        # never as a substring, so a "1%" rating is not swallowed by a name containing "11%".
        shown = {tok.casefold() for tok in str(cand["display_name"] or "").split()}
        cand["distinguish"] = [specs[key] for key in varying
                               if specs.get(key) and specs[key].casefold() not in shown]
    return out


# -- grouping: identical placements are ONE decision ---------------------------

# A designator splits into its letter prefix and its number so R10 sorts after R9. A plain string sort
# would interleave them, and these ref lists are shown to the user and written into commit messages.
_REF_PARTS = re.compile(r"^([A-Za-z_#]*)(\d*)")


def ref_sort_key(ref: str) -> tuple[str, int, str]:
    m = _REF_PARTS.match(str(ref or ""))
    prefix, digits = (m.group(1), m.group(2)) if m else ("", "")
    return prefix, int(digits) if digits else -1, str(ref or "")


def group_placements(components: list[dict]) -> list[dict]:
    """Collapse placements that are the same part into one group, as [{key, lib_id, value, footprint,
    refs, count}] in a deterministic order.

    Two placements group together only when their symbol, Value and Footprint all agree, because those
    three are exactly what a user reads as "the same component". Differing footprints stay apart even
    at the same value: they are different physical parts.
    """
    groups: dict[tuple[str, str, str], dict] = {}
    for comp in components or []:
        props = comp.get("props") or {}
        lib_id = (comp.get("lib_id") or "").strip()
        value = str(props.get("Value", "") or "")
        footprint = str(props.get("Footprint") or comp.get("footprint") or "")
        key = (lib_id, value, footprint)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"key": "␟".join(key), "lib_id": lib_id, "value": value,
                                   "footprint": footprint, "refs": [], "count": 0}
        group["refs"].append(comp.get("ref", ""))
        group["count"] += 1
    for group in groups.values():
        group["refs"].sort(key=ref_sort_key)
    return sorted(groups.values(), key=lambda g: (g["lib_id"], g["value"], g["footprint"]))


def _strict_mpn(props: dict) -> str | None:
    # A component's real MPN from a dedicated property (never the Value fallback), reusing the
    # projects.identity rule so audit / BOM / fill read a component's part number identically.
    from stockroom.projects.identity import strict_mpn

    return strict_mpn(props)


def proposed_changes(part: dict, props: dict) -> list[dict]:
    """The per-field changes a matched library `part` would make to a component with `props`.

    A change is proposed for each identity field the library carries whose value differs from the
    component's current property value. `kind` is "fill" when the current value is blank/placeholder,
    else "overwrite". The Footprint is the `<lib>:<name>` reference the record actually holds, written
    verbatim so the schematic points at the library that really contains that footprint.
    """
    proposed = {
        "MPN": part.get("mpn"),
        "Manufacturer": part.get("manufacturer"),
        "Datasheet": part.get("datasheet"),
        "Description": part.get("description"),
        "Footprint": part.get("footprint_lib_id") or "",
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
    """The schematic `(lib_id ...)` a fill repoints a matched component at: the `<lib>:<name>`
    reference the library record actually holds, or "" when it holds no symbol reference (MPN only).

    Verbatim, never re-qualified with the category nickname: a passive's symbol is the KiCad stock
    `Device:R`, and `SR-Resistors` contains no symbol named `R`, so re-qualifying pointed the placed
    instance at an entry that does not exist and KiCad could no longer resolve the symbol.
    """
    return part.get("symbol_lib_id") or ""
