"""Independent semantic s-expression diff used as a write-verification gate.

Distinguishes harmless reformatting from token loss, mutation, or reordering.
Uses its own minimal parser so it can catch bugs in the edit layer.
"""

from __future__ import annotations

import difflib
import re

NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


class SemDiffError(Exception):
    pass


def _tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c, c
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    buf.append(text[j])
                    j += 1
            if j >= n:
                raise SemDiffError(f"unterminated string at index {i}")
            yield "str", "".join(buf)
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"':
                j += 1
            yield "atom", text[i:j]
            i = j


def _norm_atom(kind, val):
    if kind == "atom" and NUM_RE.match(val):
        return ("num", float(val))
    if kind == "str":
        v = val.replace('\\"', '"').replace("\\\\", "\\")
        if NUM_RE.match(v):
            return ("num", float(v))
        return ("s", v)
    return ("s", val)


def _parse(text):
    toks = list(_tokenize(text))
    pos = 0

    def read():
        nonlocal pos
        if pos >= len(toks):
            raise SemDiffError("unexpected end of input")
        kind, val = toks[pos]
        if kind == "(":
            pos += 1
            lst = []
            while pos < len(toks) and toks[pos][0] != ")":
                lst.append(read())
            if pos >= len(toks):
                raise SemDiffError("missing close paren")
            pos += 1
            return tuple(lst)
        pos += 1
        return _norm_atom(kind, val)

    root = read()
    if pos != len(toks):
        raise SemDiffError(f"trailing tokens at {pos}/{len(toks)}")
    return root


def _is_atom(t):
    return (
        isinstance(t, tuple)
        and len(t) == 2
        and t[0] in ("num", "s")
        and not isinstance(t[1], tuple)
    )


def _node_name(t):
    if not _is_atom(t) and isinstance(t, tuple) and t and _is_atom(t[0]):
        return t[0][1]
    return None


def _count(t):
    if isinstance(t, tuple) and t and not _is_atom(t):
        return 1 + sum(_count(c) for c in t)
    return 1


def _diff(a, b, path, out, cap):
    if len(out) >= cap:
        return
    if _is_atom(a) and _is_atom(b):
        if a != b:
            if a[0] == "num" and b[0] == "num" and abs(a[1] - b[1]) < 1e-9:
                return
            out.append(f"CHANGED {path}: {a[1]!r} -> {b[1]!r}")
        return
    if _is_atom(a) != _is_atom(b):
        out.append(f"TYPE-CHANGED {path}")
        return
    name = _node_name(a) or ""

    def sig(t):
        return ("A", t) if _is_atom(t) else ("L", _node_name(t), len(t))

    sm = difflib.SequenceMatcher(None, [sig(c) for c in a], [sig(c) for c in b], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if len(out) >= cap:
            break
        if tag in ("equal", "replace") and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                _diff(a[i1 + k], b[j1 + k], f"{path}/{name}[{i1 + k}]", out, cap)
        else:
            for k in range(i1, i2):
                out.append(f"LOST {path}/{name}: [{_count(a[k])} nodes]")
            for k in range(j1, j2):
                out.append(f"ADDED {path}/{name}: [{_count(b[k])} nodes]")


def semantic_diff(original: str, modified: str, cap: int = 200) -> list[str]:
    out: list[str] = []
    _diff(_parse(original), _parse(modified), "", out, cap)
    return out


def assert_only_changed(original: str, modified: str, *, allowed_changes: int) -> None:
    diffs = semantic_diff(original, modified)
    lost = [d for d in diffs if d.startswith(("LOST", "ADDED", "TYPE"))]
    changed = [d for d in diffs if d.startswith("CHANGED")]
    if lost:
        raise SemDiffError("structural change detected: " + "; ".join(lost[:5]))
    if len(changed) > allowed_changes:
        raise SemDiffError(
            f"expected <= {allowed_changes} changed atoms, got {len(changed)}: "
            + "; ".join(changed[:5])
        )
