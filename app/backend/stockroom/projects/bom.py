"""M7c: a grouped, optionally priced Bill of Materials for a registered KiCad project.

Grouping + cost are pure COMPUTE, clean-lifted from the retired PyQt app's
LibraryManager (which could not be imported: it is a Qt hub, so the ~20 dict-in/dict-out
functions were copied out). Two faithful changes from the original:

  1. the schematic is read through Stockroom's byte-preserving sexp layer
     (SexpDocument), never fp_render.parse_sexpr;
  2. the group key layers KiBoM value-normalization + do-not-fit / testpoint exclusion
     (projects/kibom.py, Decision 5) ON TOP of the app's MPN-primary grouping, so
     4.7k and 4700 merge and a fiducial drops, without disturbing MPN-primary +
     manufacturer-in-key + value-as-MPN promotion.

No kicad-cli is needed: grouping is offline. Pricing is a separate, injected
`price_lookup(mpn)` served by Stockroom's enrich layer (see enrichment_to_bom_lookup);
when it is absent or a lookup misses, the line stays honestly unpriced and a price is
never invented. Cost + procurement EXPORTS, the revision diff, sourcing-risk, and lead
time land in M7d.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from stockroom.projects import kibom
from stockroom.projects.identity import _PLACEHOLDERS, part_identity, strict_mpn
from stockroom.sexp.document import SexpDocument, SexpNode

# passives a fab stocks by value alone (a basic part when they carry no real MPN)
_BASIC_PREFIXES = {"R", "C", "L", "FB"}


def _natural_ref(ref: str):
    """Sort key so R2 < R10 (prefix, then numeric index)."""
    m = re.match(r"([A-Za-z_]+)(\d+)", ref or "")
    return (m.group(1), int(m.group(2))) if m else (ref or "", 0)


def is_basic_part(ref, value, mpn) -> bool:
    """A 'basic' part: a standard passive a fab stocks by value alone (R / C / L /
    ferrite bead with a value and no specific manufacturer part number). The offline
    analogue of JLCPCB's basic-vs-extended split."""
    if mpn and str(mpn).strip() and str(mpn).strip().lower() not in _PLACEHOLDERS:
        return False
    m = re.match(r"[A-Za-z]+", str(ref or ""))
    prefix = m.group(0).upper() if m else ""
    return prefix in _BASIC_PREFIXES and bool(str(value or "").strip())


def _dist_pn(r) -> str:
    """The distributor's own part number for a priced row, matched to its Source so an
    export can say 'order from {Source} by {this P/N}': LCSC -> lcsc_pn, Mouser ->
    mouser_pn, DigiKey -> digikey_pn. Falls back to whichever is present when the source
    is unknown, or '' when nothing was threaded."""
    src = (r.get("source") or "").strip().lower()
    lcsc = (r.get("lcsc_pn") or "").strip()
    mouser = (r.get("mouser_pn") or "").strip()
    digikey = (r.get("digikey_pn") or "").strip()
    if src == "lcsc":
        return lcsc or mouser or digikey
    if src == "mouser":
        return mouser or lcsc or digikey
    if src == "digikey":
        return digikey or mouser or lcsc
    return lcsc or mouser or digikey


# -- row primitives shared by procurement / export / diff (M7d) ----------------


def _bom_line_qty(r) -> int:
    """A BOM line's per-board quantity as a whole number: 'qty' (project BOM) or
    'total_qty' (consolidated). Anything unparseable folds to 0."""
    try:
        return int(float(r.get("qty", r.get("total_qty", 0)) or 0))
    except (TypeError, ValueError):
        return 0


def _row_refs(r) -> list:
    """The reference designators for a BOM row, from a project row (`refs`) or a
    consolidated row (`refs_by_board`), de-duplicated and naturally sorted."""
    if r.get("refs"):
        return sorted(set(r["refs"]), key=_natural_ref)
    out: list = []
    for refs in (r.get("refs_by_board") or {}).values():
        out.extend(refs)
    return sorted(set(out), key=_natural_ref)


def _row_is_passive(r) -> bool:
    """Whether a BOM row is a small SMT passive (R / C / L / ferrite bead) - the parts
    that suffer pick-and-place attrition on an assembly line. Keyed off the refdes prefix
    against the same _BASIC_PREFIXES set is_basic_part uses, but MPN-independent (a
    specific-MPN 0402 cap is still a passive). A row groups one part, so its refdes share
    a prefix; the first ref decides."""
    refs = _row_refs(r)
    if not refs:
        return False
    m = re.match(r"[A-Za-z]+", refs[0])
    return (m.group(0).upper() if m else "") in _BASIC_PREFIXES


def _lead_weeks(v):
    """Normalize a distributor lead-time value into whole weeks, or None when unknown.
    Providers disagree on shape: Mouser gives strings ("16 Weeks"), DigiKey gives a number
    of weeks, LCSC gives nothing. A numeric value is taken as weeks; a string is parsed for
    a leading count plus an optional unit (weeks default, days converted up), and anything
    without a parseable number ("In Stock", "", None) returns None - unknown, not a warning.
    Negative -> None (garbage); 0 stays 0 (in stock, not a lead risk). Days round UP to whole
    weeks so a lead time is never understated."""
    import math
    if isinstance(v, bool):  # a stray bool is not a duration
        return None
    if isinstance(v, (int, float)):
        return int(v) if v >= 0 else None
    if not isinstance(v, str):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", v)
    if not m:
        return None
    n = float(m.group(1))
    if n < 0:
        return None
    if re.search(r"\bday", v, re.IGNORECASE):
        return math.ceil(n / 7.0)
    return int(n)


# -- Package / RoHS derivation (the wide-BOM columns, offline) ------------------

# Two-terminal SMD body packages KiCad names without a size number (a diode's D_SMA), so the
# package deriver can still resolve them past a single-letter device-class prefix.
_SMD_BODY_PACKAGES = {"SMA", "SMB", "SMC", "MELF", "MINIMELF", "MICROMELF"}


def package_from_footprint(footprint: str) -> str:
    """A compact package code for the BOM's Package column, derived from a KiCad footprint
    name offline (no network). A passive footprint (R_0603_1608Metric, R_0402) yields its
    imperial EIA code (0603, 0402); an IC footprint (SOIC-8_3.9x4.9mm_P1.27mm, SOT-23) yields
    its package family (SOIC-8, SOT-23). Returns "" when the name carries no recognizable
    package (a blank is honest, never a guess); the library prefix (Resistor_SMD:) is stripped
    first. Display-only, so it is never a grouping key."""
    name = (footprint or "").split(":")[-1].strip()
    if not name:
        return ""
    m = re.match(r"^[A-Za-z]+_(\d{3,5})(?:_|$)", name)  # R_0603_1608Metric / R_0402 -> imperial code
    if m:
        return m.group(1)
    tokens = name.split("_")
    first = tokens[0]
    # A real package family carries a size number or a hyphen (SOT-23, SOIC-8, QFN-32, TO-92).
    if re.search(r"[-\d]", first):
        return first
    # A single-letter device-class prefix (a diode's D_SOD-123 / D_SMA) hides the package in the
    # next token; take it when it names a package (a hyphen/digit, or a known two-body SMD case).
    if len(first) == 1 and len(tokens) > 1:
        second = tokens[1]
        if re.search(r"[-\d]", second) or second.upper() in _SMD_BODY_PACKAGES:
            return second
    # A bare word (Crystal, MountingHole) is not a package -> honest blank.
    return ""


