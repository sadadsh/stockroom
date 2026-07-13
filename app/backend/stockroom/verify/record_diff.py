"""Structured field-level diff between two PartRecord JSON snapshots, and the
matching symbol-node extractor for the visual (SVG) diff.

The git timeline (M6k) reads a part's canonical JSON at two revisions with
``GitRepo.show_file`` (no working-tree checkout) and asks: what changed? A raw
textual diff of the JSON is unreadable; this walk produces a list of
``FieldChange`` items keyed by dotted path (``datasheet.file``, ``specs.pinout``)
so the UI can render "MPN: '' -> 'TPS62130'" instead of a hunk of JSON.

Nested objects are recursed into (so ``datasheet`` going from null to an object
reports the meaningful ``datasheet.file`` leaf, not a whole-object churn); lists
are treated as a single leaf (a collection reads as one field, not
``purchase[0].url`` noise). Purely functional, no git or filesystem dependency,
so it is exhaustively unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Internal / derived keys the timeline diff never shows a human: the id never
# changes, content hashes are noise, and enrichment is per-key provenance already
# implied by the spec/field it annotates.
DEFAULT_EXCLUDE: frozenset[str] = frozenset({"id", "hashes", "enrichment"})


@dataclass
class FieldChange:
    key: str
    before: Any
    after: Any
    status: str  # "added" | "removed" | "changed"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "before": self.before,
            "after": self.after,
            "status": self.status,
        }


def _is_empty(v: Any) -> bool:
    """A leaf that carries no information: absent, blank, or an empty collection.
    Used to classify a leaf change as added vs removed vs changed."""
    return v is None or v == "" or v == [] or v == {}


def _walk(before: Any, after: Any, prefix: str, out: list[FieldChange]) -> None:
    # a dict on EITHER side => recurse key-by-key, treating the missing/None side
    # as {} so a null-to-object transition flattens to its real leaf paths.
    if isinstance(before, dict) or isinstance(after, dict):
        b = before if isinstance(before, dict) else {}
        a = after if isinstance(after, dict) else {}
        for key in sorted(set(b) | set(a)):
            child = f"{prefix}.{key}" if prefix else key
            _walk(b.get(key), a.get(key), child, out)
        return
    # leaf: scalar, list, or None. == compares lists and scalars structurally.
    # both-empty (None vs "" vs [] vs absent) is not a change: a null field becoming
    # an empty string carries no information for the timeline.
    if before == after or (_is_empty(before) and _is_empty(after)):
        return
    if _is_empty(before):
        status = "added"
    elif _is_empty(after):
        status = "removed"
    else:
        status = "changed"
    out.append(FieldChange(key=prefix, before=before, after=after, status=status))


def field_diff(
    before: dict | None,
    after: dict | None,
    exclude: frozenset[str] | set[str] = DEFAULT_EXCLUDE,
) -> list[FieldChange]:
    """Ordered field changes turning ``before`` into ``after``. Either side may be
    None (the part did not exist at that revision) and is treated as an empty
    record, so a first commit reads as every field added and a deletion as every
    field removed. Top-level keys in ``exclude`` are ignored entirely."""
    b = {k: v for k, v in (before or {}).items() if k not in exclude}
    a = {k: v for k, v in (after or {}).items() if k not in exclude}
    out: list[FieldChange] = []
    _walk(b, a, "", out)
    return out


def extract_symbol_node(lib_text: str, name: str) -> str | None:
    """The paren-balanced ``(symbol "NAME" ...)`` block for the exact top-level symbol
    ``name`` in a .kicad_sym file's text, including its nested sub-unit symbols, or
    None if absent. Used to detect (and to isolate) a single part's symbol geometry
    change across two revisions when the category lib holds many parts. Balances
    parentheses while respecting quoted strings, so a value containing ``(`` or ``)``
    never throws off the scan; matches only the exact top-level name, never a
    ``NAME_1_1`` sub-unit."""
    target = f'symbol "{name}"'  # the trailing quote pins the exact name
    depth = 0
    in_str = False
    i = 0
    n = len(lib_text)
    while i < n:
        c = lib_text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            # a top-level symbol's open paren is a direct child of the root list, i.e.
            # encountered while depth == 1; a sub-unit sits at depth >= 2 and is skipped.
            if depth == 1:
                j = i + 1
                while j < n and lib_text[j] in " \t\r\n":
                    j += 1
                if lib_text.startswith(target, j):
                    return _balanced_block(lib_text, i)
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return None


def _balanced_block(text: str, start: int) -> str | None:
    depth = 0
    in_str = False
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None  # unbalanced input
