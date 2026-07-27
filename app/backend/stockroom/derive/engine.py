"""THE derive engine: `sourced/` + identity -> the `derived` block. One function, no network.

Spec section 9, and its acceptance test verbatim: *"change the naming scheme, re-derive the entire
library, and lose nothing that was imported. If a re-derive can destroy imported data, the schema
is wrong. Concretely: a re-derive must be idempotent (run it twice, get identical records) and
lossless (the `sourced/` tree is never written by it)."*

Three properties, and each is a property of the CODE rather than of a promise:

  IDEMPOTENT   the block is a pure function of (identity, payload bytes, ruleset, scheme). Nothing
               here reads a clock, a random source, the filesystem beyond the payloads, or the
               record's existing derived block - so running it twice cannot differ. `derived_at`
               is the one timestamp, and it is passed IN by the caller for exactly this reason.
  LOSSLESS     this module does not import `model.sourced`'s writer, and cannot: see
               `assert_no_writer_imported`. The payloads are read through `read_payload` only.
  DISPOSABLE   `rederive` replaces the whole block and never merges with what was there. A block
               that were merged into would accumulate values whose source had been removed, which
               is the opposite of recomputable.

WHERE NORMALIZATION LIVES, and why it moved. `normalize_spec_key`/`normalize_spec_value` used to
run at IMPORT time (`enrich/pipeline.py`, `enrich/refresh.py`), which destroyed the winning value
AS THE SOURCE RETURNED IT - permanently, for all 158 of the owner's records. Normalizing is
legitimate HERE precisely because the raw answer now survives in `sourced/`: the derived block is
allowed to be opinionated because it is disposable, and the evidence it was computed from is not.

WHAT IS NOT DERIVED, and must never be computed here: `id`, `mpn`, `manufacturer`, `part_class`,
`assets`, `sources`, `tags`, `purchase`, `datasheet`, `provenance`. Identity is not derived (spec
rule 3) and assets arrive from a capture pass that must not be undone by a re-derive. This module
returns a `Derived` and mutates nothing but the block it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stockroom.derive.naming import DEFAULT_SCHEME, NameInputs, get_scheme
from stockroom.derive.payloads import known_sources, parse_one
from stockroom.enrich.schema import EnrichmentResult
from stockroom.model.derived import DERIVED_BY, Derived
from stockroom.model.part_id import is_valid_part_id
from stockroom.model.sourced import list_sources, read_json
from stockroom.model.spec_hygiene import normalize_specs

# The category a part sits in until something can classify it. Named rather than inlined: an
# unclassified part must read as unclassified, and a blank category would make it look filed.
UNFILED = "Other"


@dataclass(frozen=True)
class Identity:
    """The part facts a derivation may READ but never write.

    A frozen value object rather than the record, so a mistake in this module cannot write to
    identity: `record.mpn = ...` inside a derivation is the failure mode that would make `id`
    unstable, and this makes it a runtime error instead of a silent corruption.
    """

    mpn: str = ""
    manufacturer: str = ""
    part_class: str = "component"

    @classmethod
    def of(cls, record) -> "Identity":
        pc = getattr(record, "part_class", "component")
        return cls(
            mpn=getattr(record, "mpn", "") or "",
            manufacturer=getattr(record, "manufacturer", "") or "",
            part_class=getattr(pc, "value", pc) or "component",
        )


class _CategoryView:
    """The minimal record-shaped object `refile_category` and `derive_value` read.

    Both take "a record" but touch only `.category`, `.specs`, `.mpn`, `.description` and
    `.alternates`. Passing this instead of the real record is what stops a derivation from
    reaching `assets` or `sources` - see the NameInputs docstring for why that matters - and it
    is reuse-by-extraction rather than a second copy of either rule.
    """

    __slots__ = ("category", "specs", "mpn", "description", "alternates")

    def __init__(self, category, specs, mpn, description, alternates):
        self.category = category
        self.specs = specs
        self.mpn = mpn
        self.description = description
        self.alternates = alternates


def merged_result(identity: Identity, payloads: dict[str, dict | None]) -> EnrichmentResult:
    """Every stored payload, parsed and merged in registry priority order.

    Iterates `known_sources()` rather than the payload dict, so the merge order is the REGISTRY's
    and not whatever order the files happened to be listed in. That is what makes the result
    deterministic, and determinism is what makes the whole engine idempotent.

    A payload for a source this build does not know is skipped, not an error, and is left on disk
    untouched (see `payloads.parser_for`).
    """
    merged = EnrichmentResult()
    for source in known_sources():
        if source not in payloads:
            continue
        one = parse_one(source, payloads[source], identity.mpn)
        if not one.filled_fields():
            continue
        merged.merge_missing(one)
    return merged


def derive_block(
    identity: Identity,
    payloads: dict[str, dict | None],
    *,
    derived_at: str,
    scheme: str = DEFAULT_SCHEME,
    current_category: str = "",
) -> Derived:
    """The whole derived block, from identity + raw payloads. Pure; no clock, no network, no I/O.

    `derived_at` is a PARAMETER, not `datetime.now()`. A timestamp read inside would make two
    consecutive derives differ in exactly one field, and "derive twice, byte-identical" would be
    untestable without special-casing the field the test most wants to trust.

    `current_category` is honoured, not overwritten: a part a PERSON filed somewhere real keeps
    that filing, because a vendor taxonomy is a suggestion for an UNFILED part and never an
    override of a human decision (the guard inside `refile_category`, relied on here rather than
    re-implemented).
    """
    from stockroom.enrich.pipeline import refile_category
    from stockroom.ingest.component_naming import derive_value

    merged = merged_result(identity, payloads)

    # NORMALIZE HERE. This is the line that moved off the import path: the values below are the
    # opinionated, canonical form, and the raw answers each source actually gave are still in
    # `sourced/` where they can be re-read if this normalization is ever wrong.
    specs = normalize_specs({key: sv.value for key, sv in merged.specs.items()})

    description = merged.description.value if merged.description is not None else ""
    description = str(description or "").strip()

    # Category: the source's taxonomy for an unfiled part, the existing filing otherwise.
    category = (current_category or "").strip()
    view = _CategoryView(category or UNFILED, specs, identity.mpn, description, {})
    suggested = refile_category(view)
    if suggested:
        category = suggested
    if not category:
        category = (merged.category or "").strip() or UNFILED

    # The schematic/BOM Value reads the FILED category, so it is computed after filing: a
    # resistor filed "Other" would take the MPN branch and silently lose its parametric value.
    view.category = category
    value = derive_value(view)

    display_name = get_scheme(scheme)(
        NameInputs(
            mpn=identity.mpn,
            manufacturer=identity.manufacturer,
            category=category,
            description=description,
            specs=specs,
        )
    )

    return Derived(
        display_name=display_name,
        value=value,
        category=category,
        description=description,
        specs=specs,
        derived_at=derived_at,
        derived_by=DERIVED_BY,
    )


def load_payloads(sourced_root: Path, part_id: str) -> dict[str, dict | None]:
    """Every stored payload for a part, keyed by source. READ ONLY.

    Goes through `model.sourced.read_json` - which that module documents as "the deriver's entry
    point: it READS" - rather than opening the files here, so the path layout stays owned by one
    module. A source whose file is missing or unparseable is OMITTED rather than raising: a
    re-derive of a part with one damaged payload should produce the best block the remaining
    evidence supports, not refuse to rebuild the part at all.

    Driven off `list_sources` (what the part actually HAS) intersected with the parser registry
    (what this build can read), so a payload from a source a newer build wrote is skipped and left
    untouched rather than crashing an older peer.
    """
    # An id `sourced/` refuses (pre-v3, containing an underscore) is NOT the same fact as "this
    # part has no evidence yet", and conflating them was a real defect (cold-eyes finding 7,
    # 2026-07-27): `list_sources` raises ValueError for such an id, and swallowing it here made
    # `rederive()` silently BLANK the derived block of a record it could not actually check
    # evidence for - display_name, description and specs all wiped with no error raised.
    # `import_part` already guards its OWN call path against this (it inspects the id before
    # ever reaching here), but `rederive()` is a public entry point callers can and do use
    # directly (see tests/backend/derive/test_engine.py), so THIS function must refuse loudly
    # rather than let an invalid id look identical to "nothing pulled yet".
    if not is_valid_part_id(part_id):
        raise ValueError(
            f"cannot load evidence for {part_id!r}: not a valid v3 part id "
            f"(slug(mpn)+'-'+sha256(mpn)[:4]); sourced/ refuses it as a path"
        )
    out: dict[str, dict | None] = {}
    try:
        available = set(list_sources(sourced_root, part_id))
    except OSError:
        return out
    for source in known_sources():
        if source not in available:
            continue
        try:
            payload = read_json(sourced_root, part_id, source)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        out[source] = payload
    return out


def rederive(record, sourced_root: Path, *, derived_at: str, scheme: str = DEFAULT_SCHEME):
    """Replace a record's derived block from its stored payloads. Returns the record.

    REPLACES, never merges. `clear_derived()` first, so a field whose only source has been removed
    disappears instead of lingering - a block that were merged into would slowly become a set of
    values with no evidence behind them, which is precisely the state the sourced/derived split
    exists to make impossible.

    A part with NO stored payloads is a real case (every record in the owner's library today, until
    the importer runs) and is handled honestly: the block is recomputed from nothing, which leaves
    the derived fields empty rather than inventing them. It does NOT preserve the old block, and
    that is the point - a silent "keep what was there" would make a library look re-derived when
    nothing had been.
    """
    payloads = load_payloads(sourced_root, record.id)
    block = derive_block(
        Identity.of(record),
        payloads,
        derived_at=derived_at,
        scheme=scheme,
        current_category=getattr(record, "category", "") or "",
    )
    record.derived = block
    return record


# `replace` and `rename` are deliberately NOT in this list (cold-eyes finding 10, 2026-07-27): both
# are also plain `str`/`dict` method names (`text.replace(...)`), and the AST walk below sees only
# the attribute NAME, never the receiver's type. Convicting every `.replace()` call in the derive
# path - which normalizes strings for a living - would be exactly the false-positive machine the
# owner's rule warns against ("a package-vs-pad check reported 16 mismatches and ALL 16 were false
# positives"). `unlink`/`rmtree` stay: neither is a method any object in this path's actual
# vocabulary (str, dict, dataclass) exposes, so they carry no such collision.
FORBIDDEN_CALLS: frozenset[str] = frozenset({"unlink", "rmtree"})


def _scan_modules_for_writes(modules, writer) -> None:
    """The core of the losslessness check, taking its inputs as PARAMETERS.

    Split out of `assert_no_writer_imported` (cold-eyes finding 2, 2026-07-27) because the
    original test claiming to prove this check "can actually fail" built a synthetic AST from a
    bare string and asserted `ast.walk` finds a call in it - which tests the `ast` module, not
    this one, and stayed green when the real gate was disabled entirely (verified: an early
    `return` at the top of `assert_no_writer_imported` left the whole `tests/backend/derive`
    suite passing, including the test claiming to guard against exactly that).

    Taking `modules` and `writer` as arguments is what makes the gate itself testable: a test can
    now hand this a synthetic module object whose `__file__` points at a temp file containing a
    genuine `write_payload(...)` call, and watch THIS function convict it - proving the mechanism,
    not a restatement of it.
    """
    import ast

    for module in modules:
        for attr, value in vars(module).items():
            if value is writer:
                raise AssertionError(
                    f"{module.__name__}.{attr} IS the writer - the derive path must never be able "
                    f"to write under sourced/, which is append-only evidence."
                )

    for module in modules:
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name.startswith("write") or name in FORBIDDEN_CALLS:
                raise AssertionError(
                    f"{module.__name__} line {node.lineno} calls {name!r}. The derive path READS "
                    f"evidence and writes nothing: sourced/ is the only copy of what a vendor "
                    f"actually returned."
                )


def assert_no_writer_imported() -> None:
    """LOSSLESSNESS, as a check rather than a promise: the derive path CANNOT write evidence.

    `sourced/` is append-only and a re-derive must never touch it. A comment saying so is
    unenforceable and the failure would be invisible - a derive that rewrote a payload would still
    produce a perfectly plausible record. So the rule is measured two ways against the real code:

      1. no module in `stockroom.derive` holds a reference to `model.sourced.write_payload`;
      2. no module in `stockroom.derive` CALLS anything named `write_payload` / `write_*`, checked
         by walking the AST.

    The AST is what makes this honest. A `"write_payload" in source` test cannot tell a docstring
    that says "must never call write_payload" from a line that calls it, so it would either convict
    this very docstring or have to exempt this file - and an exemption for the file most likely to
    break the rule is not a check. The scanning logic itself lives in `_scan_modules_for_writes`,
    so `tests/backend/derive/test_payload_registry.py` can drive it against an injected module
    and prove the mechanism can fail, not just call this wrapper and trust it.
    """
    import stockroom.derive.engine as engine
    import stockroom.derive.naming as naming
    import stockroom.derive.payloads as payloads_mod
    from stockroom.model.sourced import write_payload

    _scan_modules_for_writes((engine, naming, payloads_mod), write_payload)