# Spec values that read as RoHS compliant vs not, matched case-insensitively against the value
# of any spec whose key names RoHS (Mouser "RoHS Status", LCSC compliance, a plain "RoHS" row).
_ROHS_YES = ("compliant", "yes", "compatible", "lead free", "lead-free", "rohs3", "rohs 3")
# Genuine non-compliance phrasing ONLY (not any "not"/"non" prefix, which also opens unknown
# statuses like "Not Applicable"/"None" that must never be read as a hard "No").
_ROHS_NO = ("non-compliant", "noncompliant", "not compliant", "non compliant")
# Explicit "no verdict" statuses a distributor emits for a part with no RoHS data: unknown, not
# a compliance verdict, so they map to blank rather than a fabricated Yes/No.
_ROHS_UNKNOWN = {"none", "n/a", "na", "not applicable", "not specified", "not reviewed",
                 "unknown", "tbd", "-"}


def rohs_from_specs(specs) -> str:
    """A compact RoHS verdict ("Yes" / "No" / "" ) for the BOM's RoHS column, read from a
    part's specs dict (Mouser/LCSC label the compliance in a "RoHS"-named key). Compliant
    values ("RoHS3 Compliant", "Lead Free", "Compliant", "Yes") map to "Yes"; genuinely
    non-compliant values ("Non-Compliant", "Not Compliant") to "No"; a no-verdict status
    ("Not Applicable", "None", "Unknown") or a missing/blank RoHS key to "" (unknown, never a
    guessed compliance); any other value passes through verbatim."""
    if not isinstance(specs, dict):
        return ""
    for key, val in specs.items():
        if "rohs" in str(key).lower():
            s = str(val or "").strip()
            low = s.lower()
            if not s or low in _ROHS_UNKNOWN:
                return ""
            if any(t in low for t in _ROHS_NO):
                return "No"
            if any(t in low for t in _ROHS_YES):
                return "Yes"
            return s
    return ""


# -- schematic read (Stockroom sexp, replacing fp_render.parse_sexpr) ----------


def _read_root(sch_path) -> SexpNode | None:
    try:
        root = SexpDocument.load(sch_path).root
    except Exception:  # noqa: BLE001 - a corrupt/missing file yields no components, never a crash
        return None
    return root if root.name == "kicad_sch" else None


def _token_is_yes(node: SexpNode | None) -> bool:
    """A KiCad flag token, true when present and not explicitly 'no': (dnp yes) and a
    bare (exclude_from_bom) are true; (dnp no) and an absent node are false."""
    if node is None:
        return False
    val = node.children[1].value if len(node.children) > 1 else "yes"
    return val != "no"


def _bom_components(sch_path) -> list:
    """Every real BOM component (ref, lib_id, props) in one .kicad_sch. Skips power / virtual
    symbols, in_bom=no / exclude_from_bom / dnp=yes parts, and the KiBoM exclude set
    (testpoints, fiducials, mounting holes, do-not-fit). [] for a non-schematic file. lib_id is
    carried so the library-combining step can match a component to its library part by symbol
    name, not just by an MPN the schematic may not carry."""
    root = _read_root(sch_path)
    if root is None:
        return []
    out = []
    for node in root.find_all("symbol"):
        lib_node = node.find("lib_id")
        lib_id = (
            lib_node.children[1].value
            if lib_node is not None and len(lib_node.children) > 1
            else ""
        )
        props: dict = {}
        for prop in node.find_all("property"):
            kids = prop.children
            if len(kids) >= 3:
                props[kids[1].value] = kids[2].value
        in_bom = True
        ib = node.find("in_bom")
        if ib is not None and len(ib.children) > 1 and ib.children[1].value == "no":
            in_bom = False
        if _token_is_yes(node.find("exclude_from_bom")):
            in_bom = False
        if _token_is_yes(node.find("dnp")):
            in_bom = False
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#") or lib_id.lower().startswith("power:") or not in_bom:
            continue
        part_name = lib_id.split(":")[-1]
        if kibom.is_excluded(ref, part_name, props.get("Footprint", "")):
            continue
        if kibom.is_do_not_fit(props):
            continue
        out.append((ref, lib_id, props))
    return out


# -- grouping (the app's MPN-primary logic + KiBoM value-normalization) --------


