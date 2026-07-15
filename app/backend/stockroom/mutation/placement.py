"""Primitives that place a part's files into the per-category libraries.

Merging a symbol into an existing .kicad_sym and copying a footprint into a
.pretty are the building blocks of add_part (Task 13). Both preserve the target
file's bytes via the M1 span layer; the symbol merge is gated so it can only
ADD nodes, never lose or mutate existing ones (spec sections 5 and 8).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from stockroom.kicad.footprint import Footprint
from stockroom.kicad.symbol_lib import Symbol, SymbolLib
from stockroom.model.part import PartRecord
from stockroom.sexp.document import SexpDocument, quote_kicad
from stockroom.verify.semdiff import semantic_diff


class PlacementError(Exception):
    pass


def assert_only_added(before: str, after: str) -> None:
    diffs = semantic_diff(before, after)
    bad = [d for d in diffs if not d.startswith("ADDED")]
    if bad:
        raise PlacementError("expected only additions, got: " + "; ".join(bad[:5]))


def _symbol_node_text(source: Path, source_name: str) -> str:
    """Return the exact source bytes of the (symbol "<source_name>" ...) node."""
    doc = SexpDocument.load(source)
    for node in doc.root.find_all("symbol"):
        kids = node.children
        if len(kids) >= 2 and kids[1].value == source_name:
            start, end = node.span
            return doc.text[start:end]
    raise PlacementError(f"symbol {source_name!r} not found in {source.name}")


def merge_symbol_into_lib(
    lib_path: Path, symbol_source: Path, source_name: str, new_name: str
) -> None:
    lib = SymbolLib.load(lib_path)
    if new_name in lib.symbol_names:
        raise PlacementError(f"symbol {new_name!r} already in {Path(lib_path).name}")
    node_text = _symbol_node_text(Path(symbol_source), source_name)
    # rename only the symbol's own name token: (symbol "<source_name>" -> new_name.
    # The name is the first string token right after 'symbol'; replace just that.
    renamed = re.sub(
        r'^\(symbol\s+' + re.escape(quote_kicad(source_name)),
        f"(symbol {quote_kicad(new_name)}",
        node_text,
        count=1,
    )
    if renamed == node_text and source_name != new_name:
        raise PlacementError(f"could not rename symbol {source_name!r}")
    before = lib.serialize()
    lib.insert_symbol(renamed)  # append the symbol node (byte-preserving)
    after = lib.serialize()
    assert_only_added(before, after)
    Path(lib_path).write_text(after, encoding="utf-8", newline="")


def place_footprint(pretty_dir: Path, footprint_source: Path, new_name: str) -> Path:
    pretty_dir = Path(pretty_dir)
    pretty_dir.mkdir(parents=True, exist_ok=True)
    dst = pretty_dir / f"{new_name}.kicad_mod"
    shutil.copyfile(footprint_source, dst)
    # rewrite the internal footprint name token to new_name (first string after
    # 'footprint'), byte-preserving everything else.
    fp = Footprint.load(dst)
    fp.set_name(new_name)
    dst.write_text(fp.serialize(), encoding="utf-8", newline="")
    return dst


def _datasheet_value(record: PartRecord) -> str:
    if record.datasheet and record.datasheet.file:
        return f"${{SR_LIB}}/datasheets/{record.datasheet.file}"
    if record.datasheet and record.datasheet.source_url:
        return record.datasheet.source_url
    return ""


def kicad_visible_properties(record: PartRecord) -> dict[str, str]:
    """The KiCad-visible subset mirrored into a symbol, as {property: value}.
    Single source of truth for both writing (mirror) and drift detection."""
    values = {
        "MPN": record.mpn,
        "Manufacturer": record.manufacturer,
        "Description": record.description,
        "ki_keywords": " ".join(record.tags),
        "Datasheet": _datasheet_value(record),
    }
    if record.purchase and record.purchase[0].url:
        values["Purchase"] = record.purchase[0].url
    return {k: v for k, v in values.items() if v}


def mirror_fields_to_symbol(symbol: Symbol, record: PartRecord) -> None:
    # hidden: these are metadata for KiCad's field views, never schematic text;
    # visible they would splat URLs over a schematic and drown the symbol preview
    for name, value in kicad_visible_properties(record).items():
        symbol.set_property(name, value, hide=True)
