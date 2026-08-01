"""Recover the DigiKey models id from the PERSON's own browser history. Opt-in, and nothing else.

WHY THIS MODULE EXISTS
``capture/digikey_models.py`` deep-links a part straight to
``https://www.digikey.com/en/models/<id>?tab=<provider>``, which removes a keyword search, a page
of navigation and a tab click that the person had already performed for that exact part. The id is
opaque, DigiKey publishes no lookup for it, and it was learned incidentally from
``UserCaptureResult.final_url`` - the page a Playwright-driven capture ended on.

Person-driven capture has since been DE-AUTOMATED. ``capture/handoff.py`` hands the validated URL
to the operating system's default browser and walks away, precisely so the session that reaches
DigiKey is the owner's real browser rather than a disguised robot. The cost of that correct
decision is that Stockroom no longer observes where the person navigated: it cannot learn a single
new id, and the shortcut is dead for every new part.

The owner approved recovering the id from their own local browser history. That approval is narrow
and this module is built to stay inside it.

WHAT IS READ, AND WHAT IS NOT
The SQL query is the filter, not a Python loop after the fact. Only rows whose URL already has
DigiKey's models prefix are selected, so a row about the person's bank, mail, health or employer is
never read into this process at all - not returned, not counted, not traced, not cached. There is
no code path here that can widen that predicate, and ``read_models_page_visits`` returns a bounded
list of ``ModelsPageVisit``, which structurally cannot carry a foreign URL or title.

The one justification for touching this file is resolving the owner's OWN parts. Anything that is
not that is not ours to look at.

THE LIVE DATABASE IS NEVER OPENED
Chromium holds ``History`` locked while the browser runs, so the file is copied to a private
temporary directory and the COPY is opened read-only; the copy is deleted before the function
returns, whether or not the read worked. Nothing here opens, writes to, or leaves a sidecar beside
the person's real database.

BINDING AN ID TO A PART, SAFELY
The models URL carries the opaque id and no part number, so the MPN comes from the page TITLE,
which DigiKey renders as ``<MPN> EDA | CAD 3D Model Download | Digikey``. History supplies no
manufacturer, and the store keys on manufacturer AND MPN, because two manufacturers ship the same
MPN string and a models page belongs to one of them. So an id is recorded only when the parsed MPN
identifies EXACTLY ONE part identity in the library; two parts sharing that MPN under different
manufacturers is a skip, and the trace says so. The comparison is ``identity.same_mpn`` - the same
one the provider identity gate uses, separator tolerance included, which matters here because a
title is as lossy a carrier as a slug.

IT MAY NEVER FAIL A CAPTURE
This is an optimisation over behaviour that already works. A missing browser, a locked file that
survives the copy, a corrupt page, a shifted schema, an unwritable store - every one of them
degrades to "learned nothing", which costs one keyword search and is exactly today's behaviour.

NO NETWORK. NO PROVIDER AUTOMATION. This reads one local file and writes ids to one local store.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from stockroom.capture.digikey_models import DigiKeyModelsIds, digikey_models_id
from stockroom.capture.identity import same_mpn
from stockroom.capture.trace import trace, trace_debug

# -- the opt-in ---------------------------------------------------------------------------------

#: Set to ``1``/``true``/``yes``/``on`` to allow this reader to run. DEFAULT OFF, and the only
#: thing that turns it on today.
MODELS_HISTORY_OPT_IN = "STOCKROOM_DIGIKEY_MODELS_FROM_HISTORY"

#: A per-machine flag, honoured the way ``access_policy`` honours its own: an explicit ``True`` on
#: the machine configuration, never a truthy value. ``MachineConfig`` does not declare this field
#: yet, so it is a forward seam - a settings toggle can be added without touching this module, and
#: until then the environment variable above is the enable.
MODELS_HISTORY_CONFIG_FLAG = "digikey_models_history_learning"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class HistoryLearningDecision:
    """Whether this installation may read local browser history, and WHICH signal settled it."""

    enabled: bool
    signal: str
    detail: str


def history_learning_decision(
    *,
    config: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> HistoryLearningDecision:
    """Fail closed. Absence of an opt-in is not an opt-in, and neither is an unreadable config."""

    environment = os.environ if environ is None else environ
    try:
        raw = str(environment.get(MODELS_HISTORY_OPT_IN, "") or "").strip().casefold()
    except Exception:  # noqa: BLE001 - an unreadable environment is not permission
        raw = ""
    if raw in _TRUE_VALUES:
        return HistoryLearningDecision(
            enabled=True,
            signal="environment-opt-in",
            detail=f"{MODELS_HISTORY_OPT_IN} is set",
        )
    if config is not None and getattr(config, MODELS_HISTORY_CONFIG_FLAG, None) is True:
        return HistoryLearningDecision(
            enabled=True,
            signal="machine-config-flag",
            detail=f"the per-machine {MODELS_HISTORY_CONFIG_FLAG} flag is enabled",
        )
    return HistoryLearningDecision(
        enabled=False,
        signal="not-enabled",
        detail=(
            "learning DigiKey models ids from local browser history is off; "
            f"set {MODELS_HISTORY_OPT_IN} to enable it"
        ),
    )


# -- finding the databases -----------------------------------------------------------------------

# Chromium-family browsers all keep ``<User Data>/<Profile>/History`` under %LOCALAPPDATA%. Listed
# explicitly rather than discovered by scanning LocalAppData, so a directory this module was never
# meant to look at is never even enumerated.
_BROWSER_USER_DATA = (
    ("vivaldi", ("Vivaldi", "User Data")),
    ("chrome", ("Google", "Chrome", "User Data")),
    ("edge", ("Microsoft", "Edge", "User Data")),
    ("brave", ("BraveSoftware", "Brave-Browser", "User Data")),
)
# Chromium's own non-browsing profiles. They hold no person's navigation and are skipped by name.
_NOT_A_PERSON_PROFILE = frozenset({"system profile", "guest profile"})
# A person has a handful of profiles per browser. A bound keeps a strange tree from turning this
# into a filesystem walk.
_MAX_DATABASES = 24


@dataclass(frozen=True, slots=True)
class HistoryDatabase:
    """One browser profile's history file. The browser NAME is for the trace; the path is not."""

    browser: str
    path: Path