def _bom_from_components(comps, lookup=None,
                        enrich_fields=("manufacturer", "datasheet", "description"),
                        price_lookup=None) -> dict:
    """Group (ref, props) components into BOM lines, enrich blanks via `lookup`, flag
    basic parts, and (when `price_lookup` is given) price each line with an MPN and roll
    up a cost summary. Shared by the single-sheet and whole-project builders.

    Grouping is MPN-primary: a real manufacturer part number groups by that MPN; an IC
    with a manufacturer and no dedicated MPN promotes its Value to the MPN; everything
    else falls back to a (value, footprint, manufacturer) key whose value is
    KiBoM-normalized so 4.7k and 4700 merge (Decision 5). Two parts of the same value
    but different manufacturers stay distinct lines."""
    groups: dict = {}
    for comp in comps:
        # Accept either (ref, props) or (ref, lib_id, props): both the library-combining path and
        # the plain path pass (ref, lib_id, props); the 2-tuple form is tolerated defensively.
        ref, props = comp[0], comp[-1]
        lib_id = comp[1] if len(comp) == 3 else ""
        part_name = lib_id.split(":")[-1]
        ident = part_identity(props, fallback=props.get("Value", ""))
        value = (props.get("Value") or "").strip()
        smpn = strict_mpn(props)
        # An IC (non-passive) with a manufacturer often carries its real MPN in the
        # Value field. Promote it, but NEVER for a passive, whose Value is a value.
        if not smpn and ident["manufacturer"] and not is_basic_part(ref, value, None):
            smpn = value if value and value.lower() not in _PLACEHOLDERS else None
        # Fallback key on the KiBoM-normalized value + footprint + manufacturer, plus the symbol
        # family ONLY when the footprint is blank: a present footprint already discriminates part
        # type (so Device:R and Device:R_US on one footprint stay merged), while a blank footprint
        # needs the symbol to keep a Device:R "10k" and a Device:L "10k" apart (roadmap #9).
        footprint = props.get("Footprint", "")
        sym = kibom.normalize_symbol(part_name) if not footprint else ""
        key = smpn or (
            "VF", kibom.normalize_value(value), footprint, ident["manufacturer"] or "", sym,
        )
        g = groups.setdefault(key, {
            "mpn": smpn, "manufacturer": ident["manufacturer"],
            "datasheet": ident["datasheet"], "description": ident["description"],
            "value": props.get("Value", ""), "footprint": props.get("Footprint", ""),
            "part_name": part_name, "refs": []})
        if not g["part_name"] and part_name:  # prefer the first non-blank symbol name in the group
            g["part_name"] = part_name
        g["refs"].append(ref)

    if lookup:
        for g in groups.values():
            if g["mpn"] and any(not g.get(f) for f in enrich_fields):
                res = lookup(g["mpn"])
                if res:
                    for f in enrich_fields:
                        if not g.get(f) and res.get(f):
                            g[f] = res[f]

    rows = []
    for g in groups.values():
        refs = sorted(g["refs"], key=_natural_ref)
        rows.append({"refs": refs, "qty": len(refs), "value": g["value"],
                     "mpn": g["mpn"] or "", "manufacturer": g["manufacturer"] or "",
                     "has_real_mpn": bool(g["mpn"]),
                     "footprint": g["footprint"], "datasheet": g["datasheet"] or "",
                     "description": g["description"] or "", "part_name": g["part_name"] or "",
                     # Wide-BOM columns: package is derived offline from the footprint as a
                     # baseline (an authoritative enrich/library package overrides it below);
                     # rohs/category start blank and fill from the enrich layer or the library.
                     "package": package_from_footprint(g["footprint"]), "rohs": "", "category": "",
                     "basic": is_basic_part(refs[0] if refs else "", g["value"], g["mpn"])})
    rows.sort(key=lambda r: (r["value"].lower(), r["footprint"].lower(),
                             _natural_ref(r["refs"][0]) if r["refs"] else ("", 0)))

    priced = price_lookup is not None
    if priced:
        _price_rows(rows, price_lookup, "qty")

    out = {"rows": rows, "component_count": len(comps), "line_count": len(rows),
           "csv": _bom_project_csv(rows, priced)}
    if priced:
        out["cost"] = bom_cost_summary(rows)
    return out


# -- library combining: enrich components + price from the library ------------
#
# The KiCad schematic supplies the component list, refs, and quantities; the Stockroom library
# supplies the canonical part data (MPN, manufacturer, datasheet, footprint) AND, when a part was
# enriched at add time, its stored price breaks + stock. Combining the two produces a BOM that is
# complete and priced FROM YOUR OWN LIBRARY, offline, before ever touching a distributor.


def library_match_index(library_parts):
    """The fill match index (by symbol name + MPN) from the active profile's PartRecords, so a
    schematic component can be matched to its library part for the BOM."""
    from stockroom.projects import fill

    return fill.library_match_records(list(library_parts or ()))


def library_enrich(comps, match_index):
    """Fill each component's BLANK identity fields (MPN / Manufacturer / Datasheet / Description /
    Footprint) from its matching library part, so the BOM combines the KiCad schematic with the
    library. `comps` are (ref, lib_id, props) triples; returns (ref, lib_id, props) triples with
    blanks filled (never overwriting a value the schematic already carries, so a deliberate
    schematic override stands). lib_id is carried through so the grouping key keeps the symbol
    family (roadmap #9). An unmatched component passes through unchanged (honest)."""
    from stockroom.projects import fill

    out = []
    for ref, lib_id, props in comps:
        enriched = dict(props)
        if match_index:
            match = fill.match_component({"ref": ref, "lib_id": lib_id, "props": props}, match_index)
            if match["part"] is not None:
                for ch in fill.proposed_changes(match["part"], props):
                    if ch["kind"] == "fill":  # blanks only, never an overwrite
                        enriched[ch["prop"]] = ch["new"]
        out.append((ref, lib_id, enriched))
    return out


def library_price_index(library_parts) -> dict:
    """mpn -> the flat {price_breaks, unit_price, stock, manufacturer, datasheet, description, url,
    source} dict from a library part's STORED purchase data, so the BOM prices OFFLINE from the
    library. Only a part carrying price breaks or a stock figure is indexed; a part with identity
    but no price is skipped so the enrich layer can still fill it. Prefers a purchase that carries
    price breaks."""
    index: dict = {}
    for p in (library_parts or ()):
        mpn = (getattr(p, "mpn", "") or "").strip()
        if not mpn:
            continue
        purchases = list(getattr(p, "purchase", None) or [])
        best = next((pu for pu in purchases if getattr(pu, "price_breaks", None)), None)
        if best is None:
            best = purchases[0] if purchases else None
        breaks = []
        if best is not None:
            for b in (getattr(best, "price_breaks", None) or []):
                try:
                    breaks.append({"qty": int(b["qty"]), "price": float(b["price"])})
                except (KeyError, TypeError, ValueError):
                    continue
        stock = getattr(best, "stock", None) if best is not None else None
        if not breaks and stock is None:
            continue  # nothing priceable to contribute; leave it for the enrich layer
        entry: dict = {"source": "library"}
        if breaks:
            breaks.sort(key=lambda b: b["qty"])
            entry["price_breaks"] = breaks
            entry["unit_price"] = breaks[0]["price"]
        if stock is not None:
            entry["stock"] = stock
        if getattr(p, "manufacturer", ""):
            entry["manufacturer"] = p.manufacturer
        ds = getattr(p, "datasheet", None)
        if ds is not None and (ds.source_url or ds.file):
            entry["datasheet"] = ds.source_url or ds.file
        if getattr(p, "description", ""):
            entry["description"] = p.description
        if best is not None and getattr(best, "url", ""):
            entry["url"] = best.url
        # Wide-BOM columns from the part's captured specs / category, so a library-priced line
        # carries its package + RoHS + category without a network round-trip.
        specs = getattr(p, "specs", None)
        if isinstance(specs, dict):
            pkg = str(specs.get("Package") or "").strip()
            if pkg:
                entry["package"] = pkg
            rohs = rohs_from_specs(specs)
            if rohs:
                entry["rohs"] = rohs
        if getattr(p, "category", ""):
            entry["category"] = p.category
        index[mpn] = entry
    return index


