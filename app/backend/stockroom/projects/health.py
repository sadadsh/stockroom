"""Project health audit, Qt-free.

Lifted behavior-for-behavior from the retired app's nd_project_health (the READ half):
it reads a KiCad schematic (and, when footprint libraries are pointed at it, the
footprints) and reports the problems that bite a board before fab - unannotated or
duplicated reference designators, components with no footprint, symbol-pin vs
footprint-pad mismatches, missing 3D models, and parts with no manufacturer / MPN.

Two changes from the original: the sexp reading goes through Stockroom's byte-preserving
sexp layer instead of fp_render.parse_sexpr, and the no-MPN check uses the Qt-free
projects.identity helpers instead of the PyQt LibraryManager. Everything here is
read-only and returns plain dicts. The annotate/auto-fix (write) half lands in M7f.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re
from pathlib import Path

from stockroom.projects import identity
from stockroom.sexp.document import SexpDocument, SexpNode

# ---- schematic reading (via the sexp layer) ---------------------------------


def _read_root(sch_path) -> SexpNode | None:
    try:
        root = SexpDocument.load(sch_path).root
    except Exception:  # noqa: BLE001 - a corrupt/missing file audits as empty, never crashes
        return None
    return root if root.name == "kicad_sch" else None


def _prop_value(prop: SexpNode) -> tuple[str, str] | None:
    kids = prop.children
    if len(kids) >= 3:
        return kids[1].value, kids[2].value
    return None


def schematic_components(sch_path) -> list[dict]:
    """Real placed components in a .kicad_sch: [{ref, value, footprint, lib_id, props}].
    Power/virtual symbols (#PWR..., power:*) are excluded."""
    root = _read_root(sch_path)
    if root is None:
        return []
    out = []
    for node in root.find_all("symbol"):
        lib_node = node.find("lib_id")
        if lib_node is None:
            continue
        lib_id = lib_node.children[1].value if len(lib_node.children) > 1 else ""
        props: dict = {}
        for prop in node.find_all("property"):
            kv = _prop_value(prop)
            if kv:
                props[kv[0]] = kv[1]
        ref = props.get("Reference", "")
        if not ref or ref.startswith("#") or lib_id.lower().startswith("power:"):
            continue
        out.append(
            {
                "ref": ref,
                "value": props.get("Value", ""),
                "footprint": props.get("Footprint", ""),
                "lib_id": lib_id,
                "props": props,
            }
        )
    return out


def _count_pins(node: SexpNode) -> int:
    n = 0
    for c in node.children:
        if c.is_atom:
            continue
        n += 1 if c.name == "pin" else _count_pins(c)
    return n


def symbol_pin_counts(sch_path) -> dict:
    """lib_id -> number of pins, from the (lib_symbols) cache the schematic embeds.
    Pins are counted across the symbol's unit sub-symbols."""
    root = _read_root(sch_path)
    if root is None:
        return {}
    libsym = root.find("lib_symbols")
    if libsym is None:
        return {}
    counts: dict = {}
    for sym in libsym.find_all("symbol"):
        kids = sym.children
        if len(kids) > 1 and kids[1].is_atom:
            counts[kids[1].value] = _count_pins(sym)
    return counts


# ---- footprint resolution (best-effort, when libraries are pointed at us) ----


def _footprint_pads_and_models(fp_dirs, fp_ref):
    """Given 'Nickname:NAME' and candidate footprint directories, return
    (distinct_pad_count, [model_filenames]) or (None, None) if unresolvable."""
    if not fp_ref or ":" not in fp_ref:
        return None, None
    name = fp_ref.split(":", 1)[1]
    for d in fp_dirs:
        cand = Path(d) / f"{name}.kicad_mod"
        if not cand.exists():
            for pretty in Path(d).glob("*.pretty"):
                alt = pretty / f"{name}.kicad_mod"
                if alt.exists():
                    cand = alt
                    break
        if cand.exists():
            text = cand.read_text(encoding="utf-8", errors="replace")
            pads = set(re.findall(r'\(pad\s+"([^"]+)"', text))
            pads.discard("")
            models = [Path(m).name for m in re.findall(r'\(model\s+"?([^"\s)]+)', text)]
            return len(pads), models
    return None, None


# ---- check registry ---------------------------------------------------------

_CHECKS: list = []


def register_check(fn):
    """Register a check(ctx) callable into the audit pipeline. Returns the function
    unchanged so it doubles as a decorator."""
    _CHECKS.append(fn)
    return fn


class _AuditContext:
    def __init__(self, comps, pin_counts, fp_dirs, model_dirs, mdl_names, detect_duplicates, findings):
        self.comps = comps
        self.pin_counts = pin_counts
        self.fp_dirs = fp_dirs
        self.model_dirs = model_dirs
        self.mdl_names = mdl_names
        self.detect_duplicates = detect_duplicates
        self.findings = findings
        self.checked_footprints = 0
        self.unresolved_footprints = 0

    def add(self, ref, severity, kind, detail):
        self.findings.append({"ref": ref, "severity": severity, "kind": kind, "detail": detail})


@register_check
def _check_unannotated(ctx):
    for c in ctx.comps:
        if c["ref"].rstrip().endswith("?"):
            ctx.add(c["ref"], "error", "unannotated", "reference designator not annotated")


@register_check
def _check_duplicate_ref(ctx):
    if not ctx.detect_duplicates:
        return
    seen: dict = {}
    for c in ctx.comps:
        if not c["ref"].endswith("?"):
            seen[c["ref"]] = seen.get(c["ref"], 0) + 1
    for ref, n in seen.items():
        if n > 1:
            ctx.add(ref, "error", "duplicate_ref", f"{n} components share reference {ref}")


@register_check
def _check_no_footprint(ctx):
    for c in ctx.comps:
        if not c["footprint"].strip():
            ctx.add(c["ref"], "warning", "no_footprint", "no footprint assigned")


@register_check
def _check_no_mpn(ctx):
    # Qt-free identity: a real MPN from a dedicated field, or a manufacturer, else a
    # sourcing gap. (Replaces the retired PyQt LibraryManager.part_identity/strict_mpn.)
    for c in ctx.comps:
        ident = identity.part_identity(c["props"])
        if not ident["manufacturer"] and not identity.strict_mpn(c["props"]):
            ctx.add(c["ref"], "info", "no_mpn", "no manufacturer / MPN - cannot be sourced")


@register_check
def _check_footprint_pads_and_models(ctx):
    if not ctx.fp_dirs:
        return
    for c in ctx.comps:
        if not c["footprint"].strip():
            continue
        pad_n, models = _footprint_pads_and_models(ctx.fp_dirs, c["footprint"])
        if pad_n is None:
            ctx.unresolved_footprints += 1
            continue
        ctx.checked_footprints += 1
        pins = ctx.pin_counts.get(c["lib_id"])
        if pins and pad_n and pins != pad_n:
            ctx.add(
                c["ref"],
                "error",
                "pin_pad_mismatch",
                f"symbol {pins} pins vs footprint {pad_n} pads ({c['footprint']})",
            )
        if ctx.model_dirs is not None:
            if not models:
                ctx.add(c["ref"], "info", "no_3d_model", f"footprint has no 3D model ({c['footprint']})")
            elif ctx.mdl_names and not any(Path(m).name in ctx.mdl_names for m in models):
                ctx.add(
                    c["ref"],
                    "info",
                    "missing_3d_model",
                    f"3D model not found on disk ({', '.join(Path(m).name for m in models)})",
                )


# ---- audit core -------------------------------------------------------------


def _audit_components(comps, pin_counts, footprint_dirs=None, model_dirs=None, detect_duplicates=True, extra_findings=None) -> dict:
    fp_dirs = [d for d in (footprint_dirs or []) if d and Path(d).exists()]
    mdl_names = set()
    for d in model_dirs or []:
        if d and Path(d).exists():
            mdl_names |= {p.name for p in Path(d).glob("*") if p.suffix.lower() in (".step", ".stp", ".wrl")}

    findings = list(extra_findings or [])
    ctx = _AuditContext(comps, pin_counts, fp_dirs, model_dirs, mdl_names, detect_duplicates, findings)
    for check in _CHECKS:
        check(ctx)

    # collapse identical findings (a duplicate-ref'd component would repeat its per-ref note)
    seen_f, uniq = set(), []
    for f in findings:
        k = (f["ref"], f["kind"], f["detail"])
        if k not in seen_f:
            seen_f.add(k)
            uniq.append(f)
    findings = uniq

    by_sev = {"error": 0, "warning": 0, "info": 0}
    by_kind: dict = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
    healthy = len({c["ref"] for c in comps}) - len({f["ref"] for f in findings})
    return {
        "project": "",
        "components": len(comps),
        "healthy": max(0, healthy),
        "counts": {"by_severity": by_sev, "by_kind": by_kind},
        "findings": sorted(
            findings,
            key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f["severity"]], f["kind"], f["ref"]),
        ),
        "checked_footprints": ctx.checked_footprints,
        "unresolved_footprints": ctx.unresolved_footprints,
    }


