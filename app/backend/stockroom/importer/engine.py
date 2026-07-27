"""Pull each source's RAW payload into `sourced/`, then re-derive. Nothing else.

This is the wave-2 importer of `docs/progress/rebuild-plan.json`, and its job is narrow on purpose:

    for each part that needs evidence:
        for each usable source, in priority order:
            fetch the RAW body        -> write it verbatim under sourced/<id>/<source>.json
        re-derive the derived block   -> by CALLING stockroom.derive.engine, never re-deriving here

It contains NO derivation logic. That is the point of the plan step *"Calls the existing derive
engine, does not write a second one"*: two derivations that drift is how the frontend ended up
reading fields the backend had renamed.

THE OUTCOME MODEL, and why DEFERRED is not a kind of failure. A part whose fetch was refused for
QUOTA reasons has nothing wrong with it - the answer simply has not been collected yet, and the
right response is to come back later. Recording that as FAILED would (a) put a permanent red mark
on a healthy part and (b) make "how much of the library is imported" unanswerable, because a
retryable gap and a real problem would be the same number. So:

    IMPORTED   evidence was written for at least one source, and the part re-derived.
    DEFERRED   a source refused for quota/rate reasons. Retryable, and the part is UNCHANGED.
    NO_DATA    every usable source answered, and none of them knows this part. Not retryable.
    SKIPPED    the part already has evidence from every usable source (this is what makes a
               re-run cheap and the whole pass resumable).
    FAILED     something genuinely went wrong writing or deriving. Rare and loud.

RESUMABILITY has no checkpoint file, deliberately. The worklist is derived from LIBRARY STATE - a
part needs a source if `sourced/<id>/<source>.json` is absent - so killing the process and starting
again resumes exactly where it stopped, with no state to go stale and no state to corrupt. A
checkpoint file is a second source of truth about what has been imported, and the tree is already
the first one.

IT NEVER WRITES A RECORD IN --dry-run. Anything that acts on the world gets a dry run before it
acts (owner's standing rule), and for a pass that mutates a git-backed library of the owner's real
158 parts that is not optional.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from stockroom.derive.engine import rederive
from stockroom.derive.naming import DEFAULT_SCHEME
from stockroom.importer.classify import reclassify
from stockroom.importer.sources import build_sources
from stockroom.model.part_id import is_valid_part_id
from stockroom.model.sourced import SOURCED_DIRNAME, source_rel_path, sourced_file, write_payload

# The `last_status` values the adapters set when a provider refuses for QUOTA reasons rather than
# because the part is unknown. Data, so a new provider's wording is one entry rather than a branch.
DEFERRABLE_STATUSES: frozenset[str] = frozenset({"rate_limited", "quota", "auth", "http_429"})


class Outcome(str, Enum):
    IMPORTED = "imported"
    DEFERRED = "deferred"
    NO_DATA = "no_data"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class PartResult:
    part_id: str
    mpn: str
    outcome: Outcome
    # Sources whose payload was written this pass.
    written: list[str] = field(default_factory=list)
    # Sources that refused for quota reasons, so a retry is worth making.
    deferred: list[str] = field(default_factory=list)
    # The class the importer proposed, when it proposed one (never an override of a human's).
    reclassified_to: str = ""
    detail: str = ""
    # Sources whose fetch RAISED rather than answering cleanly (a malformed response, a proxy
    # returning HTML with a 200, ...). Distinct from `deferred`: a deferred source told us it was
    # rate-limited, this one broke while trying to tell us anything at all.
    errors: list[str] = field(default_factory=list)
    # Sources whose payload was already on disk from a previous pass that wrote evidence and then
    # failed BEFORE the record was persisted - indexed and re-derived from this pass without a
    # new fetch. See `import_part`'s orphaned-evidence handling (cold-eyes finding 5).
    recovered: list[str] = field(default_factory=list)


@dataclass
class ImportReport:
    results: list[PartResult] = field(default_factory=list)
    # Sources present in the registry but unusable here, mapped to why. Reported ONCE rather than
    # logged per part: 158 identical "digikey: not configured" lines is noise that hides signal.
    unusable_sources: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

    def count(self, outcome: Outcome) -> int:
        return sum(1 for r in self.results if r.outcome is outcome)

    def summary(self) -> str:
        """One honest line. Names every bucket, including the empty ones, because a bucket that is
        omitted when zero reads as "not measured" rather than as "none"."""
        parts = ", ".join(f"{o.value}={self.count(o)}" for o in Outcome)
        prefix = "DRY RUN (nothing written): " if self.dry_run else ""
        return f"{prefix}{len(self.results)} parts: {parts}"


def needs_sources(sourced_root: Path, part_id: str, sources: Iterable[str]) -> list[str]:
    """Which of `sources` this part has NO evidence from yet.

    This IS the resumability mechanism: library state, read fresh, with no checkpoint to drift.
    """
    return [s for s in sources if not sourced_file(sourced_root, part_id, s).is_file()]


def import_part(
    record,
    *,
    library_root: Path,
    sources: list[tuple[str, object]],
    derived_at: str,
    scheme: str = DEFAULT_SCHEME,
    refetch: bool = False,
    dry_run: bool = False,
) -> PartResult:
    """Fetch, store and re-derive ONE part. Returns what happened and why."""
    result = PartResult(part_id=record.id, mpn=record.mpn, outcome=Outcome.SKIPPED)
    if not record.mpn:
        result.outcome = Outcome.NO_DATA
        result.detail = "no MPN, so there is nothing to look up"
        return result

    # An id the sourced layer refuses as a path component. MEASURED 2026-07-27 against the
    # owner's real library: 84 of 158 records still carry the PRE-V3 id scheme (`103at_2`,
    # underscores), while `sourced/` only accepts the decided `[a-z0-9-]` form - so evidence
    # cannot be filed for any of them until the ids are migrated.
    #
    # Checked HERE, before anything else, rather than only inside `needs_sources`: with
    # `--refetch` that call is skipped entirely (`todo = wanted` unconditionally), so an
    # unguarded id would reach real API calls and spend quota on a part that can never be
    # persisted (cold-eyes finding, 2026-07-27).
    #
    # Reported as ONE failed part with the reason, never raised: a bulk pass must not die on
    # part 2 of 158 and lose the 1 it had already done. "One part never fails the whole run."
    if not is_valid_part_id(record.id):
        result.outcome = Outcome.FAILED
        result.detail = (
            f"unsafe part id {record.id!r}. This record predates the v3 id scheme "
            f"(slug(mpn)+'-'+sha256(mpn)[:4]); `sourced/` will not accept it as a path. "
            f"The library needs an id migration first."
        )
        return result

    wanted = [name for name, _ in sources]
    # Computed UNCONDITIONALLY, even under --refetch, so orphaned evidence can be detected either
    # way: a source already ON DISK but not yet in `record.sources` is a real, separate case from
    # "needs a fetch", and the two must not be conflated (see below).
    missing_files = needs_sources(library_root, record.id, wanted)
    todo = wanted if refetch else missing_files
    # ORPHANED EVIDENCE (cold-eyes finding 5, 2026-07-27): a payload can be WRITTEN to disk and
    # the record's index/derive/save step can still fail after it - a raising naming scheme, a
    # killed process, a disk-full write to the record's own JSON. Resumability is deliberately
    # keyed on "does the file exist" (see `needs_sources`), so on the very next pass that source
    # reads as "already done" and is never retried - silently, forever, and counted in the
    # `skipped` bucket beside parts that are genuinely complete. A source with a file present but
    # NOT in `record.sources` is exactly that half-finished state, and it is recoverable WITHOUT a
    # new fetch: the evidence is already correct on disk.
    have_files = [s for s in wanted if s not in missing_files]
    orphaned = [s for s in have_files if s not in record.sources]
    if not todo and not orphaned:
        result.detail = "already has evidence from every usable source"
        return result

    by_name = dict(sources)
    fetched: dict[str, dict] = {}
    for name in todo:
        adapter = by_name[name]
        try:
            body = adapter.fetch_payload(record.mpn)
        except Exception as exc:  # noqa: BLE001 - one source's fetch must never fail the part
            # MEASURED (cold-eyes finding 4, 2026-07-27): a proxy or gateway answering with HTML on
            # a 200 makes `json.loads` raise `JSONDecodeError` - a `ValueError` - straight OUT of
            # `_default_requester`, past `EnrichError` (the only exception `fetch_payload`
            # anticipates) and past this function's own guard, aborting the entire pass with no
            # `ImportReport` produced at all. `Exception` here is deliberately broad: the contract
            # this module documents is "one part never fails the whole run", and a source library
            # can raise anything from a malformed response.
            result.errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        status = (getattr(adapter, "last_status", "") or "").strip().lower()
        if body is None:
            # DEFERRED vs NO_DATA is decided by the provider's own status, never guessed from the
            # absence of a body: "the API refused me" and "this part does not exist" look identical
            # from here, and conflating them is what would make a quota blip look like a bad part.
            if status in DEFERRABLE_STATUSES:
                result.deferred.append(name)
            continue
        fetched[name] = body

    if not fetched and not orphaned:
        # A source that RAISED is neither "deferred" (it never told us it was rate-limited) nor
        # "no data" (it never got far enough to say the part is unknown) - it is a genuine
        # failure, and reporting it as anything softer would hide it inside a healthy-looking
        # bucket. Checked first, so a mix of one error + one deferral still reads as FAILED - the
        # part cannot honestly be called merely "retryable" while something is broken.
        if result.errors:
            result.outcome = Outcome.FAILED
            result.detail = "; ".join(result.errors)
        elif result.deferred:
            result.outcome = Outcome.DEFERRED
            result.detail = f"{', '.join(result.deferred)} refused for quota reasons; retryable"
        else:
            result.outcome = Outcome.NO_DATA
            result.detail = "no usable source knows this MPN"
        return result

    # Orphaned entries already covered by a fetch this pass (a --refetch that re-pulled the same
    # source) do not need separate recovery; only recover what genuinely was not re-fetched.
    to_recover = [s for s in orphaned if s not in fetched]

    if dry_run:
        result.outcome = Outcome.IMPORTED
        result.written = sorted(fetched)
        result.recovered = sorted(to_recover)
        pieces = []
        if fetched:
            pieces.append("write " + ", ".join(
                f"{SOURCED_DIRNAME}/{record.id}/{n}.json" for n in sorted(fetched)
            ))
        if to_recover:
            pieces.append("recover already-written evidence for " + ", ".join(sorted(to_recover)))
        result.detail = "would " + "; ".join(pieces)
        return result

    try:
        for name, body in fetched.items():
            # VERBATIM, and this is the one line the whole sourced layer exists for. `indent=1`
            # only so a git diff of a re-pull is readable; the KEYS ARE NOT SORTED and no value is
            # touched, because re-serializing with sorted keys would already be a rewrite of
            # evidence. `refetch=True` is required to replace an existing payload, so an accidental
            # second pass cannot silently overwrite the only copy of what a vendor said.
            rel = write_payload(
                library_root,
                record.id,
                name,
                json.dumps(body, indent=1, ensure_ascii=False),
                refetch=True,
            )
            record.record_source(name, file=rel, fetched_at=derived_at)
            result.written.append(name)

        for name in to_recover:
            # The file is ALREADY correct on disk (see the orphaned-evidence comment above): index
            # it without touching the payload, so a stale evidence write is never re-timestamped or
            # re-serialized just because the record fell behind it.
            record.record_source(name, file=source_rel_path(record.id, name), fetched_at=derived_at)
            result.recovered.append(name)

        rederive(record, library_root, derived_at=derived_at, scheme=scheme)

        # Classification runs AFTER the derive, because it reads the derived category and
        # description - and it never overrides a class a human already chose (see classify.py).
        proposed = reclassify(record)
        if proposed is not None:
            record.part_class = proposed
            result.reclassified_to = proposed.value
    except Exception as exc:  # noqa: BLE001 - "one part never fails the whole run", see module doc
        # WAS `(OSError, ValueError, KeyError, TypeError)`, and `UnknownNamingScheme` - raised by
        # `derive.naming.get_scheme` for a typo'd --scheme - subclasses `Exception` directly, not
        # `ValueError`, so it escaped this tuple entirely. Measured: the payload had ALREADY been
        # written to sourced/ by the time it raised, so the part was left with orphaned evidence
        # and no derived block - exactly the state finding 5's fix below now recovers from, but
        # only a future pass should have to; this one should not have let it happen for a typo.
        result.outcome = Outcome.FAILED
        result.detail = f"{type(exc).__name__}: {exc}"
        return result

    result.outcome = Outcome.IMPORTED
    detail_bits = []
    if fetched:
        detail_bits.append("stored evidence from " + ", ".join(sorted(fetched)))
    if result.recovered:
        detail_bits.append("recovered orphaned evidence for " + ", ".join(sorted(result.recovered)))
    result.detail = "; ".join(detail_bits) + "; re-derived"
    return result


def _needs_a_fetch(record, library_root: Path, wanted: list[str], refetch: bool) -> bool:
    """Mirrors `import_part`'s own "is there anything to fetch" check, cheaply and read-only.

    Used ONLY to decide whether pacing is owed for this part - never to decide the actual import,
    which stays `import_part`'s call. Kept a small, explicitly-mirrored check rather than a shared
    helper both call, because the two callers want different failure behaviour: `import_part` must
    turn an invalid id into a reported `FAILED` result; this one only needs a boolean, and must
    never raise while a caller is deciding whether to spend quota.
    """
    if not record.mpn or not is_valid_part_id(record.id):
        return False
    if refetch:
        return bool(wanted)
    return bool(needs_sources(library_root, record.id, wanted))


def run_import(
    records: Iterable,
    *,
    library_root: Path,
    config,
    derived_at: str,
    scheme: str = DEFAULT_SCHEME,
    refetch: bool = False,
    dry_run: bool = False,
    pace: Callable[[str], None] | None = None,
    on_result: Callable[[PartResult], None] | None = None,
    save: Callable[[object], None] | None = None,
    sources: list[tuple[str, object]] | None = None,
) -> ImportReport:
    """Import a whole worklist. Stoppable at any point; re-running resumes from library state.

    `pace` is injected rather than constructed so the caller owns the quota policy (the existing
    `enrich.rescan.Pacer` is what the CLI passes) and so tests run at full speed without patching
    a clock. `save` is injected for the same reason: this module decides WHAT changed, and the
    caller decides how a record reaches disk - which keeps the atomic-commit rule where it lives.

    `sources` overrides the credentialed registry. It exists because building them from `config`
    is UNTESTABLE WITHOUT THE NETWORK: measured 2026-07-27, a test that passed a config carrying
    `mouser_api_key="k"` made a real outbound request to `api.mouser.com` with a bogus key. A unit
    test that reaches the internet is slow, flaky, and spends the owner's quota to prove something
    about pacing - so the seam is real, not a test convenience.
    """
    from stockroom.importer.sources import source_names

    report = ImportReport(dry_run=dry_run)
    if sources is None:
        sources = build_sources(config)
    # SORTED, not a set (cold-eyes finding 8): `usable` fed `pace()` in whatever order a set
    # happens to iterate, which is insertion-order-ish in CPython but not a documented guarantee -
    # so a resumed pass could pace providers in a different order than the original run for no
    # reason a person could predict or reproduce.
    usable = sorted(name for name, _ in sources)
    for name in source_names():
        if name not in usable:
            report.unusable_sources[name] = "not configured on this machine (no credentials)"

    if not sources:
        # LOUD, and early. A pass that fetched nothing because nothing was configured must not
        # report 158 clean "no_data" parts, which would read as "the vendors do not know your
        # library" rather than "you have not given me any keys".
        report.results = []
        return report

    for record in records:
        # Paced ONLY when this part will actually be fetched (cold-eyes finding 8): pacing every
        # record unconditionally meant a resumed pass over 158 parts with 150 already imported
        # still paid the full per-provider quota delay 158 times over, throttling for work it was
        # never going to do.
        if pace is not None and _needs_a_fetch(record, library_root, usable, refetch):
            for name in usable:
                pace(name)
        result = import_part(
            record,
            library_root=library_root,
            sources=sources,
            derived_at=derived_at,
            scheme=scheme,
            refetch=refetch,
            dry_run=dry_run,
        )
        if result.outcome is Outcome.IMPORTED and not dry_run and save is not None:
            save(record)
        report.results.append(result)
        if on_result is not None:
            on_result(result)
    return report