def library_spec_index(library_parts) -> dict:
    """mpn -> {package, rohs, category} from a library part's captured specs + category, so a
    BOM line matched to a library part surfaces those wide-table columns even when the line is
    UNPRICED (library_price_index only indexes priced parts). Only non-blank fields are emitted;
    a part with no MPN, or nothing to contribute, is skipped."""
    index: dict = {}
    for p in (library_parts or ()):
        mpn = (getattr(p, "mpn", "") or "").strip()
        if not mpn:
            continue
        specs = getattr(p, "specs", None)
        entry: dict = {}
        if isinstance(specs, dict):
            pkg = str(specs.get("Package") or "").strip()
            if pkg:
                entry["package"] = pkg
            rohs = rohs_from_specs(specs)
            if rohs:
                entry["rohs"] = rohs
        cat = (getattr(p, "category", "") or "").strip()
        if cat:
            entry["category"] = cat
        if entry:
            index[mpn] = entry
    return index


def combined_price_lookup(library_parts, enrich_lookup=None):
    """A price_lookup(mpn) that prices from the LIBRARY first (offline, instant), then falls back
    to `enrich_lookup` (the network enrich layer) for an MPN the library cannot price. So the BOM
    combines the library's stored prices with live distributor data, never a fabricated price.
    Returns None when neither source can price anything, so `priced` stays honestly False."""
    lib = library_price_index(library_parts)
    if not lib and enrich_lookup is None:
        return None

    def lookup(mpn):
        hit = lib.get((mpn or "").strip())
        if hit is not None:
            return hit
        return enrich_lookup(mpn) if enrich_lookup is not None else None

    return lookup


def bom_from_project(sch_paths, lookup=None,
                     enrich_fields=("manufacturer", "datasheet", "description"),
                     price_lookup=None, library_index=None) -> dict:
    """A single BOM merged across EVERY sheet of a project (not just the root),
    grouping identical parts with summed quantity. Priced when `price_lookup` is given.
    When `library_index` is given, each component's blank identity fields are first filled
    from its matching library part (combining the schematic with the library)."""
    comps = []
    for p in (sch_paths or []):
        try:
            comps.extend(_bom_components(p))
        except Exception:  # noqa: BLE001 - an unreadable sheet drops out, never crashes the build
            continue
    if library_index:
        comps = library_enrich(comps, library_index)
    return _bom_from_components(comps, lookup, enrich_fields, price_lookup=price_lookup)


def bom_from_kicad_schematic(sch_path, lookup=None,
                             enrich_fields=("manufacturer", "datasheet", "description"),
                             price_lookup=None) -> dict:
    """Grouped BOM from one KiCad 6+ schematic (.kicad_sch). Skips power / virtual /
    excluded-from-BOM symbols, groups by MPN (else normalized value + footprint), and
    prices each MPN line when `price_lookup` is given. Returns {rows, component_count,
    line_count, csv}, plus a cost roll-up when priced; an error shape for a non-schematic."""
    root = _read_root(sch_path)
    if root is None:
        return {"error": "not a KiCad schematic (.kicad_sch)", "rows": [],
                "component_count": 0, "line_count": 0, "csv": ""}
    return _bom_from_components(_bom_components(sch_path), lookup, enrich_fields,
                               price_lookup=price_lookup)


def consolidated_bom(boards: dict, lookup=None, price_lookup=None) -> dict:
    """Merge the BOMs of several boards into one purchasing list. `boards` is
    {board_name: [.kicad_sch sheet paths]}. Groups by MPN (else normalized value +
    footprint) across ALL boards, sums quantity, and keeps the per-board breakdown +
    reference designators. Priced by total_qty when `price_lookup` is given. Read-only."""
    board_names = list(boards)
    merged: dict = {}
    for board, sheets in boards.items():
        for sheet in sheets:
            for r in bom_from_kicad_schematic(sheet)["rows"]:
                # Symbol family only when the footprint is blank (see _bom_from_components): a
                # present footprint already discriminates part type, so do not over-split it.
                sym = kibom.normalize_symbol(r.get("part_name") or "") if not r["footprint"] else ""
                key = r["mpn"] or ("VF", kibom.normalize_value(r["value"]), r["footprint"],
                                   r.get("manufacturer") or "", sym)
                m = merged.setdefault(key, {
                    "mpn": r["mpn"], "manufacturer": r["manufacturer"], "value": r["value"],
                    "has_real_mpn": bool(r["mpn"]),
                    "footprint": r["footprint"], "datasheet": r["datasheet"],
                    "description": r["description"], "part_name": r.get("part_name", ""),
                    "total_qty": 0, "per_board": {}, "refs_by_board": {}})
                m["total_qty"] += r["qty"]
                m["per_board"][board] = m["per_board"].get(board, 0) + r["qty"]
                m["refs_by_board"][board] = sorted(
                    set(m["refs_by_board"].get(board, []) + r["refs"]), key=_natural_ref)
                for f in ("manufacturer", "datasheet", "description"):
                    if not m[f] and r.get(f):
                        m[f] = r[f]

    if lookup:
        for m in merged.values():
            if not m["mpn"]:
                m["source"] = ""
                continue
            res = lookup(m["mpn"])
            if res:
                m["source"] = res.get("source", "")
                for f in ("manufacturer", "datasheet"):
                    if not m[f] and res.get(f):
                        m[f] = res[f]
            else:
                m["source"] = "NOT FOUND"

    rows = sorted(merged.values(), key=lambda r: (r["value"].lower(), r["footprint"].lower()))
    sourced = bool(lookup)
    priced = price_lookup is not None
    if priced:
        _price_rows(rows, price_lookup, "total_qty")
    out = {"rows": rows, "board_names": board_names,
           "csv": _bom_consolidated_csv(rows, board_names, sourced, priced),
           "line_count": len(rows), "total_parts": sum(r["total_qty"] for r in rows)}
    if priced:
        out["cost"] = bom_cost_summary(rows)
    return out


def bom_rows_at_ref(sheet_rels, show) -> dict:
    """Reconstruct a project's BOM as it existed at a git revision, for diffing against
    the current build. `sheet_rels` are the current build's repo-relative sheet paths;
    `show(rel) -> str | None` returns that sheet's content at the target revision.
    Identity only, NO network and NO pricing. Never raises: a failing `show` or an
    unparseable sheet is skipped. Returns {rows, sheets_found, sheets_missing}."""
    import os
    import tempfile
    comps: list = []
    found = missing = 0
    with tempfile.TemporaryDirectory() as td:
        for i, rel in enumerate(sheet_rels or []):
            try:
                text = show(rel)
            except Exception:  # noqa: BLE001 - a git failure is just an absent sheet
                text = None
            if not text:
                missing += 1
                continue
            found += 1
            fp = os.path.join(td, f"sheet_{i}.kicad_sch")
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                comps.extend(_bom_components(fp))
            except Exception:  # noqa: BLE001 - an unparseable sheet drops out
                continue
    res = _bom_from_components(comps)
    return {"rows": res["rows"], "sheets_found": found, "sheets_missing": missing}


# Header aliases so an exported BOM (project OR consolidated) parses back into
# diff-ready rows, matched case-insensitively.
_CSV_MPN_COLS = ("mpn", "manufacturer part number", "mfr part number",
                 "manufacturer part no", "part number")