def audit_schematic(sch_path, footprint_dirs=None, model_dirs=None) -> dict:
    """Health findings for a single KiCad schematic. Optional footprint_dirs enables the
    symbol-pin vs footprint-pad check; model_dirs enables the missing-3D-model check.
    Returns {project, components, healthy, counts, findings, checked_footprints,
    unresolved_footprints, sheets}. Read-only."""
    comps = schematic_components(sch_path)
    pin_counts = symbol_pin_counts(sch_path)
    au = _audit_components(comps, pin_counts, footprint_dirs, model_dirs)
    au["project"] = Path(sch_path).stem
    au["sheets"] = 1
    return au


def audit_project(sch_paths, footprint_dirs=None, model_dirs=None) -> dict:
    """Health across every schematic sheet in a project: collect all components + pin
    counts, detect intra-sheet duplicate references, dedupe a component reused across
    hierarchical sheets by identity, then run the checks once. Same shape as
    audit_schematic plus a `sheets` count."""
    comps: list = []
    pin_counts: dict = {}
    n = 0
    seen_sig = set()
    dup_findings = []
    for sp in sch_paths or []:
        n += 1
        try:
            sheet_comps = schematic_components(sp)
            pin_counts.update(symbol_pin_counts(sp))
        except Exception:  # noqa: BLE001
            continue
        within: dict = {}
        for c in sheet_comps:
            if not c["ref"].endswith("?"):
                within[c["ref"]] = within.get(c["ref"], 0) + 1
        for ref, k in within.items():
            if k > 1:
                dup_findings.append(
                    {"ref": ref, "severity": "error", "kind": "duplicate_ref", "detail": f"{k} components share reference {ref} on one sheet"}
                )
        for c in sheet_comps:
            sig = (c["ref"], c.get("value", ""), c.get("footprint", ""), c.get("lib_id", ""))
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            comps.append(c)
    au = _audit_components(comps, pin_counts, footprint_dirs, model_dirs, detect_duplicates=False, extra_findings=dup_findings)
    au["project"] = "project"
    au["sheets"] = n
    return au


