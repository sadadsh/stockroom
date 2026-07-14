"""Byte-preserving object conform for M7f-B: retroactively normalize the font size (and, where
a font carries one, its thickness) of EXISTING text objects across a KiCad project to a house
standard.

KiCad's Board Setup only sets defaults for newly-placed items; existing footprint text, board
text, schematic text, and net labels keep whatever size they were drawn at. This does what
KiCad's "Edit Text & Graphics Properties" global edit does, headlessly and by type, so a whole
project can be brought onto a standard. The COMPUTE is ported by behavior from the retired
`nd_object_conform.py`, but every edit routes through Stockroom's byte-preserving `SexpDocument`
(the one and only `.kicad_*` editor): only the (size ...)/(thickness ...) atoms inside a matching
text object's font change, so the file is never reformatted and a re-conform is a byte-identical
no-op.

Node scope (verified against real KiCad-10 fixtures, an improvement over the reference's
whole-file regex):
  PCB  - fp_text + gr_text + property, by layer: silk / fab / copper. On KiCad 8+/10 boards a
         footprint's reference designator and value/field text are (property "Reference"/... (layer)
         (effects (font)))) nodes, NOT (fp_text reference/value) (which only pre-KiCad-8 boards
         wrote), so the walk MUST include property to conform the reference designators (the most
         common silk text). A .kicad_pcb has no footprint-library cache, so a recursive walk reaches
         exactly placed content; a bare (size X Y) is a PAD size (the pad node is not walked and has
         no (layer) in a category), so the font-scoped edit never touches it. Copper matches ANY
         copper layer (F.Cu / B.Cu / In*.Cu), since board copper text can sit on an inner layer.
  SCH  - the top-level (direct-child) text / label / global_label / hierarchical_label. lib_symbols
         is a SIBLING library cache whose embedded symbol graphics must never be resized, so the
         schematic conform iterates the root's direct children only and never descends into it.
         Schematic SYMBOL fields (a symbol instance's reference/value (property ...) text) are a
         separate KiCad category (EESCHEMA edits them apart from schematic text/graphics) and are
         intentionally out of scope here, matching the retired reference.

Sizes/thicknesses are millimetres (KiCad's on-disk unit). A target is
`{category: {"size": float|None, "thickness": float|None}}`; a None size/thickness leaves that
dimension untouched, and thickness is UPDATE-IF-PRESENT (a font with no explicit thickness keeps
KiCad's default rather than gaining a manufactured token on every default-thickness object).

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

from stockroom.sexp.document import SexpDocument, SexpNode

# The board-text categories. silk / fab match a fixed front+back layer pair; copper matches ANY
# copper layer (F.Cu, B.Cu, and In*.Cu inner layers on a multilayer board). Text on a layer
# outside these (e.g. a courtyard or comment layer) is left alone.
PCB_FIXED_LAYERS: dict[str, tuple[str, ...]] = {
    "silk": ("F.SilkS", "B.SilkS"),
    "fab": ("F.Fab", "B.Fab"),
}
PCB_CATEGORIES: tuple[str, ...] = ("silk", "fab", "copper")

# The schematic categories and the node names each covers. `text` is sheet graphic text; `labels`
# groups the three net-label kinds KiCad writes.
SCH_NAMES: dict[str, tuple[str, ...]] = {
    "text": ("text",),
    "labels": ("label", "global_label", "hierarchical_label"),
}
SCH_CATEGORIES: tuple[str, ...] = ("text", "labels")

# The list-node names that carry conformable board text: gr_text (board), fp_text (footprint user
# text), and property (a footprint's reference designator / value / field text on KiCad 8+/10). A
# property without a (layer) in a category (board metadata) or without a font is skipped by the
# filters below, so only real on-board footprint text is touched.
_PCB_TEXT_NAMES = ("fp_text", "gr_text", "property")


def _fmt(v) -> str:
    """Format a length the way KiCad writes it on disk: an integral value as a bare int, else up
    to 6 decimals with trailing zeros trimmed, negative zero normalised to 0. Matches
    board._fmt_num so a conformed value round-trips byte-identically with what KiCad would emit."""
    f = float(v)
    if f == 0.0:
        f = 0.0  # kill negative zero
    if f == int(f):
        return str(int(f))
    s = ("%.6f" % f).rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _find_font(node: SexpNode) -> SexpNode | None:
    """The first (font ...) node anywhere inside a text object (KiCad nests it under (effects ...)).
    A text object carries exactly one font, so the first descendant match is its own."""
    for d in node.iter_descendants():
        if d.name == "font":
            return d
    return None


def _node_layer(node: SexpNode) -> str | None:
    """The node's single (layer "X") value, or None when it has no (layer) child (e.g. a board
    metadata property, or a pad which carries a plural (layers ...) not this singular form)."""
    layer = node.find("layer")
    if layer is not None and len(layer.children) >= 2:
        return layer.children[1].value
    return None


def _layer_in_category(layer_value: str, cat: str) -> bool:
    """Whether a layer belongs to a conform category. Copper is any *.Cu layer (outer F/B plus
    inner In*.Cu); silk / fab are their fixed front+back pair."""
    if cat == "copper":
        return layer_value.endswith(".Cu")
    return layer_value in PCB_FIXED_LAYERS[cat]


def _set_font(node: SexpNode, size, thickness) -> bool:
    """Set the font size (square, both atoms = `size`) and, if the font already carries a
    thickness atom, its thickness on one text object. Only atoms whose current text differs from
    the KiCad-canonical target are rewritten, so a no-op is a true no-op (idempotent, zero float
    drift). Returns True when at least one atom actually changed."""
    font = _find_font(node)
    if font is None:
        return False
    changed = False
    if size is not None:
        target = _fmt(size)
        size_node = font.find("size")
        if size_node is not None and len(size_node.children) >= 3:
            for atom in (size_node.children[1], size_node.children[2]):
                if atom.value != target:
                    atom.set_value(target, quote=False)
                    changed = True
    if thickness is not None:
        target = _fmt(thickness)
        th_node = font.find("thickness")
        if th_node is not None and len(th_node.children) >= 2:
            atom = th_node.children[1]
            if atom.value != target:
                atom.set_value(target, quote=False)
                changed = True
    return changed


def conform_pcb(doc: SexpDocument, targets: dict) -> dict[str, int]:
    """Normalize the fonts of the board's text objects to `targets`
    ({category: {"size", "thickness"}} over PCB_CATEGORIES). Rewrites fp_text + gr_text on the
    matching layers, byte-preservingly, in place on `doc`. Returns {category: changed_count}.
    Categories are layer-disjoint, so each text object is considered for at most one category."""
    text_nodes = [n for n in doc.root.iter_descendants() if n.name in _PCB_TEXT_NAMES]
    counts: dict[str, int] = {}
    for cat in PCB_CATEGORIES:
        target = targets.get(cat)
        if not target:
            continue
        n = 0
        for node in text_nodes:
            layer = _node_layer(node)
            if layer is None or not _layer_in_category(layer, cat):
                continue
            if _set_font(node, target.get("size"), target.get("thickness")):
                n += 1
        counts[cat] = n
    return counts


def conform_sch(doc: SexpDocument, targets: dict) -> dict[str, int]:
    """Normalize the fonts of the schematic's top-level text + net labels to `targets`
    ({category: {"size", "thickness"}} over SCH_CATEGORIES), byte-preservingly, in place on `doc`.
    Iterates the root's DIRECT children only, so lib_symbols (the library cache) is never touched.
    Returns {category: changed_count}."""
    root = doc.root
    counts: dict[str, int] = {}
    for cat in SCH_CATEGORIES:
        target = targets.get(cat)
        if not target:
            continue
        n = 0
        for name in SCH_NAMES[cat]:
            for node in root.find_all(name):
                if _set_font(node, target.get("size"), target.get("thickness")):
                    n += 1
        counts[cat] = n
    return counts


def conform_document(doc: SexpDocument, pcb_targets: dict, sch_targets: dict) -> dict[str, int]:
    """Conform a single parsed document, routing by its root node name (kicad_pcb -> pcb targets,
    kicad_sch -> sch targets). A document of neither kind yields no changes. Edits are applied in
    place; the caller serializes to obtain the new bytes."""
    name = doc.root.name
    if name == "kicad_pcb":
        return conform_pcb(doc, pcb_targets or {})
    if name == "kicad_sch":
        return conform_sch(doc, sch_targets or {})
    return {}