_CSV_VALUE_COLS = ("value",)
_CSV_FOOTPRINT_COLS = ("footprint",)
_CSV_QTY_COLS = ("qty", "quantity", "total", "total qty")


def bom_rows_from_csv(text: str) -> list:
    """Parse an exported BOM CSV back into diff-ready rows [{mpn, value, footprint, qty}].
    Columns match by name (case-insensitive) so both the project and consolidated
    exports load. Rows with neither an MPN nor a value are skipped. Never raises."""
    if not text:
        return []
    import csv as _csv
    import io as _io
    rows = []
    try:
        reader = _csv.DictReader(_io.StringIO(text))
        headers = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}

        def _col(cols):
            for c in cols:
                if c in headers:
                    return headers[c]
            return None

        mpn_c = _col(_CSV_MPN_COLS)
        val_c = _col(_CSV_VALUE_COLS)
        fp_c = _col(_CSV_FOOTPRINT_COLS)
        qty_c = _col(_CSV_QTY_COLS)
        for raw in reader:
            mpn = (raw.get(mpn_c) or "").strip() if mpn_c else ""
            value = (raw.get(val_c) or "").strip() if val_c else ""
            if not mpn and not value:
                continue
            try:
                qty = int(float(raw.get(qty_c) or 0)) if qty_c else 0
            except (TypeError, ValueError):
                qty = 0
            rows.append({"mpn": mpn, "value": value,
                         "footprint": (raw.get(fp_c) or "").strip() if fp_c else "",
                         "qty": qty})
    except Exception:  # noqa: BLE001 - a malformed CSV yields what parsed so far
        return rows
    return rows


# -- cost roll-up --------------------------------------------------------------


def _coerce_price(v):
    """A price ('$0.10', '1,250.00', a number) -> float, or None if unparseable
    (e.g. 'Call for pricing')."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lstrip("$").replace(",", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def price_at_qty(price_breaks, qty):
    """The applicable unit price for ordering `qty` from a [{qty, price}, ...] ladder:
    the price of the largest break quantity <= qty. Below the first break, falls back to
    that first break. None when the ladder is empty or qty is unparseable."""
    if not price_breaks:
        return None
    try:
        q = int(float(qty))
    except (TypeError, ValueError):
        return None
    ladder = sorted(price_breaks, key=lambda b: b["qty"])
    applicable = None
    for b in ladder:
        if b["qty"] <= q:
            applicable = b["price"]
        else:
            break
    return applicable if applicable is not None else ladder[0]["price"]


def line_extended(unit_price, qty):
    """Extended line cost = unit_price * qty, or None when either is missing. Rounded to
    4 dp so fractional-cent unit prices do not accumulate float noise."""
    p = _coerce_price(unit_price)
    try:
        q = int(float(qty))
    except (TypeError, ValueError):
        q = 0
    return round(p * q, 4) if (p is not None and q) else None


def _coerce_rate(v) -> float:
    """A tax/tariff percentage ('8.25', '8.25%', 8.25, None) -> a non-negative float,
    or 0.0 when unparseable (a rate we cannot read never inflates a total)."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) if v >= 0 else 0.0
    s = str(v).strip().rstrip("%").replace(",", "")
    try:
        r = float(s)
    except (TypeError, ValueError):
        return 0.0
    return r if r >= 0 else 0.0


def line_moq(price_breaks) -> int | None:
    """A line's minimum order quantity: the smallest quantity on its price ladder (the
    fewest a distributor will sell). None when the ladder is empty or unparseable (an
    unpriced or value-only part has no MOQ)."""
    if not price_breaks:
        return None
    try:
        qtys = [int(b["qty"]) for b in price_breaks]
    except (TypeError, ValueError, KeyError):
        return None
    return min(qtys) if qtys else None


def price_line_at_build(row, build_qty, tax_rate=0.0, optimize_breaks=True) -> dict:
    """The order economics for ONE BOM line at a build of `build_qty` boards, taxed at
    `tax_rate` percent. Pure: never mutates `row`. Returns:
      moq              the smallest price-break quantity (the minimum orderable), or None
      final_qty        per_board_qty * build_qty, RAISED to the MOQ (you cannot order
                       fewer than the minimum), unit-priced at that quantity
      final_unit_price the ladder price at final_qty (a bigger run buys a cheaper break),
                       else the stored qty-1 unit_price; None when the line is unpriced
      final_extended   final_unit_price * final_qty; None when unpriced
      tax_tariff       final_extended * tax_rate / 100; None when unpriced
      line_total       final_extended + tax_tariff; None when unpriced
    """
    per_board = _bom_line_qty(row)
    build = _board_count(build_qty)
    needed = per_board * build
    ladder = row.get("price_breaks")
    moq = line_moq(ladder)

    final_qty = needed
    if needed > 0 and moq is not None and moq > needed:
        final_qty = moq  # round up to the minimum order

    # Price-break optimization: order MORE than needed when a higher break makes the TOTAL
    # cost lower (a steep quantity discount can beat ordering the exact count). We compare the
    # total (qty * unit at that qty) at `final_qty` against each break quantity above it, and
    # take the cheapest total. Because it minimizes TOTAL (not unit) cost, it never overbuys for
    # a trivial saving: a far-larger break whose total exceeds the smaller run is not chosen.
    if optimize_breaks and ladder and final_qty > 0:
        best_qty = final_qty
        best_unit = _coerce_price(price_at_qty(ladder, final_qty))
        best_total = best_unit * final_qty if best_unit is not None else None
        for b in ladder:
            try:
                bq = int(b["qty"])
            except (TypeError, ValueError, KeyError):
                continue
            if bq <= final_qty:
                continue  # only consider ordering MORE than the needed/MOQ quantity
            bu = _coerce_price(price_at_qty(ladder, bq))
            if bu is None:
                continue
            bt = bu * bq
            if best_total is None or bt < best_total:
                best_qty, best_total = bq, bt
        final_qty = best_qty

    unit = _coerce_price(price_at_qty(ladder, final_qty)) if ladder else None
    if unit is None:
        unit = _coerce_price(row.get("unit_price"))
    extended = round(unit * final_qty, 4) if (unit is not None and final_qty) else None

    # A per-part tariff overrides the blanket project rate for THIS line (some parts carry a
    # country-of-origin tariff others do not). A row-level tariff_rate wins when set; otherwise
    # the project-wide rate applies. So a mixed order taxes each line at its own rate.
    line_tariff = row.get("tariff_rate")
    rate = _coerce_rate(line_tariff if line_tariff not in (None, "") else tax_rate)
    tax = round(extended * rate / 100.0, 4) if extended is not None else None
    total = round(extended + tax, 4) if extended is not None else None
    return {
        "moq": moq,
        "final_qty": final_qty,
        "final_unit_price": unit,
        "final_extended": extended,
        "tax_tariff": tax,
        "line_total": total,
    }


