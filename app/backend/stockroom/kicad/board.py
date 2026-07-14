"""Byte-preserving editor for the .kicad_pcb (setup ...) block.

These keys physically live in the board's `(setup ...)` S-expression, NOT in `.kicad_pro`:
KiCad ignores solder-mask / solder-paste / tenting / origin keys written to the project
file, so they must be edited here to take effect. Domain knowledge (which keys exist, the
friendly-name aliases, KiCad number formatting) is ported by-behavior from the retired
`nd_board_setup.py`, but every edit routes through Stockroom's byte-preserving
`SexpDocument` (the one and only `.kicad_*` editor), and this adds the KiCad-10 nested
via-protection family (tenting / covering / plugging) that nd_board_setup predated.

The overall board thickness lives in a DIFFERENT block, `(general (thickness N))`, not
`(setup)`; `thickness()`/`set_thickness()` edit it byte-preservingly through the same doc.

All lengths are millimetres (KiCad's on-disk unit); `*_ratio` is a dimensionless fraction.
Out of scope (a board editor, not a stackup editor): the physical `(setup (stackup ...))`
layer stack, per-layer settings, the repeatable user via/track/diff-pair size lists, and the
`(pcbplotparams ...)` plot block.
"""

from __future__ import annotations

from stockroom.kicad.errors import KiCadFileError
from stockroom.sexp.document import SexpDocument

# Scalar length / ratio values: (key N).
SETUP_NUMERIC_KEYS = frozenset(
    {
        "pad_to_mask_clearance",
        "solder_mask_min_width",
        "pad_to_paste_clearance",
        "pad_to_paste_clearance_ratio",
    }
)
# Coordinate-pair values: (key X Y).
SETUP_COORD_KEYS = frozenset({"grid_origin", "aux_axis_origin"})
# Flat yes/no boolean values: (key yes|no).
SETUP_BOOL_KEYS = frozenset(
    {"allow_soldermask_bridges_in_footprints", "capping", "filling"}
)
# Via-protection blocks with a per-side pair: (key (front yes|no) (back yes|no)). The
# board-level value is the default consulted by vias (a via may override it per-via). The
# nested tenting form arrived in KiCad 9; covering/plugging (and the flat capping/filling)
# are the KiCad-10 IPC-4761 additions. KiCad rewrites the whole block on every save.
SETUP_SIDED_KEYS = frozenset({"tenting", "covering", "plugging"})

# Friendly ProjectSettings names -> real (setup ...) keys. `solder_mask_margin` etc. are
# PAD-level keys in KiCad and would be dead keys in (setup ...); these map onto the real ones.
KEY_ALIASES = {
    "solder_mask_clearance": "pad_to_mask_clearance",
    "solder_paste_margin": "pad_to_paste_clearance",
    "solder_paste_margin_ratio": "pad_to_paste_clearance_ratio",
}

# KiCad's implicit per-side default when a via-protection block is absent, so creating one
# to change a single side leaves the other side at its effective value (no silent flip).
# Matches KiCad 10.0.4 BOARD_DESIGN_SETTINGS (m_TentViasFront/Back default true; the IPC-4761
# covering/plugging default false), i.e. writing (tenting (front yes)(back yes)) onto a board
# that has no tenting block is a no-op. (A pre-9.0 board carrying a legacy
# (pcbplotparams (viasonmask no)) flag is the one exception, out of scope here.)
SIDED_DEFAULTS = {"tenting": True, "covering": False, "plugging": False}

# The order KiCad writes (setup ...) children, used only when creating a fresh block.
_SETUP_ORDER = (
    "pad_to_mask_clearance",
    "solder_mask_min_width",
    "pad_to_paste_clearance",
    "pad_to_paste_clearance_ratio",
    "allow_soldermask_bridges_in_footprints",
    "tenting",
    "covering",
    "plugging",
    "capping",
    "filling",
    "aux_axis_origin",
    "grid_origin",
)

# Blocks a (setup ...) normally follows, most-preferred first (KiCad's natural ordering).
_PREAMBLE_PRIORITY = (
    "layers",
    "general",
    "paper",
    "title_block",
    "generator_version",
    "generator",
    "version",
)

# A fresh (general ...) block is placed right after the preamble (version/generator),
# before (paper)/(title_block)/(layers)/(setup) - KiCad's canonical (general) position.
_GENERAL_ANCHOR_PRIORITY = ("generator_version", "generator", "version")

_SIDED_FRIENDLY = {
    f"{key}_{side}": (key, side)
    for key in SETUP_SIDED_KEYS
    for side in ("front", "back")
}


