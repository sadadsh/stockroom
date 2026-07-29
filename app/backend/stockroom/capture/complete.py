"""Automatic completion: give every part the files it still needs, from sources that need
no human.

This is the machine behind the owner's bar -- *"i want every single thing i put there thats
purchasable to be in the library fully complete"*, and *"if i handed u 10000 components it
should work fully endlessly, i only handed u almost 200"*. Those two sentences are what the
design is answering, so both are stated here rather than paraphrased.

**It is a source framework, not a feature.** `capture_needs` already says WHAT a part is
missing, per EDA tool, straight off the registry. This module says HOW a missing asset gets
filled without a person in the loop, and it does that by asking each registered `AssetSource`
what it can provide. Nothing here knows the word "kicad" or "altium": register an Altium
source and the same engine reports and fills Altium gaps through the same one action, which
is exactly what "kicad and altium at once" has to mean structurally.

**Scale is a property of the shape, not a tuning knob.** Three decisions do all the work:

* The worklist is a GENERATOR over the parts directory, and `complete_library` consumes it
  one part at a time. 10,000 records are never simultaneously in memory, and the first part
  starts before the last is even discovered.
* Every part is its own atomic unit -- loaded fresh, attached in its own transaction. So a
  run can be STOPPED between any two parts and nothing is left half-done.
* The worklist is DERIVED from the library on every run, never bookkept. A re-run therefore
  resumes by construction: parts already holding their files report `already-complete` and
  cost nothing. There is no progress file to go stale, and "run it again to catch the
  stragglers" is free rather than full price.

Nothing aborts the batch. A source that returns an error, a source that raises, a record
that will not load -- each is a ROW in the report. A 10,000-part run always finishes and
always says what happened to every part.

Qt-free and network-free: the sources own their I/O.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from stockroom.capture.requirements import Requirement, capture_needs

ProviderOutcomeStatus = Literal[
    "succeeded-retained",
    "activated",
    "unavailable",
    "requires-human",
    "blocked",
    "failed",
    "cancelled",
    "not-attempted",
]
_PROVIDER_OUTCOME_STATUSES = frozenset(
    {
        "succeeded-retained",
        "activated",
        "unavailable",
        "requires-human",
        "blocked",
        "failed",
        "cancelled",
        "not-attempted",
    }
)
_PROVIDER_KEY = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_PROVIDER_ROUTE_ID = re.compile(
    r"[a-z0-9][a-z0-9._-]{0,127}:[a-z0-9][a-z0-9._-]{0,127}\Z"
)
_URL = re.compile(r"https?://[^\s;]+", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[-_ ]?key|authorization)"
    r"\s*[:=]\s*[^\s;,]+"
)


def sanitize_provider_reason(value: object, *, limit: int = 400) -> str:
    """Return bounded, single-line provider detail with secrets and URL queries removed."""

    text = " ".join(str(value or "").split())

    def sanitize_url(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,)]}":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parsed = urlsplit(raw)
            host = parsed.hostname or ""
            if not host:
                return "[provider URL]" + trailing
            netloc = f"[{host}]" if ":" in host else host
            if parsed.port is not None:
                netloc = f"{netloc}:{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", "")) + trailing
        except (TypeError, ValueError):
            return "[provider URL]" + trailing

    text = _URL.sub(sanitize_url, text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    """One terminal result for one deterministic provider-surface/author route."""

    route_id: str
    provider_key: str
    author_key: str
    label: str
    status: ProviderOutcomeStatus
    attempted: bool
    retained: int = 0
    activated: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_key", self.provider_key),
            ("author_key", self.author_key),
        ):
            if type(value) is not str or _PROVIDER_KEY.fullmatch(value) is None:
                raise ValueError(f"{name} must be a canonical provider key")
        expected_route_id = f"{self.provider_key}:{self.author_key}"
        if self.route_id != expected_route_id:
            raise ValueError(f"route_id must be {expected_route_id!r}")
        if type(self.label) is not str or not self.label.strip():
            raise ValueError("provider outcome label must be non-empty")
        if self.status not in _PROVIDER_OUTCOME_STATUSES:
            raise ValueError("provider outcome status is not supported")
        if type(self.attempted) is not bool or type(self.activated) is not bool:
            raise TypeError("provider outcome flags must be booleans")
        if type(self.retained) is not int or self.retained < 0:
            raise ValueError("provider outcome retained count must be a non-negative integer")
        if self.activated != (self.status == "activated"):
            raise ValueError("provider outcome activation must match its terminal status")
        if self.status == "unavailable" and not self.attempted:
            raise ValueError(
                "unavailable requires a genuine route evaluation; use not-attempted instead"
            )
        if self.status == "not-attempted" and self.attempted:
            raise ValueError("not-attempted cannot claim the route was attempted")
        object.__setattr__(self, "label", self.label.strip())
        object.__setattr__(self, "reason", sanitize_provider_reason(self.reason))

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "provider_key": self.provider_key,
            "author_key": self.author_key,
            "label": self.label,
            "status": self.status,
            "attempted": self.attempted,
            "retained": self.retained,
            "activated": self.activated,
            "reason": self.reason,
        }


def provider_outcome_from_source(
    outcome: "SourceOutcome",
    *,
    provider_key: str,
    author_key: str,
    label: str,
    attempted: bool = True,
    status: ProviderOutcomeStatus | None = None,
    reason: str | None = None,
) -> ProviderOutcome:
    """Classify one source result without conflating retention and activation."""

    terminal = status
    if terminal is None:
        if outcome.blocked:
            terminal = "blocked"
        elif outcome.error:
            terminal = "failed"
        elif outcome.satisfied:
            terminal = "activated"
        elif outcome.retained:
            terminal = "succeeded-retained"
        elif outcome.skipped:
            terminal = "unavailable"
        else:
            terminal = "failed"
            if reason is None:
                reason = "provider route returned no terminal result"
    detail = reason if reason is not None else (outcome.error or outcome.skipped)
    return ProviderOutcome(
        route_id=f"{provider_key}:{author_key}",
        provider_key=provider_key,
        author_key=author_key,
        label=label,
        status=terminal,
        attempted=attempted,
        retained=outcome.retained,
        activated=terminal == "activated",
        reason=detail,
    )


def _planned_provider_route_ids(source: object) -> tuple[str, ...] | None:
    """Return a source's exhaustive route contract when it declares one."""

    planner = getattr(source, "provider_route_ids", None)
    if not callable(planner):
        return None
    planned = tuple(planner())
    if not planned:
        raise ValueError("provider route plan must contain at least one route")
    if any(
        type(route_id) is not str or _PROVIDER_ROUTE_ID.fullmatch(route_id) is None
        for route_id in planned
    ):
        raise ValueError("provider route plan contains a non-canonical route id")
    if len(set(planned)) != len(planned):
        raise ValueError("provider route plan repeats a route id")
    return planned