def bom_build_rollup(rows, build_qty, tax_rate=0.0) -> dict:
    """Roll a priced BOM up for a build of `build_qty` boards taxed at `tax_rate`%: the
    subtotal (sum of every priced line's final_extended), the tax/tariff total on that
    subtotal, and the grand total, plus priced/unpriced counts. Pure. Mirrors
    price_line_at_build so the roll-up and the per-line columns always agree."""
    build = _board_count(build_qty)
    rate = _coerce_rate(tax_rate)
    subtotal = 0.0
    tax_total = 0.0
    priced = unpriced = 0
    for r in rows:
        line = price_line_at_build(r, build, rate)
        if line["final_extended"] is None:
            unpriced += 1
        else:
            subtotal += line["final_extended"]
            # Sum each line's OWN tax (its per-part tariff when set, else the blanket rate), so a
            # mixed-tariff order rolls up correctly - not one rate applied to the whole subtotal.
            tax_total += line["tax_tariff"] or 0.0
            priced += 1
    subtotal = round(subtotal, 2)
    tax_total = round(tax_total, 2)
    return {
        "build_qty": build,
        "tax_rate": rate,
        "subtotal": subtotal,
        "tax_total": tax_total,
        "grand_total": round(subtotal + tax_total, 2),
        "priced_lines": priced,
        "unpriced_lines": unpriced,
        "currency": "USD",
    }


def annotate_build_pricing(rows, boards=1, tax_rate=0.0) -> dict:
    """Attach the per-line build economics (moq / final_qty / final_unit_price /
    final_extended / tax_tariff / line_total) to each row IN PLACE for a build of `boards`
    boards taxed at `tax_rate`%, and return the roll-up. The single place the per-line
    columns and the roll-up are computed, so the table and the totals always agree."""
    for r in rows:
        r.update(price_line_at_build(r, boards, tax_rate))
    return bom_build_rollup(rows, boards, tax_rate)


def bom_cost_summary(rows) -> dict:
    """Roll up a BOM's line costs. Sums the extended cost of every PRICED line and
    counts unpriced lines separately, so a partial total is never mistaken for the whole.
    qty comes from 'qty' (project BOM) or 'total_qty' (consolidated). Returns {total_cost,
    priced_lines, unpriced_lines, line_count, currency}."""
    total = 0.0
    priced = unpriced = 0
    for r in rows:
        qty = r.get("qty", r.get("total_qty", 0))
        ext = r.get("extended")
        if ext is None:
            ext = line_extended(r.get("unit_price"), qty)
        if ext is None:
            unpriced += 1
        else:
            total += ext
            priced += 1
    return {"total_cost": round(total, 2), "priced_lines": priced,
            "unpriced_lines": unpriced, "line_count": len(rows), "currency": "USD"}


def _board_count(boards) -> int:
    """A build's board count as a whole number >= 1: anything unparseable or below 1
    folds to 1."""
    try:
        n = int(boards)
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1


def _row_cost_at_qty(r, boards):
    """The (order_qty, unit_price, extended) for ONE line at a build of `boards` boards.
    order_qty = per_board_qty * boards; the unit price is re-read from the line's ladder
    at that scaled qty (a bigger run buys down a cheaper break), else the stored qty-1
    unit_price. per-board qty comes from 'qty' (project) or 'total_qty' (consolidated).
    unit_price / extended are None when the line is unpriced. Never mutates `r`."""
    per_board = r.get("qty", r.get("total_qty", 0)) or 0
    try:
        per_board = int(per_board)
    except (TypeError, ValueError):
        per_board = 0
    order_qty = per_board * boards
    ladder = r.get("price_breaks")
    # Coerce the ladder-read price the same way line_extended / bom_cost_summary do, so a
    # string ladder price ('$0.10') costs instead of raising on round(str * qty).
    unit = _coerce_price(price_at_qty(ladder, order_qty)) if ladder else None
    if unit is None:
        unit = _coerce_price(r.get("unit_price"))
    ext = round(unit * order_qty, 4) if (unit is not None and order_qty) else None
    return order_qty, unit, ext


def bom_cost_at_qty(rows, boards) -> dict:
    """Project a priced BOM's cost for building `boards` copies. Each line scales to
    per_board_qty * boards and re-reads its unit price at that scaled quantity (volume
    break), else the stored qty-1 price. Mirrors bom_cost_summary's priced/unpriced
    bookkeeping. Pure: never mutates `rows`. Returns {boards, total_cost, priced_lines,
    unpriced_lines, currency}."""
    n = _board_count(boards)
    total = 0.0
    priced = unpriced = 0
    for r in rows:
        _order_qty, _unit, ext = _row_cost_at_qty(r, n)
        if ext is None:
            unpriced += 1
        else:
            total += ext
            priced += 1
    return {"boards": n, "total_cost": round(total, 2), "priced_lines": priced,
            "unpriced_lines": unpriced, "currency": "USD"}


def bom_cost_by_source(rows, boards=1) -> dict:
    """Split a priced BOM's projected cost by the distributor sourcing each line (they
    sum to the whole-run total). Uses the same per-line volume costing as bom_cost_at_qty.
    Only PRICED lines count; a priced line with a blank source is 'Unsourced'; unpriced
    lines are skipped. Returns {sources: {name: {total_cost, lines}}, currency}."""
    n = _board_count(boards)
    by: dict = {}
    for r in rows:
        _order_qty, _unit, ext = _row_cost_at_qty(r, n)
        if ext is None:
            continue
        src = (r.get("source") or "").strip() or "Unsourced"
        s = by.setdefault(src, {"total_cost": 0.0, "lines": 0})
        s["total_cost"] += ext
        s["lines"] += 1
    for s in by.values():
        s["total_cost"] = round(s["total_cost"], 2)
    return {"sources": by, "currency": "USD"}


