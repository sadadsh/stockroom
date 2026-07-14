"""Byte-preserving editor for the .kicad_pcb physical layer stack: `(setup (stackup ...))`.

This is the M7f-C write engine, the piece `kicad/board.py` (setup scalars + thickness) explicitly
left out of its A-slice scope. It reads the current stack structurally, edits individual stack
fields in place (finish / dielectric constraints / per-layer thickness / dielectric material +
epsilon_r + loss_tangent), and generates a whole `(stackup ...)` block from a fab preset. Every
edit routes through Stockroom's byte-preserving `SexpDocument` (the one and only `.kicad_*` editor):
a per-field edit rewrites only the atoms that differ, and a preset apply replaces exactly the
`(stackup ...)` span (KiCad itself rewrites the whole stackup on every save, so a block replace is
faithful AND still scoped, leaving the rest of the board byte-identical).

Grammar verified against REAL KiCad-10 boards (NETDECK `SH Files`/`CG Files`, generator_version
"10.0"), an improvement over the retired `nd_fab_presets.stackup_block` which the version drift had
made stale: KiCad 10 writes each `(layer ...)` MULTI-LINE / expanded (not single-line), a dielectric
carries `type`/`thickness`/`material`/`epsilon_r`/`loss_tangent` in that order, a copper layer carries
`thickness`, a solder mask carries `thickness` (and `color` only when a mask color is set, else the
atom is absent), and the block ends with `(copper_finish "...")` + `(dielectric_constraints yes|no)`.

The stackup's copper layers MUST match the board's own `(layers ...)` copper definition, so the
preset generate always uses the board's ACTUAL copper layer names (a preset whose copper count does
not match the board is refused, never silently desynced). Board thickness lives in a DIFFERENT block
(`(general (thickness N))`, board.py's accessor) and a preset apply sets it there.

All lengths are millimetres (KiCad's on-disk unit). No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import re

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument, quote_kicad

# The fixed framing layers KiCad always writes around the copper/dielectric core, with their exact
# `(type ...)` strings. F.Mask / B.Mask additionally carry a thickness (and optionally a color).
_FRAME_TYPES = {
    "F.SilkS": "Top Silk Screen",
    "F.Paste": "Top Solder Paste",
    "F.Mask": "Top Solder Mask",
    "B.Mask": "Bottom Solder Mask",
    "B.Paste": "Bottom Solder Paste",
    "B.SilkS": "Bottom Silk Screen",
}

# Per-field editors: numeric atoms (formatted like KiCad) and string atoms (quoted). Only atoms that
# already exist are rewritten (update-if-present) so a per-field edit never manufactures a token.
_NUMERIC_LAYER_FIELDS = ("thickness", "epsilon_r", "loss_tangent")
_STRING_LAYER_FIELDS = ("material",)

_IN_CU_RE = re.compile(r"^In(\d+)\.Cu$")


def _fmt(v) -> str:
    """Format a length the way KiCad writes it: an integral value as a bare int, else up to 6
    decimals with trailing zeros trimmed, negative zero normalised to 0. Matches board._fmt_num /
    conform._fmt so a value round-trips byte-identically with what KiCad emits."""
    f = float(v)
    if f == 0.0:
        f = 0.0  # kill negative zero
    if f == int(f):
        return str(int(f))
    s = ("%.6f" % f).rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _to_float(atom: str):
    try:
        return float(atom)
    except (TypeError, ValueError):
        return None


def detect_format(text: str) -> tuple[str, str]:
    """The (indent-unit, newline) a .kicad_pcb uses, so a generated `(stackup ...)` block matches the
    file's whitespace convention (tabs vs spaces, LF vs CRLF) and stays a minimal diff. Defaults to a
    single tab + LF (KiCad's on-disk convention)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    unit = "\t"
    for line in text.split("\n"):
        stripped = line.lstrip(" \t")
        if stripped.startswith("(") and stripped != line:
            unit = line[: len(line) - len(stripped)]
            break
    return unit, nl


def _copper_sort_key(name: str):
    """Physical top->bottom order of a copper layer: F.Cu first, then In1..InN ascending, B.Cu last.
    The board's `(layers ...)` lists copper by KiCad layer INDEX (F.Cu 0, B.Cu 2, In1 4, In2 6),
    which is NOT physical order, so a stackup read must re-sort."""
    if name == "F.Cu":
        return (0, 0)
    if name == "B.Cu":
        return (2, 0)
    m = _IN_CU_RE.match(name)
    if m:
        return (1, int(m.group(1)))
    return (1, 10 ** 6)  # an unrecognised copper layer sorts into the inner region, defensive


def copper_layer_names(doc: SexpDocument) -> list[str]:
    """The board's copper layer names in PHYSICAL top->bottom order, read from `(layers ...)`.
    Returns [] when the board declares no `(layers ...)` block. The stackup's copper layers must
    match these exactly, so the preset generate substitutes them for the preset's copper positions."""
    layers = doc.root.find("layers")
    if layers is None:
        return []
    names: list[str] = []
    for ch in layers.children:
        if ch.is_atom:
            continue
        kids = ch.children
        # a layer entry is (index "Name" type ...): the name is the second atom
        if len(kids) >= 2 and kids[1].is_atom:
            nm = kids[1].value
            if nm.endswith(".Cu"):
                names.append(nm)
    return sorted(names, key=_copper_sort_key)


def _read_layer(node) -> dict:
    kids = node.children
    lyr: dict = {"name": kids[1].value if len(kids) >= 2 and kids[1].is_atom else ""}
    t = node.find("type")
    if t is not None and len(t.children) >= 2:
        lyr["type"] = t.children[1].value
    for key in _NUMERIC_LAYER_FIELDS:
        n = node.find(key)
        if n is not None and len(n.children) >= 2:
            v = _to_float(n.children[1].value)
            if v is not None:
                lyr[key] = v
    for key in ("material", "color"):
        n = node.find(key)
        if n is not None and len(n.children) >= 2:
            lyr[key] = n.children[1].value
    return lyr


def _stackup_node(doc: SexpDocument):
    setup = doc.root.find("setup")
    if setup is None:
        return None, None
    return setup, setup.find("stackup")


def read_stackup(doc: SexpDocument) -> dict | None:
    """The board's current physical stack, structured, or None when it has no `(setup (stackup ...))`.

    Shape: {"layers": [{name, type, thickness?, material?, epsilon_r?, loss_tangent?, color?}, ...],
    "copper_finish": str|None, "dielectric_constraints": bool|None}. A field is present in a layer
    dict only when its atom is present on disk, so `render_stackup_block` reproduces the block
    byte-for-byte (a mask with no color has no color key -> no color atom emitted)."""
    _setup, st = _stackup_node(doc)
    if st is None:
        return None
    layers = [_read_layer(ln) for ln in st.find_all("layer")]
    cf = st.find("copper_finish")
    dc = st.find("dielectric_constraints")
    return {
        "layers": layers,
        "copper_finish": cf.children[1].value if cf is not None and len(cf.children) >= 2 else None,
        "dielectric_constraints": (
            _as_yes(dc.children[1].value) if dc is not None and len(dc.children) >= 2 else None
        ),
    }


def _as_yes(atom: str) -> bool:
    return isinstance(atom, str) and atom.strip().lower() == "yes"


def render_stackup_block(
    layers: list[dict], *, copper_finish, dielectric_constraints,
    unit: str = "\t", nl: str = "\n", depth: int = 2,
) -> str:
    """Render a full structured stackup (the exact list `read_stackup` returns) back to a KiCad-10
    `(stackup ...)` block. `read_stackup(doc)` -> `render_stackup_block(...)` is byte-identity for a
    native board, which is the fidelity guarantee the preset-apply path inherits (it renders through
    the same function). Atom order per layer: type, color, thickness, material, epsilon_r,
    loss_tangent (only those present are emitted). `depth` is the stackup's indent depth (2 = inside
    (setup) inside (kicad_pcb)); the returned block starts at `(stackup` with no leading indent (the
    caller's replace preserves the existing indent) and closes at `unit*depth`."""
    li = unit * (depth + 1)  # a (layer ...) line
    ai = unit * (depth + 2)  # an atom inside a layer
    out = ["(stackup"]
    for lyr in layers:
        out.append(f'{li}(layer "{lyr["name"]}"')
        if "type" in lyr:
            out.append(f'{ai}(type "{lyr["type"]}")')
        if "color" in lyr:
            out.append(f'{ai}(color "{lyr["color"]}")')
        if "thickness" in lyr:
            out.append(f"{ai}(thickness {_fmt(lyr['thickness'])})")
        if "material" in lyr:
            out.append(f'{ai}(material "{lyr["material"]}")')
        if "epsilon_r" in lyr:
            out.append(f"{ai}(epsilon_r {_fmt(lyr['epsilon_r'])})")
        if "loss_tangent" in lyr:
            out.append(f"{ai}(loss_tangent {_fmt(lyr['loss_tangent'])})")
        out.append(f"{li})")
    out.append(f'{li}(copper_finish "{copper_finish}")')
    out.append(f"{li}(dielectric_constraints {'yes' if dielectric_constraints else 'no'})")
    out.append(f"{unit * depth})")
    return nl.join(out)


def stackup_thickness_sum(layers: list[dict]) -> float:
    """The board's overall thickness as KiCad computes it: the sum of every stackup layer that
    carries a `(thickness ...)` (copper + dielectric + solder mask; silk/paste carry none). Verified
    against the real NETDECK boards, whose `(general (thickness))` equals exactly this sum. A preset
    apply writes THIS as the board thickness so the generated board is internally consistent (the
    declared thickness matches its own stack), the invariant KiCad maintains, rather than a nominal
    that KiCad would recompute away."""
    return round(sum(float(l["thickness"]) for l in layers if l.get("thickness") is not None), 6)


def build_preset_layers(
    copper_names: list[str], physical: list[dict], *,
    mask_thickness: float = 0.01, mask_color: str | None = None,
) -> list[dict]:
    """Build the full structured layer list for a fab-preset apply: the fixed silk/paste/mask frame
    wrapped around the preset's copper/dielectric core. Copper entries take their names from
    `copper_names` (the board's actual copper layers, in physical order); dielectrics are numbered
    `dielectric 1..K`. Raises ValueError when the preset's copper count does not match the board's
    (the stackup would desync from the board's `(layers ...)`). `physical` is the ordered core: each
    entry is {"kind": "copper", "thickness"} or {"kind": "dielectric", "type", "thickness",
    "material"?, "epsilon_r"?, "loss_tangent"?}."""
    copper_entries = [p for p in physical if p.get("kind") == "copper"]
    if len(copper_entries) != len(copper_names):
        raise ValueError(
            f"the preset defines {len(copper_entries)} copper layers but this board has "
            f"{len(copper_names)} ({', '.join(copper_names) or 'none'}); pick a preset that matches "
            "the board's layer count"
        )
    fmask = {"name": "F.Mask", "type": _FRAME_TYPES["F.Mask"], "thickness": mask_thickness}
    bmask = {"name": "B.Mask", "type": _FRAME_TYPES["B.Mask"], "thickness": mask_thickness}
    if mask_color:
        fmask["color"] = mask_color
        bmask["color"] = mask_color
    layers: list[dict] = [
        {"name": "F.SilkS", "type": _FRAME_TYPES["F.SilkS"]},
        {"name": "F.Paste", "type": _FRAME_TYPES["F.Paste"]},
        fmask,
    ]
    ci = 0
    di = 0
    for p in physical:
        if p.get("kind") == "copper":
            layers.append({"name": copper_names[ci], "type": "copper", "thickness": p["thickness"]})
            ci += 1
        else:
            di += 1
            lyr: dict = {"name": f"dielectric {di}", "type": p.get("type", "core"),
                         "thickness": p["thickness"]}
            for k in ("material", "epsilon_r", "loss_tangent"):
                if k in p:
                    lyr[k] = p[k]
            layers.append(lyr)
    layers += [
        bmask,
        {"name": "B.Paste", "type": _FRAME_TYPES["B.Paste"]},
        {"name": "B.SilkS", "type": _FRAME_TYPES["B.SilkS"]},
    ]
    return layers


def apply_stackup_block(doc: SexpDocument, block_text: str) -> bool:
    """Replace the board's `(stackup ...)` block with `block_text` (a scoped span replace, so the
    rest of the board is byte-identical), or insert it into `(setup ...)` when the board has no
    stackup yet. Returns True when the bytes actually change (an identical block is a no-op that
    returns False). Raises KiCadFileError when the board has no `(setup ...)` block to hold it."""
    setup, st = _stackup_node(doc)
    if setup is None:
        raise KiCadFileError("board has no (setup ...) block to hold a stackup")
    if st is not None:
        current = doc.text[st.span[0]:st.span[1]]
        if current == block_text:
            return False
        doc.replace_span(*st.span, block_text)
        return True
    # No stackup yet: insert it as the FIRST child of (setup ...) (KiCad's convention: the stackup
    # always leads the setup block), not the last, so the generated board is native and KiCad does
    # not reorder + churn it on the next save.
    first = next((c for c in setup.children if not c.is_atom), None)
    if first is not None:
        indent = setup._indent_before(setup.children.index(first))
        doc.insert_span(first.span[0], block_text + indent)
    else:  # an empty (setup) with no list children: fall back to a plain child insert
        setup.insert_child_text(block_text)
    return True


def _find_layer(st, name: str):
    for ln in st.find_all("layer"):
        kids = ln.children
        if len(kids) >= 2 and kids[1].value == name:
            return ln
    return None


def _set_atom_value(node, target: str, *, quote: bool) -> int:
    """Set node's value atom (children[1]) to `target`, but only if it differs (idempotent). Returns
    1 when an atom actually changed, 0 when identical or the node is absent/malformed (update-if-
    present: an absent atom is left absent, never manufactured)."""
    if node is None or len(node.children) < 2:
        return 0
    atom = node.children[1]
    if atom.value == target:
        return 0
    atom.set_value(target, quote=quote)
    return 1


def set_stackup_fields(
    doc: SexpDocument, *, copper_finish=None, dielectric_constraints=None, layers=None,
) -> int:
    """Edit individual stack fields in place, byte-preservingly, on the existing `(stackup ...)`:
    `copper_finish` (quoted string), `dielectric_constraints` (bool -> yes/no), and per-layer fields
    via `layers` = {layer_name: {thickness?, material?, epsilon_r?, loss_tangent?}}. Every field is
    update-if-present (only an atom that exists is rewritten, never manufactured). Returns the count
    of atoms that changed; a no-op (every target already at its value) returns 0 and leaves the file
    byte-identical. No change to any layer topology or to unmodeled tokens. (A solder-mask colour is
    set through a fab-preset apply, which regenerates the whole block, not through this per-field
    path.)"""
    _setup, st = _stackup_node(doc)
    if st is None:
        return 0
    changed = 0
    if copper_finish is not None:
        node = st.find("copper_finish")
        if node is None:
            st.insert_child_text(f"(copper_finish {quote_kicad(str(copper_finish))})")
            changed += 1
        else:
            changed += _set_atom_value(node, str(copper_finish), quote=True)
    if dielectric_constraints is not None:
        target = "yes" if dielectric_constraints else "no"
        node = st.find("dielectric_constraints")
        if node is None:
            st.insert_child_text(f"(dielectric_constraints {target})")
            changed += 1
        else:
            changed += _set_atom_value(node, target, quote=False)
    for lname, fields in (layers or {}).items():
        node = _find_layer(st, lname)
        if node is None:
            continue
        for key in _NUMERIC_LAYER_FIELDS:
            if key in fields and fields[key] is not None:
                changed += _set_atom_value(node.find(key), _fmt(fields[key]), quote=False)
        for key in _STRING_LAYER_FIELDS:
            if key in fields and fields[key] is not None:
                changed += _set_atom_value(node.find(key), str(fields[key]), quote=True)
        if fields.get("color") is not None:
            cn = node.find("color")
            if cn is None:
                node.insert_child_text(f"(color {quote_kicad(str(fields['color']))})")
                changed += 1
            else:
                changed += _set_atom_value(cn, str(fields["color"]), quote=True)
    return changed