def audit_altium_project(root, pro_path, sheet_paths) -> dict:
    """Health across an Altium project's .SchDoc sheets, through the SAME check
    registry as the KiCad audit (unannotated / duplicate refs / no footprint /
    no MPN), plus the Altium-specific findings the .PrjPcb makes possible: a
    document the project lists that is missing on disk, and a sheet that exists
    but cannot be read as a schematic. The pin/pad and 3D checks need KiCad
    footprint libraries, so they honestly skip here (no fabricated results).

    Same designator + same library reference on two sheets is ONE component
    (multi-part units spread across pages); the same designator with a DIFFERENT
    library reference is a genuine annotation error."""
    comps, extra_findings, n = _collect_altium(root, sheet_paths)
    au = _audit_components(comps, {}, None, None, detect_duplicates=False,
                           extra_findings=extra_findings)
    au["project"] = "project"
    au["sheets"] = n
    return au


def altium_project_components(root, sheet_paths) -> list[dict]:
    """The placed components of an Altium project in the SAME {ref, lib_id, value,
    footprint, props} shape fill.read_components yields for KiCad, so readiness and
    the Buildability verdict compute identically for both EDAs."""
    comps, _findings, _n = _collect_altium(root, sheet_paths)
    return comps


def _collect_altium(root, sheet_paths) -> tuple[list[dict], list[dict], int]:
    from stockroom.altium.schdoc import read_schdoc_components

    root = Path(root)
    comps: list = []
    extra_findings: list = []
    seen_keys: set = set()
    ref_libref: dict = {}
    n = 0
    for rel in sheet_paths or []:
        n += 1
        sp = root / rel
        if not sp.exists():
            extra_findings.append({
                "ref": rel, "severity": "error", "kind": "missing_document",
                "detail": f"the project lists {rel} but it is missing on disk",
            })
            continue
        try:
            sheet = read_schdoc_components(sp)
        except Exception:  # noqa: BLE001 - a corrupt sheet is a finding, never a crash
            extra_findings.append({
                "ref": rel, "severity": "warning", "kind": "unreadable_document",
                "detail": f"{rel} could not be read as an Altium schematic",
            })
            continue
        for c in sheet:
            ref = c["designator"]
            key = (ref, c["lib_ref"])
            if ref and key in seen_keys:
                continue  # another unit of the same physical part on a later sheet
            seen_keys.add(key)
            if ref and not ref.endswith("?"):
                prev = ref_libref.get(ref)
                if prev is not None and prev != c["lib_ref"]:
                    extra_findings.append({
                        "ref": ref, "severity": "error", "kind": "duplicate_ref",
                        "detail": f"2 components share reference {ref} across sheets",
                    })
                ref_libref.setdefault(ref, c["lib_ref"])
            props = dict(c["params"])
            props["Reference"] = ref
            if not (props.get("Footprint") or "").strip():
                props["Footprint"] = c["footprint"]
            if not (props.get("MPN") or "").strip() and (c["design_item_id"] or "").strip():
                props["MPN"] = c["design_item_id"]
            comps.append({
                "ref": ref,
                "value": props.get("Value", ""),
                "footprint": props.get("Footprint", ""),
                "lib_id": f"altium:{c['lib_ref']}" if c["lib_ref"] else "",
                "props": props,
            })
    return comps, extra_findings, n


def audit_report_markdown(audit: dict) -> str:
    """A shareable markdown report from an audit result."""
    s = audit["counts"]["by_severity"]
    lines = [
        f"# Project Health - {audit['project']}",
        "",
        f"**{audit['healthy']} / {audit['components']} components healthy** - "
        f"{s['error']} errors, {s['warning']} warnings, {s['info']} notes.",
        "",
    ]
    if audit["unresolved_footprints"]:
        lines.append(
            f"*(pin/pad + 3D checked on {audit['checked_footprints']} footprints; "
            f"{audit['unresolved_footprints']} not resolvable from the given libraries)*"
        )
        lines.append("")
    order = {"error": "Errors", "warning": "Warnings", "info": "Notes"}
    for sev, title in order.items():
        rows = [f for f in audit["findings"] if f["severity"] == sev]
        if rows:
            lines += [f"## {title} ({len(rows)})", ""]
            lines += [f"- **{f['ref']}** - {f['detail']}" for f in rows]
            lines.append("")
    if not audit["findings"]:
        lines.append("No issues found.")
    return "\n".join(lines) + "\n"