def _price_rows(rows, price_lookup, qty_key: str):
    """Attach unit_price / stock / lifecycle / lead_time / source / distributor P/Ns and
    the extended cost to each row from a pricing lookup, one call per unique MPN. Rows
    without an MPN are left unpriced (a passive's value is not a purchasable part number).
    Prefers the price-break ladder so the line is costed at its real quantity."""
    cache: dict = {}
    for r in rows:
        mpn = r.get("mpn")
        if not mpn:
            continue
        if mpn not in cache:
            try:
                cache[mpn] = price_lookup(mpn)
            except Exception:  # noqa: BLE001 - a dead lookup leaves the line unpriced
                cache[mpn] = None
        res = cache[mpn] or {}
        qty = r.get(qty_key, 0)
        ladder = res.get("price_breaks")
        vol = price_at_qty(ladder, qty) if ladder else None
        if vol is not None:
            r["unit_price"] = vol
            r["extended"] = line_extended(vol, qty)
            r["price_breaks"] = ladder
        else:
            up = res.get("unit_price")
            if up is not None and up != "":
                r["unit_price"] = up
                r["extended"] = line_extended(up, qty)
                if ladder:
                    r["price_breaks"] = ladder
        if res.get("stock") is not None:
            r["stock"] = res.get("stock")
        if res.get("lifecycle"):
            r["lifecycle"] = res.get("lifecycle")
        if res.get("lead_time") not in (None, ""):
            r["lead_time"] = res.get("lead_time")
        # The enrich spec-table package (Mouser/LCSC) is authoritative, so it OVERRIDES the
        # footprint-derived baseline; rohs/category only fill a value the row does not carry.
        if res.get("package"):
            r["package"] = res["package"]
        for k in ("source", "lcsc_pn", "mouser_pn", "digikey_pn", "url", "category", "rohs"):
            v = res.get(k)
            if v and not r.get(k):
                r[k] = v


# -- CSV shapes (return-value fields; full export suite lands in M7d) ----------