def chromium_history_databases(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[HistoryDatabase, ...]:
    """Every installed Chromium-family ``History`` file. A missing browser is simply absent."""

    environment = os.environ if environ is None else environ
    try:
        local_app_data = str(environment.get("LOCALAPPDATA", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ()
    if not local_app_data:
        return ()
    root = Path(local_app_data)
    found: list[HistoryDatabase] = []
    for browser, segments in _BROWSER_USER_DATA:
        user_data = root.joinpath(*segments)
        try:
            profiles = sorted(entry for entry in user_data.iterdir() if entry.is_dir())
        except OSError:
            continue  # not installed, or not ours to read
        for profile in profiles:
            if profile.name.casefold() in _NOT_A_PERSON_PROFILE:
                continue
            history = profile / "History"
            try:
                if not history.exists():
                    continue
            except OSError:
                continue
            found.append(HistoryDatabase(browser=browser, path=history))
            if len(found) >= _MAX_DATABASES:
                return tuple(found)
    return tuple(found)


# -- reading only the models pages -----------------------------------------------------------------

# Anchored on DigiKey's own origins. This predicate is what keeps every other row out of the
# process; `digikey_models_id` then re-validates each surviving URL in full, so a traversal, a
# port, an embedded credential or a non-numeric id still fails closed.
_MODELS_URL_PREFIXES = (
    "https://www.digikey.com/en/models/",
    "https://digikey.com/en/models/",
)
_MODELS_QUERY = (
    "SELECT url, title, last_visit_time FROM urls "
    "WHERE url LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' "
    "ORDER BY last_visit_time DESC LIMIT ?"
)
# One person's models-page visits over the life of a profile. Far above any real count, and a hard
# ceiling on what a tampered or enormous database can pull into memory.
_MAX_VISIT_ROWS = 5_000


@dataclass(frozen=True, slots=True)
class ModelsPageVisit:
    """One visit to one DigiKey models page. Structurally incapable of carrying anything else."""

    models_id: str
    mpn: str
    last_visit: int


def read_models_page_visits(path: Path | str) -> tuple[ModelsPageVisit, ...]:
    """The DigiKey models pages in one history database, newest first. Never raises.

    The live file is copied first: Chromium holds it locked while the browser runs, and it is the
    person's data either way. The copy is opened read-only and deleted before returning.

    Only ``History`` itself is copied - no ``-wal``/``-journal`` sidecar. Chromium does not run
    this database in WAL mode, and taking the sidecars would mean opening the copy writably so
    SQLite could replay them. A read-only handle is the stronger guarantee and the worse case if
    that ever changes is a stale or unreadable copy, which learns nothing and costs one search.
    """

    scratch: str | None = None
    try:
        scratch = tempfile.mkdtemp(prefix="stockroom-history-")
        copy = Path(scratch) / "History"
        shutil.copyfile(str(path), copy)
        return _visits_in(copy)
    except Exception:  # noqa: BLE001 - absent, locked, corrupt, shifted: all learn nothing
        return ()
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _visits_in(copy: Path) -> tuple[ModelsPageVisit, ...]:
    # `as_uri` percent-encodes the path SQLite is about to percent-decode, so a temp directory
    # containing a space, a `%` or a `#` opens the file it names rather than a neighbour.
    connection = sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            _MODELS_QUERY,
            (
                _MODELS_URL_PREFIXES[0].replace("_", r"\_") + "%",
                _MODELS_URL_PREFIXES[1].replace("_", r"\_") + "%",
                _MAX_VISIT_ROWS,
            ),
        ).fetchall()
    finally:
        connection.close()
    visits: list[ModelsPageVisit] = []
    for url, title, last_visit in rows:
        models_id = digikey_models_id(url if isinstance(url, str) else "")
        if not models_id:
            continue  # a look-alike that satisfied the prefix but not the full shape
        visits.append(
            ModelsPageVisit(
                models_id=models_id,
                mpn=mpn_from_models_title(title),
                last_visit=last_visit if isinstance(last_visit, int) else 0,
            )
        )
    return tuple(visits)


# -- reading the MPN out of the page title -------------------------------------------------------

# DigiKey renders this page as ``<MPN> EDA | CAD 3D Model Download | Digikey``. The part number is
# the leading segment; everything after the first separator describes the page, not the part.
_TITLE_SEPARATOR = "|"
# Trailing words that describe the page rather than name a part. Deliberately a tiny closed set:
# stripping descriptive words is how a parser starts inventing part numbers, and a wrong parse that
# still matched a library part would bind the wrong id.
_TITLE_TAIL_WORDS = frozenset({"eda", "cad", "3d", "model", "models", "download", "downloads", "&"})
_MAX_TAIL_WORDS = 4
# No real MPN is this long. A title that is a sentence is not a part number.
_MAX_MPN_CHARS = 100


def mpn_from_models_title(title: object) -> str:
    """The MPN a DigiKey models page title names, or ``""``.

    Deliberately unforgiving in one direction only: a title this cannot read yields nothing and
    the visit is skipped. It cannot yield a WRONG part, because whatever it returns still has to
    identify exactly one library part before an id is bound to anything.
    """

    if not isinstance(title, str) or not title:
        return ""
    head = title.split(_TITLE_SEPARATOR)[0]
    head = unicodedata.normalize("NFKC", head).strip()
    for _ in range(_MAX_TAIL_WORDS):
        words = head.split()
        if len(words) < 2 or words[-1].casefold() not in _TITLE_TAIL_WORDS:
            break
        head = " ".join(words[:-1]).strip()
    if head.casefold() in _TITLE_TAIL_WORDS:
        return ""
    if not head or len(head) > _MAX_MPN_CHARS:
        return ""
    return head


# -- binding an id to exactly one library part -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistoryLearnOutcome:
    """What one pass learned, in counts. Nothing here can carry a history row."""

    enabled: bool
    signal: str
    databases: int = 0
    candidates: int = 0
    resolved: int = 0
    learned: int = 0
    skipped_no_mpn: int = 0
    skipped_unknown_mpn: int = 0
    skipped_ambiguous_mpn: int = 0


def _part_identities(parts: Iterable[object]) -> list[tuple[str, str]]:
    """(manufacturer, mpn) for every library part that has both. A broken record is skipped."""

    identities: list[tuple[str, str]] = []
    for part in parts or ():
        try:
            manufacturer = getattr(part, "manufacturer", "") or ""
            mpn = getattr(part, "mpn", "") or ""
        except Exception:  # noqa: BLE001 - an unreadable record never stops the others
            continue
        if not isinstance(manufacturer, str) or not isinstance(mpn, str):
            continue
        if manufacturer.strip() and mpn.strip():
            identities.append((manufacturer, mpn))
    return identities


def _sole_identity(
    identities: Sequence[tuple[str, str]],
    mpn: str,
) -> tuple[tuple[str, str] | None, int]:
    """The one part identity this MPN names, plus how many distinct identities it named.

    Distinct IDENTITY, not distinct record: a library holding the same manufacturer and MPN twice
    describes one part and is not ambiguous. Two manufacturers for one MPN is exactly the case the
    store's compound key exists for, and it fails closed here.
    """

    matches: dict[tuple[str, str], tuple[str, str]] = {}
    for manufacturer, candidate in identities:
        try:
            if not same_mpn(candidate, mpn):
                continue
        except Exception:  # noqa: BLE001 - a comparison that raises is not a match
            continue
        matches[(manufacturer.strip().casefold(), candidate.strip().casefold())] = (
            manufacturer,
            candidate,
        )
    if len(matches) == 1:
        return next(iter(matches.values())), 1
    return None, len(matches)


def learn_models_ids_from_history(
    parts: Iterable[object],
    *,
    store: DigiKeyModelsIds,
    config: object | None = None,
    environ: Mapping[str, str] | None = None,
) -> HistoryLearnOutcome:
    """Teach ``store`` every models id the local history unambiguously proves. Never raises."""

    decision = history_learning_decision(config=config, environ=environ)
    if not decision.enabled:
        trace_debug(
            "capture.models-history.skipped",
            signal=decision.signal,
            detail=decision.detail,
        )
        return HistoryLearnOutcome(enabled=False, signal=decision.signal)
    try:
        return _learn(parts, store=store, environ=environ)
    except Exception:  # noqa: BLE001 - an optimisation may never fail a capture
        trace_debug("capture.models-history.unreadable")
        return HistoryLearnOutcome(enabled=True, signal="unreadable")


def _learn(
    parts: Iterable[object],
    *,
    store: DigiKeyModelsIds,
    environ: Mapping[str, str] | None,
) -> HistoryLearnOutcome:
    identities = _part_identities(parts)
    databases = chromium_history_databases(environ=environ)

    candidates = 0
    skipped_no_mpn = 0
    # Newest wins: one entry per MPN, replaced only by a strictly later visit. Keyed on the title's
    # own spelling; the library identity it resolves to is decided once, below.
    newest: dict[str, ModelsPageVisit] = {}
    for database in databases:
        visits = read_models_page_visits(database.path)
        if not visits:
            trace_debug("capture.models-history.database", browser=database.browser, candidates=0)
            continue
        trace_debug(
            "capture.models-history.database",
            browser=database.browser,
            candidates=len(visits),
        )
        for visit in visits:
            candidates += 1
            if not visit.mpn:
                skipped_no_mpn += 1
                continue
            key = visit.mpn.strip().casefold()
            previous = newest.get(key)
            if previous is None or visit.last_visit > previous.last_visit:
                newest[key] = visit

    resolved = 0
    learned = 0
    skipped_unknown = 0
    skipped_ambiguous = 0
    for visit in newest.values():
        identity, match_count = _sole_identity(identities, visit.mpn)
        if identity is None:
            if match_count > 1:
                skipped_ambiguous += 1
                # Naming the MPN is safe and necessary here: it is a part in the OWNER'S OWN
                # library, so it reveals nothing about their browsing, and without it they cannot
                # tell which part needs its manufacturer disambiguated.
                trace(
                    "capture.models-history.ambiguous",
                    mpn=visit.mpn,
                    parts=match_count,
                )
            else:
                # NOT named. An MPN that matches nothing in the library is a part the person looked
                # at for their own reasons, and that is not Stockroom's business.
                skipped_unknown += 1
            continue
        resolved += 1
        manufacturer, mpn = identity
        try:
            kept = store.learn(
                manufacturer=manufacturer,
                mpn=mpn,
                # Rebuilt from the validated id, never pasted from history: the store re-validates
                # what it is handed, and this is the canonical shape it accepts.
                final_url=f"https://www.digikey.com/en/models/{visit.models_id}",
            )
        except Exception:  # noqa: BLE001 - an unwritable store learns nothing and breaks nothing
            kept = ""
        if kept:
            learned += 1

    outcome = HistoryLearnOutcome(
        enabled=True,
        signal="read",
        databases=len(databases),
        candidates=candidates,
        resolved=resolved,
        learned=learned,
        skipped_no_mpn=skipped_no_mpn,
        skipped_unknown_mpn=skipped_unknown,
        skipped_ambiguous_mpn=skipped_ambiguous,
    )
    trace(
        "capture.models-history",
        databases=outcome.databases,
        candidates=outcome.candidates,
        resolved=outcome.resolved,
        learned=outcome.learned,
        skipped_no_mpn=outcome.skipped_no_mpn,
        skipped_unknown_mpn=outcome.skipped_unknown_mpn,
        skipped_ambiguous_mpn=outcome.skipped_ambiguous_mpn,
    )
    return outcome


def learn_models_ids_for_library(ctx: object, *, store: DigiKeyModelsIds) -> HistoryLearnOutcome:
    """The capture-run entry point: the same pass, over the parts this library actually holds.

    Globs the parts directory rather than the derived index, for the reason every other capture
    seam does: the index is rebuilt in the background and a worklist that disagrees with the files
    on disk is a worklist that skips real work. Every step degrades to "learned nothing".
    """

    config = getattr(ctx, "config", None)
    try:
        if not history_learning_decision(config=config).enabled:
            # Not enabled means not even a directory listing, let alone a record load.
            return learn_models_ids_from_history((), store=store, config=config)
        profile = getattr(ctx, "profile")
        library = getattr(profile, "library")
        parts_dir = Path(getattr(library, "parts_dir"))
        ops = getattr(ctx, "ops")
        load_record = getattr(ops, "load_record")
        if not callable(load_record):
            raise TypeError("library record loader is unavailable")
        records = []
        for path in sorted(parts_dir.glob("*.json")):
            try:
                records.append(load_record(path.stem))
            except Exception:  # noqa: BLE001 - a corrupt record is skipped, never fatal
                continue
    except Exception:  # noqa: BLE001 - no readable library means nothing to bind an id to
        return HistoryLearnOutcome(enabled=True, signal="unreadable")
    return learn_models_ids_from_history(records, store=store, config=config)


__all__ = [
    "MODELS_HISTORY_CONFIG_FLAG",
    "MODELS_HISTORY_OPT_IN",
    "HistoryDatabase",
    "HistoryLearnOutcome",
    "HistoryLearningDecision",
    "ModelsPageVisit",
    "chromium_history_databases",
    "history_learning_decision",
    "learn_models_ids_for_library",
    "learn_models_ids_from_history",
    "mpn_from_models_title",
    "read_models_page_visits",
]