def _route_plan_errors(
    source_key: str,
    planned: tuple[str, ...] | None,
    reported: tuple[ProviderOutcome, ...],
) -> list[str]:
    """Describe missing or unplanned terminal rows for one source."""

    if planned is None:
        return []
    expected = set(planned)
    observed = {outcome.route_id for outcome in reported}
    errors: list[str] = []
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    if missing:
        errors.append(
            f"{source_key}: missing terminal provider outcome(s): {', '.join(missing)}"
        )
    if unexpected:
        errors.append(
            f"{source_key}: reported unplanned provider outcome(s): "
            f"{', '.join(unexpected)}"
        )
    return errors


@dataclass(frozen=True)
class SourceOutcome:
    """What one source did for one part.

    `satisfied` is what it actually DELIVERED, not what it attempted -- the caller re-reads
    the record to confirm, so a source that claims an asset it did not attach cannot fake a
    completion. `skipped` carries the honest "this source had nothing to offer for this part"
    (no LCSC id, not a decodable passive), which is a different fact from a failure and is
    reported as such instead of being flattened into an error.
    """

    satisfied: tuple[Requirement, ...] = ()
    # Files preserved as exact supplementary evidence but intentionally not projected into either
    # EDA library. This is separate from `satisfied`: a model-only source must never make a part
    # look complete merely because useful bytes were retained.
    retained: int = 0
    error: str = ""
    skipped: str = ""
    # The catalogue refused to talk to us, so this part was never really attempted. A
    # DIFFERENT fact from an error, and the engine reports it differently (`deferred`, not
    # `unchanged`): one says "try again later", the other says "nothing can help this part".
    # Set by `PacedSource` once its retries are spent.
    blocked: bool = False
    provider_outcomes: tuple[ProviderOutcome, ...] = ()

    def as_blocked(self) -> "SourceOutcome":
        return SourceOutcome(
            satisfied=self.satisfied,
            retained=self.retained,
            error=self.error,
            skipped=self.skipped,
            blocked=True,
            provider_outcomes=self.provider_outcomes,
        )