def _bom_project_csv(rows, priced: bool) -> str:
    """The project BOM export CSV (Refs, Qty, Value, MPN, Manufacturer, Footprint,
    Datasheet, Description, Basic, + priced Source/Dist P/N/Unit/Ext/Stock/Lifecycle
    columns when priced). Pure."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    head = ["Refs", "Qty", "Value", "MPN", "Manufacturer", "Footprint",
            "Datasheet", "Description", "Basic"]
    if priced:
        head += ["Source", "Dist P/N", "Unit Price", "Ext Price", "Stock", "Lifecycle"]
    w.writerow(head)
    for r in rows:
        line = [",".join(r.get("refs", [])), r.get("qty", ""), r.get("value", ""),
                r.get("mpn", ""), r.get("manufacturer", ""), r.get("footprint", ""),
                r.get("datasheet", ""), r.get("description", ""),
                "yes" if r.get("basic") else ""]
        if priced:
            ext = r.get("extended")
            line += [r.get("source", ""), _dist_pn(r), r.get("unit_price", ""),
                     f"{ext:.4f}" if ext is not None else "",
                     r.get("stock", ""), r.get("lifecycle", "")]
        w.writerow(line)
    return buf.getvalue()


def _bom_consolidated_csv(rows, board_names, sourced: bool, priced: bool) -> str:
    """The consolidated BOM export CSV (MPN, Manufacturer, Value, Footprint, Total,
    [Source,] per-board columns, Datasheet, + priced columns). Pure."""
    import csv as _csv
    import io as _io
    buf = _io.StringIO()
    w = _csv.writer(buf, lineterminator="\n")
    head = ["MPN", "Manufacturer", "Value", "Footprint", "Total"] + list(board_names) + ["Datasheet"]
    if sourced:
        head.insert(5, "Source")
    if priced:
        head += ["Dist P/N", "Unit Price", "Ext Price", "Stock", "Lifecycle"]
    w.writerow(head)
    for r in rows:
        row = [r.get("mpn", ""), r.get("manufacturer", ""), r.get("value", ""),
               r.get("footprint", ""), r.get("total_qty", "")]
        if sourced:
            row.append(r.get("source", ""))
        row += [(r.get("per_board") or {}).get(b, 0) for b in board_names] + [r.get("datasheet", "")]
        if priced:
            ext = r.get("extended")
            row += [_dist_pn(r), r.get("unit_price", ""), f"{ext:.4f}" if ext is not None else "",
                    r.get("stock", ""), r.get("lifecycle", "")]
        w.writerow(row)
    return buf.getvalue()


# -- enrich -> price adapter (M7c-3) -------------------------------------------


# Internal enrich source tokens that name a real distributor, mapped to a display name
# for the BOM's Source column. Anything else (a scrape / jsonld / datasheet source) is
# not a distributor, so the line's Source stays blank (Unsourced in the cost split).
_DISTRIBUTOR_SOURCES = {"mouser": "Mouser", "lcsc": "LCSC", "digikey": "DigiKey"}


def enrichment_to_bom_lookup(result) -> dict | None:
    """Adapt an enrich-layer EnrichmentResult into the flat {price_breaks, unit_price,
    stock, manufacturer, datasheet, description, source, lifecycle, lead_time, url,
    <dist>_pn} dict the BOM's price_lookup expects (M7c-3 + M7d), so pricing AND
    procurement are served by Stockroom's own enrich layer rather than the retired app's
    dropped distributor adapters. Returns None for an empty result (a total miss), so the
    line stays honestly unpriced. Each optional field is emitted only when the result
    carried it, so an absent lifecycle/lead/dist-P/N is simply omitted, never a blank."""
    if result is None:
        return None
    breaks = [{"qty": b.qty, "price": b.price} for b in getattr(result, "price_breaks", [])]

    def _val(sourced):
        return sourced.value if sourced is not None else None

    out: dict = {}
    if breaks:
        out["price_breaks"] = breaks
        out["unit_price"] = breaks[0]["price"]
    if result.stock is not None:
        out["stock"] = result.stock.value
    if result.manufacturer is not None:
        out["manufacturer"] = _val(result.manufacturer)
    if result.datasheet_url is not None:
        out["datasheet"] = _val(result.datasheet_url)
    if result.description is not None:
        out["description"] = _val(result.description)
    # Wide-BOM columns: package (from the distributor's spec table, authoritative), the RoHS
    # verdict (from a RoHS-named spec) and the enrich category. Each emitted only when present.
    if result.package is not None:
        pkg = _val(result.package)
        if pkg:
            out["package"] = pkg
    rohs = rohs_from_specs({k: _val(v) for k, v in (result.specs or {}).items()})
    if rohs:
        out["rohs"] = rohs
    if result.category:
        out["category"] = result.category
    # M7d procurement fields the sourcing-risk + export layer reads off the priced row.
    if result.lifecycle is not None:
        out["lifecycle"] = _val(result.lifecycle)
    if result.lead_time is not None:
        out["lead_time"] = _val(result.lead_time)
    if result.product_url is not None:
        out["url"] = _val(result.product_url)
    for dist, pn in (getattr(result, "dist_pns", None) or {}).items():
        if pn:
            out[f"{dist}_pn"] = pn
    # Label the Source with the distributor that carried the priced signal: prefer the
    # source recorded on stock (a distributor stock count), else on the MPN.
    for sourced in (result.stock, result.mpn, result.manufacturer):
        if sourced is not None:
            disp = _DISTRIBUTOR_SOURCES.get((sourced.source or "").lower())
            if disp:
                out["source"] = disp
                break
    return out or None


# -- project orchestrator (M7c-4) ----------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bom_state(line_count: int, priced: bool, summary: dict) -> str:
    """The honest BOM verdict, mirroring the checks rule that "nothing built is never a
    clean pass": 'empty' (no lines), 'built' (grouped, pricing not attempted), 'unpriced'
    (priced attempted, nothing costed, e.g. offline), 'partial' (some lines unpriced),
    'costed' (every line priced). Only 'costed' is a fully green verdict."""
    if line_count == 0:
        return "empty"
    if not priced:
        return "built"
    if summary["priced_lines"] == 0:
        return "unpriced"
    if summary["unpriced_lines"] > 0:
        return "partial"
    return "costed"


def project_bom(root, pro_path, sheet_paths, name="", boards=1, tax_rate=0.0,
                price_lookup=None, progress=None, library_parts=None) -> dict:
    """Build a grouped, optionally priced BOM for a registered project (M7c), combining the KiCad
    schematic with the Stockroom library (M7c library-combining).

    Reads every schematic sheet through Stockroom's byte-preserving sexp reader (offline,
    no kicad-cli), fills each component's blank identity fields from its matching library part
    (`library_parts`), groups identical parts with KiBoM value-normalization + DNF/testpoint
    exclusion, and prices each line from the LIBRARY's stored prices first then `price_lookup`
    (the enrich layer) as a fallback, rolling up a cost summary at 1 and `boards` copies. Honest:
    when neither source can price a line it stays unpriced and a price is never invented. Returns
    {project, ran_at, boards, priced, line_count, component_count, lines, summary,
    by_source, cost_at_qty}."""
    root = Path(root)

    def _p(pct, msg):
        if progress:
            progress({"pct": pct, "message": msg})

    _p(10, "Reading schematics")
    abs_sheets = [str(root / s) for s in (sheet_paths or [])]

    _p(40, "Grouping components")
    parts = list(library_parts or ())
    match_index = library_match_index(parts) if parts else None
    # Price from the library first (offline), then the enrich layer; None only if neither can price.
    combined = combined_price_lookup(parts, price_lookup) if parts else price_lookup
    priced = combined is not None

    def _priced_progress(mpn_lookup):
        # Report progress as unique MPNs are priced (the slow, network-bound half).
        seen = {"n": 0}

        def wrapped(mpn):
            seen["n"] += 1
            _p(min(90, 55 + seen["n"]), f"Pricing {mpn}")
            return mpn_lookup(mpn)

        return wrapped

    lookup = _priced_progress(combined) if priced else None
    built = bom_from_project(abs_sheets, price_lookup=lookup, library_index=match_index)
    rows = built["rows"]

    # Fill each line's still-blank wide-BOM columns (package / rohs / category) from its matching
    # library part's captured specs, so a library-matched line surfaces them even when unpriced
    # (the enrich layer already overrode package + filled rohs/category for a priced line above).
    if parts:
        spec_index = library_spec_index(parts)
        for r in rows:
            entry = spec_index.get((r.get("mpn") or "").strip())
            if entry:
                for k, v in entry.items():
                    if v and not r.get(k):
                        r[k] = v

    n = _board_count(boards)
    summary = bom_cost_summary(rows)
    # For a run of more than one board, project the headline total at the run quantity so
    # it agrees with by_source and cost_at_qty (which scale to n boards and re-read the
    # volume break). bom_cost_summary alone rolls up the stored per-board (qty-1) extended,
    # which would contradict the per-source split by the board multiplier.
    if priced and n > 1:
        at_qty = bom_cost_at_qty(rows, n)
        summary["total_cost"] = at_qty["total_cost"]
        summary["priced_lines"] = at_qty["priced_lines"]
        summary["unpriced_lines"] = at_qty["unpriced_lines"]
    summary["state"] = _bom_state(built["line_count"], priced, summary)
    summary["priced"] = priced

    # Attach the per-line build economics (MOQ, final order qty, unit cost at that qty,
    # cost@qty, tax/tariff, line total) and the priced roll-up. Annotated for every build,
    # priced or not, so the quantity columns show even when a line is unpriced.
    rate = _coerce_rate(tax_rate)
    build = annotate_build_pricing(rows, n, rate)

    # Fold the procurement view onto the one BOM: each line gets a stock_risk + orderable and
    # the result carries the risk/lead roll-ups, so the wide table + its risk headline read a
    # single source (local import breaks the bom<->procurement import cycle).
    from stockroom.projects.procurement import annotate_procurement_fields
    proc = annotate_procurement_fields(rows, n)

    _p(95, "Summarizing")
    return {
        "project": name,
        "ran_at": _utc_now_iso(),
        "boards": n,
        "tax_rate": rate,
        "priced": priced,
        "line_count": built["line_count"],
        "component_count": built["component_count"],
        "lines": rows,
        "summary": summary,
        "by_source": bom_cost_by_source(rows, n) if priced else None,
        "cost_at_qty": bom_cost_at_qty(rows, n) if (priced and n > 1) else None,
        "build": build,
        "risks": proc["risks"],
        "lead": proc["lead"],
    }


def reprice_bom(bom_result, boards, tax_rate=0.0) -> dict:
    """Re-cost an EXISTING BOM result for a new build quantity + tax/tariff rate, PURELY
    over its already-built lines (their stored price_breaks) - no schematic re-read, no
    network. Returns a NEW result dict with re-annotated lines, an updated build roll-up,
    boards, tax_rate, and the scaled summary/by_source/cost_at_qty. The cached BOM's raw
    lines are the source of truth; only the quantity + tax math changes."""
    n = _board_count(boards)
    rate = _coerce_rate(tax_rate)
    result = dict(bom_result)
    rows = [dict(r) for r in (bom_result.get("lines") or [])]
    priced = bool(bom_result.get("priced"))

    build = annotate_build_pricing(rows, n, rate)
    summary = bom_cost_summary(rows)
    if priced and n > 1:
        at_qty = bom_cost_at_qty(rows, n)
        summary["total_cost"] = at_qty["total_cost"]
        summary["priced_lines"] = at_qty["priced_lines"]
        summary["unpriced_lines"] = at_qty["unpriced_lines"]
    summary["state"] = _bom_state(len(rows), priced, summary)
    summary["priced"] = priced

    # Re-fold procurement over the re-costed lines: the stock-risk verdict depends on the build
    # quantity, so a reprice must recompute it (and the roll-ups) or the table would go stale.
    from stockroom.projects.procurement import annotate_procurement_fields
    proc = annotate_procurement_fields(rows, n)

    result["lines"] = rows
    result["boards"] = n
    result["tax_rate"] = rate
    result["summary"] = summary
    result["by_source"] = bom_cost_by_source(rows, n) if priced else None
    result["cost_at_qty"] = bom_cost_at_qty(rows, n) if (priced and n > 1) else None
    result["build"] = build
    result["risks"] = proc["risks"]
    result["lead"] = proc["lead"]
    return result