def resolve_key(name: str) -> str | None:
    """Map a friendly/alias flat key to its real (setup ...) key, pass a real key through,
    or return None for an unsupported name. Sided friendly keys (e.g. `tenting_front`) are
    handled separately and are not returned here."""
    if name in SETUP_NUMERIC_KEYS or name in SETUP_COORD_KEYS or name in SETUP_BOOL_KEYS:
        return name
    return KEY_ALIASES.get(name)


def _to_float(atom: str) -> float | None:
    try:
        return float(atom)
    except (TypeError, ValueError):
        return None


def _fmt_num(v) -> str:
    """Format a number the way KiCad does: integral values as bare ints, else up to 6
    decimals with trailing zeros trimmed. Normalises -0 to 0."""
    f = float(v)
    if f == 0.0:
        f = 0.0  # kill negative zero
    if f == int(f):
        return str(int(f))
    s = ("%.6f" % f).rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _as_bool(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("yes", "true", "1", "on")
    return bool(v)


def _bool_atom(on: bool) -> str:
    return "yes" if on else "no"


def _indent_unit(text: str) -> str:
    """One indentation unit: the leading whitespace of the first indented list line.
    Defaults to a single tab (KiCad's on-disk convention)."""
    for line in text.split("\n"):
        stripped = line.lstrip(" \t")
        if stripped.startswith("(") and stripped != line:
            return line[: len(line) - len(stripped)]
    return "\t"


class Board:
    """A .kicad_pcb wrapped for byte-preserving (setup ...) edits."""

    def __init__(self, doc: SexpDocument):
        self._doc = doc
        if doc.root.name != "kicad_pcb":
            raise KiCadFileError("not a .kicad_pcb file (missing kicad_pcb)")

    @classmethod
    def load(cls, path) -> "Board":
        return cls(SexpDocument.load(path))

    def serialize(self) -> str:
        return self._doc.serialize()

    def save(self, path) -> None:
        self._doc.save(path)

    def _reload(self) -> None:
        # A freshly inserted node's span points into its own fragment, so re-parse the
        # serialized text before any further find/edit can safely target it.
        self._doc = SexpDocument.parse(self._doc.serialize())

    # -- read -----------------------------------------------------------------

    def setup(self, include_aliases: bool = True) -> dict:
        """The supported (setup ...) keys present on the board. Numeric -> float, coord ->
        (x, y) float tuple, flat bool -> bool, sided -> `<key>_front`/`<key>_back` bools.
        Absent keys are omitted. When `include_aliases`, the friendly ProjectSettings names
        also mirror their real counterpart. Returns {} when there is no (setup ...) block.
        Reads the canonical KiCad-9+ nested via-protection form; a legacy bare `(tenting ..)`
        (which current KiCad never writes) reports as absent and is normalized on the next
        write."""
        setup = self._doc.root.find("setup")
        if setup is None:
            return {}
        out: dict = {}
        for child in setup.children:
            if child.is_atom:
                continue
            name = child.name
            kids = child.children
            if name in SETUP_NUMERIC_KEYS:
                if len(kids) >= 2:
                    v = _to_float(kids[1].value)
                    if v is not None:
                        out[name] = v
            elif name in SETUP_BOOL_KEYS:
                if len(kids) >= 2:
                    out[name] = _as_bool(kids[1].value)
            elif name in SETUP_COORD_KEYS:
                if len(kids) >= 3:
                    x, y = _to_float(kids[1].value), _to_float(kids[2].value)
                    if x is not None and y is not None:
                        out[name] = (x, y)
            elif name in SETUP_SIDED_KEYS:
                for side in ("front", "back"):
                    sn = child.find(side)
                    if sn is not None and len(sn.children) >= 2:
                        out[f"{name}_{side}"] = _as_bool(sn.children[1].value)
        if include_aliases:
            for alias, real in KEY_ALIASES.items():
                if real in out and alias not in out:
                    out[alias] = out[real]
        return out

    def general(self) -> dict:
        """Scalar children of the board's (general ...) block. Currently exposes
        `thickness` (the overall board thickness in mm, KiCad's `(thickness N)`
        atom); other (general) children (e.g. legacy_teardrops) are preserved on
        write but not surfaced here. Returns {} when there is no (general) block."""
        gen = self._doc.root.find("general")
        if gen is None:
            return {}
        out: dict = {}
        node = gen.find("thickness")
        if node is not None and len(node.children) >= 2:
            v = _to_float(node.children[1].value)
            if v is not None:
                out["thickness"] = v
        return out

    def thickness(self) -> float | None:
        """The board's overall thickness in mm (from (general (thickness N))), or
        None when the board declares no thickness."""
        return self.general().get("thickness")

    # -- write ----------------------------------------------------------------

    def set_setup_key(self, key: str, value) -> None:
        """Set a single (setup ...) key (real, alias, or sided friendly name)."""
        self.set_setup({key: value})

    def set_setup(self, values: dict) -> None:
        """Update the given (setup ...) keys in place, inserting any that are absent, and
        creating the (setup ...) block itself if the board has none. Real keys, friendly
        aliases, and sided friendly names (`tenting_front` etc.) are accepted; unsupported
        keys are ignored. All other board content and formatting is preserved."""
        flat, sided = _normalize(values)
        if not flat and not sided:
            return
        setup = self._doc.root.find("setup")
        if setup is None:
            self._create_setup_block(flat, sided)
            return

        inserted = False
        for key, val in flat.items():
            node = setup.find(key)
            if node is not None:
                self._set_flat_in_place(node, key, val)
            else:
                setup.insert_child_text(self._render_flat(key, val))
                inserted = True
        for key, sides in sided.items():
            node = setup.find(key)
            if node is None:
                front = sides.get("front", SIDED_DEFAULTS[key])
                back = sides.get("back", SIDED_DEFAULTS[key])
                setup.insert_child_text(self._render_sided(key, front, back))
                inserted = True
            elif _is_nested_sided(node):
                for side, on in sides.items():
                    side_node = node.find(side)
                    if side_node is not None and len(side_node.children) >= 2:
                        side_node.children[1].set_value(_bool_atom(on), quote=False)
                    else:
                        node.insert_child_text(f"({side} {_bool_atom(on)})")
                        inserted = True
            else:
                # A legacy bare form ((tenting none) / (tenting yes no), read-only compat
                # KiCad no longer writes) or a malformed node: replace it wholesale with the
                # canonical nested form rather than splice a child into it. Read the node's
                # CURRENT per-side values so a side the caller did not name is preserved, not
                # reset to a default (that would silently flip mask coverage).
                current = _read_sided(node)
                front = sides.get("front", current.get("front", SIDED_DEFAULTS[key]))
                back = sides.get("back", current.get("back", SIDED_DEFAULTS[key]))
                self._doc.replace_span(*node.span, self._render_sided(key, front, back))
                inserted = True

        if inserted:
            self._reload()

    def set_thickness(self, value) -> None:
        """Set the board's overall thickness (mm) in (general (thickness N)),
        editing the (thickness) atom in place when present, inserting one into an
        existing (general) block, or creating a (general) block (right after the
        preamble, before any (paper)/(layers)/(setup)) when the board has none.
        Byte-preserving: only the thickness value (or the new block) changes."""
        gen = self._doc.root.find("general")
        if gen is None:
            self._create_general_block(value)
            return
        node = gen.find("thickness")
        if node is not None and len(node.children) >= 2:
            node.children[1].set_value(_fmt_num(value), quote=False)
        elif node is not None:
            # Malformed thickness node (unexpected arity): replace its whole span.
            self._doc.replace_span(*node.span, f"(thickness {_fmt_num(value)})")
            self._reload()
        else:
            gen.insert_child_text(f"(thickness {_fmt_num(value)})")
            self._reload()

    def _create_general_block(self, thickness) -> None:
        text = self._doc.text
        unit = _indent_unit(text)
        nl = "\r\n" if "\r\n" in text else "\n"
        block = (
            "(general" + nl + unit * 2 + f"(thickness {_fmt_num(thickness)})" + nl + unit + ")"
        )
        root = self._doc.root
        anchor = None
        for name in _GENERAL_ANCHOR_PRIORITY:
            nodes = root.find_all(name)
            if nodes:
                anchor = nodes[-1]
                break
        if anchor is not None:
            root.insert_after(anchor, block)
        else:  # no reachable preamble child: place it inside the root
            root.insert_child_text(block)
        self._reload()

    def _set_flat_in_place(self, node, key: str, val) -> None:
        kids = node.children
        if key in SETUP_COORD_KEYS:
            seq = list(val)
            if len(kids) >= 3 and len(seq) >= 2:
                kids[1].set_value(_fmt_num(seq[0]), quote=False)
                kids[2].set_value(_fmt_num(seq[1]), quote=False)
                return
        elif key in SETUP_BOOL_KEYS:
            if len(kids) >= 2:
                kids[1].set_value(_bool_atom(_as_bool(val)), quote=False)
                return
        else:  # numeric / ratio
            if len(kids) >= 2:
                kids[1].set_value(_fmt_num(val), quote=False)
                return
        # Malformed node (unexpected arity): replace the whole node span.
        self._doc.replace_span(*node.span, self._render_flat(key, val))

    def _render_flat(self, key: str, val) -> str:
        if key in SETUP_BOOL_KEYS:
            return f"({key} {_bool_atom(_as_bool(val))})"
        if key in SETUP_COORD_KEYS:
            seq = list(val)
            if len(seq) < 2:
                raise ValueError(f"{key} needs 2 coordinates, got {val!r}")
            return f"({key} {_fmt_num(seq[0])} {_fmt_num(seq[1])})"
        return f"({key} {_fmt_num(val)})"

    def _render_sided(self, key: str, front: bool, back: bool) -> str:
        return f"({key} (front {_bool_atom(front)}) (back {_bool_atom(back)}))"

    def _create_setup_block(self, flat: dict, sided: dict) -> None:
        text = self._doc.text
        unit = _indent_unit(text)
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = []
        rendered_keys = set()
        for key in _SETUP_ORDER:
            if key in SETUP_SIDED_KEYS and key in sided:
                front = sided[key].get("front", SIDED_DEFAULTS[key])
                back = sided[key].get("back", SIDED_DEFAULTS[key])
                lines.append(
                    unit * 2
                    + f"({key}"
                    + nl
                    + unit * 3
                    + f"(front {_bool_atom(front)})"
                    + nl
                    + unit * 3
                    + f"(back {_bool_atom(back)})"
                    + nl
                    + unit * 2
                    + ")"
                )
                rendered_keys.add(key)
            elif key in flat:
                lines.append(unit * 2 + self._render_flat(key, flat[key]))
                rendered_keys.add(key)
        # Defensive: any supported key not in the canonical order still gets written.
        for key, val in flat.items():
            if key not in rendered_keys:
                lines.append(unit * 2 + self._render_flat(key, val))
        block = "(setup" + nl + nl.join(lines) + nl + unit + ")"

        anchor = self._preamble_anchor()
        if anchor is not None:
            self._doc.root.insert_after(anchor, block)
        else:  # no reachable preamble child: place it inside the root
            self._doc.root.insert_child_text(block)
        self._reload()

    def _preamble_anchor(self):
        root = self._doc.root
        for name in _PREAMBLE_PRIORITY:
            nodes = root.find_all(name)
            if nodes:
                return nodes[-1]
        reals = [c for c in root.children if not c.is_atom]
        return reals[-1] if reals else None


def _is_nested_sided(node) -> bool:
    """True when a via-protection node uses the canonical KiCad-9+ nested form
    (X (front ..) (back ..)), i.e. it has at least one (front)/(back) child list."""
    return node.find("front") is not None or node.find("back") is not None


def _read_sided(node) -> dict:
    """Best-effort current {front, back} bools for a via-protection node, tolerating the
    canonical nested form and the legacy bare forms KiCad still reads: the enumerated
    keyword form ((tenting front back) / (tenting front) / (tenting none)) and a positional
    yes/no form ((tenting yes no)). Used to preserve an unspecified side when normalizing."""
    nested = {}
    for side in ("front", "back"):
        sn = node.find(side)
        if sn is not None and len(sn.children) >= 2:
            nested[side] = _as_bool(sn.children[1].value)
    if nested:
        return nested
    atoms = [c.value.strip().lower() for c in node.children[1:] if c.is_atom]
    if not atoms or "none" in atoms:
        return {"front": False, "back": False}
    if set(atoms) <= {"front", "back"}:  # keyword-flag form: a named side is tented
        return {"front": "front" in atoms, "back": "back" in atoms}
    return {  # positional yes/no bare form
        "front": _as_bool(atoms[0]),
        "back": _as_bool(atoms[1]) if len(atoms) > 1 else _as_bool(atoms[0]),
    }


def _normalize(values: dict):
    """Split an incoming {key: value} dict into resolved flat keys and grouped sided keys,
    dropping unsupported keys. Aliases resolve first; a real key wins over an alias that
    targets the same real key (so a round-tripped alias collapses to one node)."""
    flat: dict = {}
    sided: dict = {}
    for k, v in values.items():
        if k in KEY_ALIASES:
            flat[KEY_ALIASES[k]] = v
    for k, v in values.items():
        if k in SETUP_NUMERIC_KEYS or k in SETUP_COORD_KEYS or k in SETUP_BOOL_KEYS:
            flat[k] = v
        elif k in _SIDED_FRIENDLY:
            base, side = _SIDED_FRIENDLY[k]
            sided.setdefault(base, {})[side] = _as_bool(v)
    return flat, sided