class AssetSource(Protocol):
    """Something that can fill a part's missing assets with no human in the loop.

    A source is registered once and the engine iterates it, so adding a way to get files is
    adding a source rather than editing this module.
    """

    key: str

    def provides(self) -> frozenset[Requirement]:
        """The requirements this source is capable of filling, in general."""

    def supply(self, record) -> SourceOutcome:
        """Attach what it can onto `record`, which it may mutate and persist."""


@dataclass
class CompletionItem:
    """One part's outcome.

    `status` distinguishes the four things the owner's question actually needs told apart:
    `already-complete` (nothing was needed), `completed` (everything needed arrived),
    `improved` (some arrived, some did not -- an honest partial, never rounded up), and
    `unchanged` / `error`. Rounding `improved` up to `completed` is precisely how a report
    starts claiming "all files" for a part that has no 3D model.
    """

    part_id: str
    mpn: str = ""
    display_name: str = ""
    category: str = ""
    status: str = ""  # already-complete | completed |
    #                                                    improved | deferred | unchanged | error
    needed: list[str] = field(default_factory=list)
    satisfied: list[str] = field(default_factory=list)
    retained: int = 0
    remaining: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # which sources actually delivered
    # Honest non-error explanations from sources that declined this exact part. Kept separate
    # from `error`: "no exact model exists here" is useful evidence, but it is not a provider
    # failure and must not be presented as one.
    notes: list[str] = field(default_factory=list)
    error: str = ""
    # Internal batch-control signal. A provider-wide gate may coexist with a useful partial
    # fallback, so status can remain `improved` while the circuit breaker still stops repeated
    # challenge/auth attempts. Deliberately omitted from the API shape: `status`, `remaining`, and
    # `error` already describe the user-facing result.
    provider_blocked: bool = field(default=False, repr=False)
    # Exhaustive collection is independent from projection completeness. A part may retain its
    # already-complete active pair while one provider route is blocked or errors.
    provider_outcomes: list[ProviderOutcome] = field(default_factory=list)
    collection_complete: bool | None = None

    def to_dict(self) -> dict:
        return {
            "part_id": self.part_id,
            "mpn": self.mpn,
            "display_name": self.display_name,
            "category": self.category,
            "status": self.status,
            "needed": list(self.needed),
            "satisfied": list(self.satisfied),
            "retained": self.retained,
            "remaining": list(self.remaining),
            "sources": list(self.sources),
            "notes": list(self.notes),
            "error": self.error,
            "provider_outcomes": [outcome.to_dict() for outcome in self.provider_outcomes],
            "collection_complete": self.collection_complete,
        }


