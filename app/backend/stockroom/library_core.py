"""Pure, Qt-free, contract-agnostic KiCad name helpers for the shared library.

Copied by-behavior out of the retired PyQt ``LibraryManager`` (never imported: it drags
PyQt5 at module load). These helpers move name strings around; they do NOT know which
library a name belongs to. The caller supplies the KiCad nickname to qualify against.

In Stockroom that nickname is per category: ``category_nickname(cat)`` -> ``SR-<slug>``
(``model.category``), and KiCad resolves it through the ``SR_LIB`` env var and the
``${SR_LIB}/symbols|footprints|models/...`` layout that ``kicad.wiring`` registers. This
module deliberately does NOT encode the retired app's single flat ``MySymbols`` /
``MyFootprints`` / ``${MY3DMODELS}`` contract, which Stockroom replaced.

Deliberately a leaf: stdlib only, zero project imports, and no ``.kicad_*`` text
mutation. Reading and writing KiCad files route through the byte-preserving sexp layer
(``kicad.schematic`` / ``kicad.symbol_lib`` / ``kicad.footprint``); a component's
manufacturer identity lives in ``projects.identity``. This module only computes the
name strings those layers move around.
"""

from __future__ import annotations

import re
from pathlib import Path


def footprint_name(value: str) -> str:
    """The bare footprint name with any library nickname stripped.

    ``'STUSB4500QTR:QFN50'`` -> ``'QFN50'``; a bare ``'RM_10_ADI'`` is unchanged; an
    empty or whitespace-only value is ``''``.
    """
    value = (value or "").strip()
    return value.split(":")[-1] if value else ""


def qualify_footprint(value: str, nickname: str) -> str:
    """Return ``'<nickname>:<footprintName>'`` for the target footprint library.

    ``nickname`` is supplied by the caller (in Stockroom, ``category_nickname(cat)`` ->
    ``SR-<slug>``). Idempotent: re-qualifying an already-qualified or vendor-nicknamed
    value repoints it at ``nickname``. An empty value stays ``''``.
    """
    name = footprint_name(value)
    return f"{nickname}:{name}" if name else ""


def symbol_name_ref(name: str) -> str:
    """The bare symbol name from a lib_id or a plain name.

    ``'SR-resistors:R_10k'`` -> ``'R_10k'``; a bare ``'R_10k'`` is unchanged; empty is ``''``.
    """
    name = (name or "").strip()
    return name.split(":")[-1] if name else ""


def qualify_symbol(name: str, nickname: str) -> str:
    """Return ``'<nickname>:<symbolName>'`` for the target symbol library.

    This is what a placed schematic instance's ``(lib_id ...)`` must hold so KiCad
    resolves the symbol and, through it, the right footprint and 3D model. ``nickname``
    is supplied by the caller (in Stockroom, ``category_nickname(cat)`` -> ``SR-<slug>``).
    Idempotent; an empty value stays ``''``.
    """
    bare = symbol_name_ref(name)
    return f"{nickname}:{bare}" if bare else ""


def _norm_name(s: str) -> str:
    """A footprint/model name folded to lowercase alphanumerics for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def match_model_for_footprint(fp_stem: str | None, model_files: list[Path]) -> Path | None:
    """Best-effort match of a footprint to a 3D model file by normalized name.

    Footprint ``'IC_TPS2121RUXR'`` -> model ``'TPS2121RUXR.step'``. Matching is by the
    lowercase-alphanumeric-folded stem, ranked most-specific first:

    1. an exact normalized match wins outright;
    2. otherwise a model name contained IN the footprint stem (the longer such name
       explains more of the footprint, so longer wins);
    3. otherwise the footprint stem buried in a longer model name (the shorter such name
       carries less unrelated noise, so shorter wins).

    A normalized name shorter than four characters (on either side) is ignored so a short
    token cannot match noise. Ties break deterministically by file name, so the result
    does not depend on the order the caller enumerated ``model_files``. Returns ``None``
    for a blank/``None`` stem, no models, or no match. Pure over the passed list (the
    caller supplies the candidate paths; this reads no filesystem).
    """
    fpn = _norm_name(fp_stem or "")
    if len(fpn) < 4:
        return None
    scored: list[tuple[tuple[int, int], Path]] = []
    for m in model_files:
        mn = _norm_name(m.stem)
        if len(mn) < 4:
            continue
        if mn == fpn:
            rank = (2, 0)  # exact normalized match: unbeatable
        elif mn in fpn:
            rank = (1, len(mn))  # model explains part of the footprint; longer = more of it
        elif fpn in mn:
            rank = (0, -len(mn))  # footprint buried in a noisier name; shorter = closer to exact
        else:
            continue
        scored.append((rank, m))
    if not scored:
        return None
    best_rank = max(rank for rank, _ in scored)
    winners = [m for rank, m in scored if rank == best_rank]
    return min(winners, key=lambda p: p.name)
