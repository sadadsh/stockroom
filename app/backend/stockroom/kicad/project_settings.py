"""The targeted .kicad_pro JSON editor (M7e).

A .kicad_pro is JSON, but Stockroom does not own it: KiCad wrote it and will read
it back, so an edit must stay a MINIMAL DIFF (only the changed keys differ) exactly
as the s-expression layer keeps .kicad_pcb/.kicad_sch byte-preserving. KiCad
serializes the file with nlohmann::json (2-space indent, alphabetically-sorted keys,
one trailing newline); `serialize` reproduces that format byte-for-byte (verified
against a real KiCad 10 project, version 20260206), so re-writing an unchanged file
KiCad itself wrote yields zero diff and an edit changes only the edited value.

The minimal-diff guarantee holds for a file already in KiCad's canonical format (the
normal case: KiCad wrote it). A .kicad_pro that is NOT canonical (hand-edited, a git
merge artifact, a different indent or key order) is rewritten into the canonical format
on the first save. That is correct (KiCad would canonicalize it on its own next save too)
and never loses data, but that one save is a larger diff, not a single-value change.

`merge` is a KinJector-style recursive partial-merge: a patch touches only the keys
it names, recursing into nested objects so editing net classes never rewrites the
design-rules block. Lists are replaced wholesale (the caller computes the full new
list upstream, e.g. the reconciled net-class list). The Transaction owns the
git-atomic commit and the parse-validate; this module owns the byte edit.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path


def parse(text: str) -> dict:
    return json.loads(text)


def serialize(data: dict) -> str:
    """KiCad's exact .kicad_pro serialization: 2-space indent, sorted keys, one
    trailing newline. Matches nlohmann::json's dump byte-for-byte so an untouched
    project file never churns."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def merge(base: dict, patch: dict) -> dict:
    """Return a NEW dict = base with patch deep-merged in. A key whose value is a dict
    in BOTH is recursed (so a partial patch preserves sibling keys); anything else
    (scalar, list, or a type change) is replaced by the patch value.

    The result shares NO mutable state with either argument: a container preserved from
    base (a list, or a nested dict on a key the patch does not touch) is deep-copied, as
    is a container taken from the patch, so a later caller mutating the result cannot
    reach back into base or patch. This is what makes the no-mutation contract real."""
    out = copy.deepcopy(base)
    for key, pval in patch.items():
        bval = out.get(key)
        if isinstance(bval, dict) and isinstance(pval, dict):
            out[key] = merge(bval, pval)
        else:
            out[key] = copy.deepcopy(pval)
    return out


def apply_patch_text(text: str, patch: dict, replace_keys: tuple = ()) -> str:
    """Load .kicad_pro text, partial-merge the patch, re-serialize in KiCad's format.
    An empty patch returns byte-identical text.

    `replace_keys` names TOP-LEVEL keys whose merged value is then overwritten WHOLESALE
    by the patch value (deep-copied), instead of being deep-merged. The merge can only
    add or update keys, so it can never DELETE one; a wholesale replace is how a caller
    expresses the full desired state of a map (e.g. text_variables) where a key absent
    from the desired map means "delete it". A replace_key the patch does not carry is
    left as merged (no KeyError), so a caller can pass a fixed tuple without guarding
    each key's presence."""
    out = merge(parse(text), patch)
    for key in replace_keys:
        if key in patch:
            out[key] = copy.deepcopy(patch[key])
    return serialize(out)


def apply_patch(path, patch: dict, replace_keys: tuple = ()) -> None:
    """Read the .kicad_pro at `path`, apply the partial-merge (with any `replace_keys`
    overwritten wholesale), write it back (utf-8). The caller wraps this in a Transaction,
    which tracks the path, re-parses it to validate, commits it, and rolls it back on any
    failure.

    newline="" on the write disables newline translation so KiCad's LF-terminated
    .kicad_pro is not rewritten to CRLF on Windows (which would defeat the minimal
    diff on every save)."""
    p = Path(path)
    with open(p, encoding="utf-8", newline="") as fh:
        text = fh.read()
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(apply_patch_text(text, patch, replace_keys=replace_keys))