@dataclass
class CompletionReport:
    items: list[CompletionItem] = field(default_factory=list)
    stopped: bool = False
    # Why it stopped, when it was not the user asking. Empty for a run that finished or that
    # the user stopped. A stop with no reason is indistinguishable from a crash.
    stop_reason: str = ""

    def of(self, *statuses: str) -> list[CompletionItem]:
        return [i for i in self.items if i.status in statuses]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items:
            out[i.status] = out.get(i.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        exhaustive_items = [
            item for item in self.items if item.collection_complete is not None
        ]
        return {
            "items": [i.to_dict() for i in self.items],
            "counts": self.counts(),
            "retained": sum(item.retained for item in self.items),
            "collection_complete": (
                all(item.collection_complete for item in exhaustive_items)
                if exhaustive_items
                else None
            ),
            "stopped": self.stopped,
            "stop_reason": self.stop_reason,
        }


def sourceable_needs(record, sources: Iterable[AssetSource]) -> list[Requirement]:
    """What this part is missing AND some registered source could actually supply.

    The filter matters: a gap nothing can fill is not work. Listing an Altium gap as
    outstanding work while no Altium source is registered produces a run that reports
    "0 completed" forever with nothing anyone can do about it -- the "CAD Incomplete
    forever" failure wearing a progress bar. Register the source and the same gap becomes
    work on the very next run, with no change here.
    """
    can: set[Requirement] = set()
    for source in sources:
        can |= set(source.provides())
    return [need for need in capture_needs(record) if need in can]


def complete_part(
    part_id: str,
    *,
    load_record,
    sources,
    collect_variants: bool = False,
    exhaustive: bool = False,
) -> CompletionItem:
    """Fill one part's gaps, cheapest source first, and report honestly what landed.

    `load_record` is a CALLABLE, never a pre-loaded record: a long run outlives the handles it
    starts with (a 28-minute import once failed 37 of 166 parts on a sqlite handle the
    background sync had closed underneath it), so the record is re-read here, per part.

    Every failure mode below is a ROW, never a raise: this is called in a loop over the whole
    library, and one bad part may not cost the other 9,999.
    """
    item = CompletionItem(part_id=part_id)
    try:
        record = load_record(part_id)
    except Exception as exc:  # noqa: BLE001 - a missing/corrupt record is a row, not an abort
        item.status = "error"
        item.error = str(exc)
        return item

    item.mpn = getattr(record, "mpn", "") or ""
    item.display_name = getattr(record, "display_name", "") or ""
    item.category = getattr(record, "category", "") or ""

    # Report every real CAD gap, not only the subset today's sources claim they can fill.
    # Otherwise a source can satisfy the sourceable subset and make the item read "completed"
    # while an unsupported Altium/model requirement remains on the record.
    needs = list(capture_needs(record))
    item.needed = [n.value for n in needs]
    if not needs and not collect_variants and not exhaustive:
        item.status = "already-complete"
        return item

    errors: list[str] = []
    outstanding = set(needs)
    collect_only = not needs and collect_variants and not exhaustive
    blocked = False
    seen_routes: set[str] = set()
    for source in sources:
        if not exhaustive and not outstanding and not collect_only:
            break
        # Nothing this source provides is still wanted -- do not pay for it. At 10k parts an
        # unnecessary network fetch per part is the difference between hours and days.
        if (
            not exhaustive
            and not collect_only
            and not (outstanding & set(source.provides()))
        ):
            continue
        planned_routes: tuple[str, ...] | None = None
        if exhaustive:
            try:
                planned_routes = _planned_provider_route_ids(source)
            except Exception as exc:  # noqa: BLE001 - invalid plans fail the row closed
                errors.append(f"{source.key}: invalid provider route plan: {exc}")
        try:
            outcome = source.supply(record)
        except Exception as exc:  # noqa: BLE001 - a broken source degrades, never aborts
            errors.append(f"{source.key}: {exc}")
            provider_key = getattr(source, "provider_key", "") or source.key
            author_key = getattr(source, "author_key", "") or provider_key
            label = getattr(source, "report_label", "") or source.key
            outcome = SourceOutcome(error=str(exc))
            provider_outcome = provider_outcome_from_source(
                outcome,
                provider_key=provider_key,
                author_key=author_key,
                label=label,
            )
            errors.extend(
                _route_plan_errors(
                    source.key,
                    planned_routes,
                    (provider_outcome,),
                )
            )
            if not exhaustive or provider_outcome.route_id not in seen_routes:
                item.provider_outcomes.append(provider_outcome)
                seen_routes.add(provider_outcome.route_id)
            continue
        reported_outcomes = outcome.provider_outcomes
        if not reported_outcomes:
            provider_key = getattr(source, "provider_key", "") or source.key
            author_key = getattr(source, "author_key", "") or provider_key
            label = getattr(source, "report_label", "") or source.key
            reported_outcomes = (
                provider_outcome_from_source(
                    outcome,
                    provider_key=provider_key,
                    author_key=author_key,
                    label=label,
                ),
            )
        if exhaustive:
            errors.extend(
                _route_plan_errors(
                    source.key,
                    planned_routes,
                    reported_outcomes,
                )
            )
        for provider_outcome in reported_outcomes:
            if exhaustive and provider_outcome.route_id in seen_routes:
                errors.append(
                    f"{source.key}: duplicate terminal provider outcome "
                    f"{provider_outcome.route_id}"
                )
                continue
            item.provider_outcomes.append(provider_outcome)
            seen_routes.add(provider_outcome.route_id)
        if outcome.error:
            errors.append(f"{source.key}: {outcome.error}")
        if outcome.skipped:
            # A source's stable engine key is not always its provider identity. Guided browser
            # sources deliberately share `key="guided"` while each instance drives a different
            # provider, so prefer their public report label when naming a decline.
            source_label = getattr(source, "report_label", "") or source.key
            item.notes.append(f"{source_label}: {outcome.skipped}")
        item.retained += outcome.retained
        if (
            (collect_only or exhaustive)
            and (outcome.retained or outcome.satisfied)
            and source.key not in item.sources
        ):
            item.sources.append(source.key)
        if outcome.blocked:
            blocked = True
        # Re-read the record's OWN state rather than trusting the claim. A source that
        # reports success it did not achieve would otherwise mark a part complete with no
        # files behind it, which is the "success reported by the code that started the work"
        # failure this project has paid for more than once.
        try:
            record = load_record(part_id)
            still = set(capture_needs(record))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"reload after {source.key}: {exc}")
            continue
        if collect_only:
            continue
        landed = outstanding - still
        if landed and source.key not in item.sources:
            item.sources.append(source.key)
        outstanding = still & set(needs)

    item.satisfied = [n.value for n in needs if n not in outstanding]
    item.remaining = [n.value for n in needs if n in outstanding]
    item.error = "; ".join(errors)
    if exhaustive:
        item.provider_blocked = blocked and bool(outstanding)
        settled_statuses = {"activated", "succeeded-retained", "unavailable"}
        item.collection_complete = (
            not errors
            and bool(item.provider_outcomes)
            and all(
                outcome.status in settled_statuses
                and (outcome.status != "unavailable" or outcome.attempted)
                for outcome in item.provider_outcomes
            )
        )
        if not needs:
            item.status = "already-complete"
        elif not item.remaining:
            item.status = "completed"
        elif item.satisfied:
            item.status = "improved"
        elif blocked:
            item.status = "deferred"
        else:
            item.status = "unchanged"
        return item
    if collect_only:
        item.provider_blocked = blocked
        if item.retained:
            item.status = "completed"
        elif errors:
            item.status = "deferred" if blocked else "error"
        else:
            item.status = "already-complete"
        return item
    # A later fallback may fully satisfy the part. In that case the earlier gate is irrelevant to
    # the batch outcome and must not trip the breaker.
    item.provider_blocked = blocked and bool(outstanding)
    if not item.remaining:
        item.status = "completed"
    elif item.satisfied:
        item.status = "improved"
    elif blocked:
        # Never attempted, so never "unchanged". Rounding this into `unchanged` would tell the
        # owner "nothing can be done for this part" about a part that simply needs the run
        # repeated -- the exact opposite of the truth.
        item.status = "deferred"
    else:
        item.status = "unchanged"
    return item


