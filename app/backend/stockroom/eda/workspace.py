"""Put the EDA registry's hygiene rules into a REAL repo, without owning the file they land in.

The registry has produced `.gitignore` / `.gitattributes` content since `01fd28f` and nothing ever
wrote it, which left the measured cause of the owner's KiCad peer-sync failures unfixed: KiCad's
per-user files (`.kicad_prl` holds one user's window state, `fp-info-cache` is a regenerated machine
cache) mutate on every open, so once committed, two peers conflict on every pull while the actual
design sources merge perfectly.

Two facts shape this module, and both were measured rather than assumed:

  1. **Stockroom does not own the user's project files.** A registered project very often already has
     its own `.gitignore`, so the generated content goes into a DELIMITED MANAGED BLOCK that is
     rewritten in place; everything outside the markers is preserved byte for byte. This is the
     pattern conda-init / rustup / nvm already use, adopted rather than invented.

  2. **A `.gitignore` rule does nothing to an already-TRACKED file.** Verified against git directly:
     after committing `board.kicad_prl` and then ignoring `*.kicad_prl`, git still listed it in
     `ls-files` and still reported it modified. In the owner's repos those files are already
     committed, which is exactly why they conflict, so untracking (`git rm --cached`, which leaves
     the working copy on disk) is part of the operation, not a follow-up. Writing the file alone
     would have been a feature that commits something and changes nothing observable.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import fnmatch

BEGIN = "# >>> Stockroom managed block >>>"
END = "# <<< Stockroom managed block <<<"

_NOTE = (
    "# Everything between these markers is generated from Stockroom's EDA tool registry and is\n"
    "# regenerated on every sync, so do not hand-edit inside them. Put your own rules OUTSIDE the\n"
    "# markers; those are preserved exactly as you wrote them.\n"
)


def merge_block(existing: str, body: str) -> str:
    """`existing` with the managed block set to `body`, preserving every line outside the markers.

    Appends the block when absent, replaces it in place when present (so a rule set that changed does
    not accumulate a second block), and is idempotent for an unchanged rule set.

    Raises ValueError for a file whose block is OPENED but never closed. That means a previous run
    died mid-write or a human edited the markers; appending a second block would be wrong and
    deleting to end-of-file would destroy whatever follows, so the honest move is to refuse loudly
    and let a person look.
    """
    text = existing or ""
    block = f"{BEGIN}\n{_NOTE}{body if body.endswith(chr(10)) else body + chr(10)}{END}\n"
    start = text.find(BEGIN)
    if start == -1:
        if not text:
            return block
        prefix = text if text.endswith("\n") else text + "\n"
        return f"{prefix}\n{block}"
    end = text.find(END, start)
    if end == -1:
        raise ValueError(
            "this file has an unterminated Stockroom managed block; it was edited by hand or a "
            "previous sync did not finish. Fix or remove the stray marker, then sync again."
        )
    tail = text[end + len(END):]
    tail = tail[1:] if tail.startswith("\n") else tail
    return text[:start] + block + tail


def matching(paths, rules) -> list[str]:
    """Every path in `paths` that the gitignore-style `rules` cover, in the given order.

    Deliberately narrow: it supports exactly the two shapes the registry emits, a filename glob
    (`*.kicad_prl`, `fp-info-cache`) and a directory rule (`*-backups/`), matched against the path's
    basename and against each of its directory components respectively. It is NOT a general
    gitignore engine, because the only thing it feeds is an UNTRACK decision, and a rule this code
    misunderstands would untrack a file the user actually wants. Anything unsupported simply does not
    match, which fails safe: the file stays tracked and the user can say so.
    """
    out: list[str] = []
    for path in paths or []:
        text = str(path).replace("\\", "/").strip()
        if not text:
            continue
        parts = text.split("/")
        name = parts[-1]
        for raw in rules or ():
            rule = str(raw or "").strip()
            if not rule or rule.startswith("#"):
                continue
            if rule.endswith("/"):
                if any(fnmatch.fnmatch(seg, rule[:-1]) for seg in parts[:-1]):
                    out.append(text)
                    break
                continue
            if fnmatch.fnmatch(name, rule) or fnmatch.fnmatch(text, rule):
                out.append(text)
                break
    return out