def complete_library(
    part_ids: Iterable[str],
    *,
    load_record,
    sources,
    on_progress: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    total: int | None = None,
    breaker=None,
    collect_variants: bool = False,
    exhaustive: bool = False,
) -> CompletionReport:
    """Complete many parts, streaming.

    `part_ids` is consumed lazily and deliberately: pass `iter_incomplete(...)` and the run
    starts on the first part before the last has been discovered, with one record in memory
    at a time. `total` is optional precisely because a generator has no length -- a run over
    an unknown-length stream still reports progress, just without a denominator.

    `should_stop` is checked BEFORE each part, never inside one. Each part is atomic, so a
    stop can only ever land on a clean boundary.

    `breaker` is a `CircuitBreaker`. When the catalogue starts refusing every request, the run
    STOPS with the reason rather than spending the next 9,900 parts producing false failures.
    Resuming is just running it again -- the worklist is derived, never bookkept.
    """
    report = CompletionReport()
    for done, part_id in enumerate(part_ids):
        if should_stop is not None and should_stop():
            report.stopped = True
            break
        item = complete_part(
            part_id,
            load_record=load_record,
            sources=sources,
            collect_variants=collect_variants,
            exhaustive=exhaustive,
        )
        report.items.append(item)
        if breaker is not None:
            if item.provider_blocked:
                breaker.record_blocked(item.error)
            elif item.status in ("completed", "improved", "already-complete") or item.retained:
                breaker.record_ok()
            else:
                breaker.record_failure()
        if on_progress is not None:
            on_progress(
                {
                    "stage": "completing",
                    "done": done,
                    "total": total,
                    "pct": ((done + 1) / total) if total else None,
                    "part_id": item.part_id,
                    "mpn": item.mpn,
                    "display_name": item.display_name,
                    "status": item.status,
                    "satisfied": list(item.satisfied),
                    "retained": item.retained,
                    "remaining": list(item.remaining),
                    "provider_outcomes": [
                        outcome.to_dict() for outcome in item.provider_outcomes
                    ],
                    "collection_complete": item.collection_complete,
                    "message": (
                        f"{item.mpn or item.part_id}"
                        + (f" ({done + 1} of {total})" if total else "")
                    ),
                }
            )
        if breaker is not None and breaker.tripped:
            report.stopped = True
            report.stop_reason = (
                "the catalogue is refusing requests, so the run stopped rather than reporting "
                f"the rest as failures. Run it again later to continue. Last error: "
                f"{breaker.reason}"
            )
            break
    return report


def iter_incomplete(parts_dir, *, load_record, sources) -> Iterator[str]:
    """The ids of parts some registered source could still help, yielded lazily.

    Globs the parts directory rather than reading the derived SQLite index, for the same
    reason the Altium emitter does: the index is rebuilt in the background and a worklist
    that disagrees with the files on disk is a worklist that skips real work. Sorted so a
    run is reproducible and a stopped-then-resumed run walks the library in the same order.

    A record that will not load is SKIPPED, not raised: one corrupt JSON in a 10,000-part
    library must not make the worklist unbuildable.
    """
    for path in sorted(Path(parts_dir).glob("*.json")):
        part_id = path.stem
        try:
            record = load_record(part_id)
        except Exception:  # noqa: BLE001 - a bad record is skipped, the library still works
            continue
        if sourceable_needs(record, sources):
            yield part_id
