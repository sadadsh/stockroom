"""The library-version pin: which library commit a project was last resolved against.

Batch 2 item 2, and the reason it exists is a failure git cannot report on its own. A Stockroom
project and the Stockroom library are two SEPARATE repositories. Two peers can therefore sit on the
byte-identical project commit while their libraries are at different commits, so the same
`${SR_LIB}/footprints/...` reference resolves to different geometry, the same symbol carries
different fields, and the BOM prices differently. Nothing in either repo's history says a word about
it.

The pin closes that hole the way lockfiles do everywhere else (`package-lock.json`, `Cargo.lock`,
`poetry.lock`): a small canonical JSON file that records the dependency's exact resolved version and
is committed ALONGSIDE the thing that depends on it. So the pin lives in the PROJECT's own repo, next
to the `.kicad_pro` / `.PrjPcb`, and travels with the project commit. Keeping it on the Stockroom
ProjectRecord instead would put it in the library repo, decoupled from the project commit it is
supposed to describe, and a peer who registers the project themselves would never receive it at all.

PRIOR ART considered, and what was REJECTED and why:

- **`git submodule`** is the mechanism git itself ships for "this repo depends on that repo at THIS
  commit", and it stores exactly the field this module stores. Rejected because a submodule also
  demands the dependency live INSIDE the dependent's working tree at a fixed relative path. The
  Stockroom library is one shared library that many projects consume from an arbitrary location per
  machine (that is what `SR_LIB` exists to express), and no project owns it. Adopting submodules
  would mean one nested clone of the whole library per project, and would break every existing
  registration by path. The gitlink IDEA is adopted; the storage mechanism is not.
- **`git subtree` / vendoring the library into each project.** Rejected for the same reason plus
  duplication: N copies of a growing binary library, and a part fix would have to be re-vendored
  into every project.
- **A real dependency manager over an artifact registry** (an npm/PyPI-shaped package of the
  library, resolved by version). Rejected as far more machinery than the problem: it needs a
  registry to host, a release cadence, and a publish step, to express something one git commit id
  already expresses exactly. Reconsider only if the library is ever consumed outside git.
- **Recording the pin on the Stockroom ProjectRecord** (the existing per-project JSON in the LIBRARY
  repo). Rejected above: it would not travel with the project commit, which is the entire property
  being bought.
- **Comparing library CONTENT hashes instead of a commit id.** Rejected because git already
  guarantees a commit id identifies exact content, and a content hash would answer "different" with
  no history, so it could never say ahead / behind / diverged, which is what makes the remedy
  actionable.

So what is NEW here is only the lockfile shape applied to a Stockroom library, plus the ahead /
behind / diverged / unknown classification and its remedies. The version comparison itself is
delegated to git (`merge-base --is-ancestor`, `rev-list --count`) rather than reimplemented.

Two deliberate non-goals:

- **It never checks the library out.** A library is shared by every project on the machine, so
  silently rolling it back to satisfy one project would break the others. The pin REPORTS, and every
  status names the remedy a person can take.
- **It is not a lock on content.** A commit is the finest identity git offers; if a peer has that
  commit, they have exactly those bytes.

This module is tool-agnostic on purpose: the pin is Stockroom's own sidecar, not a design file, so
one mechanism serves every EDA tool. How each tool resolves library PATHS portably (KiCad's `SR_LIB`
variable, Altium's relative `.DbLib` data source) is separate, and lives as data on the EDA registry.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from stockroom.vcs.repo import GitRepo

# The pin sits at the project root, beside the project file, so it is obvious in a diff and a peer
# reviewing a pull request sees the library move as an explicit line change.
PIN_FILENAME = "stockroom-library.json"

# Bumped only when the on-disk shape changes incompatibly. A build reading a HIGHER schema must
# refuse rather than guess, the same rule PartRecord's SCHEMA_VERSION exists for: peers share these
# files through git and both write them.
SCHEMA_VERSION = 1

UNPINNED = "unpinned"
MATCH = "match"
LIBRARY_AHEAD = "library_ahead"
LIBRARY_BEHIND = "library_behind"
DIVERGED = "diverged"
UNKNOWN_COMMIT = "unknown_commit"
DIFFERENT_LIBRARY = "different_library"
DIFFERENT_PROFILE = "different_profile"
LIBRARY_NOT_GIT = "library_not_git"

ALL_STATUSES = (
    UNPINNED,
    MATCH,
    LIBRARY_AHEAD,
    LIBRARY_BEHIND,
    DIVERGED,
    UNKNOWN_COMMIT,
    DIFFERENT_LIBRARY,
    DIFFERENT_PROFILE,
    LIBRARY_NOT_GIT,
)


@dataclass(frozen=True)
class StatusText:
    """What a status MEANS and what to do about it, as data.

    Severity is decided here rather than in the surface, so the backend and the UI can never
    disagree about whether a state is fine. `problem` means the machine cannot faithfully rebuild
    what the project expects; `notice` means it can, but the answer may differ from the last
    verified one.
    """

    detail: str
    remedy: str
    severity: str


STATUS_TEXT: dict[str, StatusText] = {
    UNPINNED: StatusText(
        detail=(
            "This project does not record which library version it was resolved against, so a peer "
            "on the same project commit can resolve different footprints without either of you "
            "being told."
        ),
        remedy="Pin the library to record the version this project currently resolves against.",
        severity="notice",
    ),
    MATCH: StatusText(
        detail="This machine's library is at exactly the commit this project is pinned to.",
        remedy="Nothing to do. Re-pin after the library changes in a way this project should adopt.",
        severity="ok",
    ),
    LIBRARY_AHEAD: StatusText(
        detail=(
            "The library has moved on since this project was pinned, so parts may resolve "
            "differently from the last version that was verified."
        ),
        remedy="Re-check the project against the current library, then update the pin.",
        severity="notice",
    ),
    LIBRARY_BEHIND: StatusText(
        detail=(
            "This machine's library is OLDER than the version this project expects, so parts the "
            "project references may be missing or may resolve to earlier geometry."
        ),
        remedy="Pull the library so this machine has the version the project was built against.",
        severity="problem",
    ),
    DIVERGED: StatusText(
        detail=(
            "This machine's library and the pinned version share history but have both moved on "
            "separately, so neither contains the other."
        ),
        remedy=(
            "Pull the library to reconcile the two histories, then re-check the project and update "
            "the pin."
        ),
        severity="problem",
    ),
    UNKNOWN_COMMIT: StatusText(
        detail=(
            "This machine's library does not contain the commit the project is pinned to, so the "
            "version the project expects has never reached it."
        ),
        remedy="Fetch the library from its remote, then re-check this project.",
        severity="problem",
    ),
    DIFFERENT_LIBRARY: StatusText(
        detail=(
            "The pin names a different library repository from the one this machine has active, so "
            "the two version histories are not comparable at all."
        ),
        remedy=(
            "Switch to the library the project is pinned to, or re-pin deliberately if this project "
            "has genuinely moved library."
        ),
        severity="problem",
    ),
    DIFFERENT_PROFILE: StatusText(
        detail=(
            "The pin was taken against a different library profile from the active one, and two "
            "profiles hold different parts even inside the same repository."
        ),
        remedy=(
            "Activate the profile the project is pinned to, or re-pin deliberately if this project "
            "has moved profile."
        ),
        severity="problem",
    ),
    LIBRARY_NOT_GIT: StatusText(
        detail=(
            "The active library is not under git, so it has no version this project could be "
            "compared against."
        ),
        remedy="Put the library under git so its version can be shared with a peer at all.",
        severity="problem",
    ),
}


@dataclass(frozen=True)
class LibraryPin:
    """One resolved library version, as committed into a project repo."""

    profile: str
    remote: str
    commit: str
    pinned_at: str
    schema: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "profile": self.profile,
            "remote": self.remote,
            "commit": self.commit,
            "pinned_at": self.pinned_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LibraryPin":
        return cls(
            profile=str(d.get("profile", "")),
            remote=str(d.get("remote", "")),
            commit=str(d.get("commit", "")),
            pinned_at=str(d.get("pinned_at", "")),
            schema=int(d.get("schema", SCHEMA_VERSION)),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def loads(cls, text: str) -> "LibraryPin":
        return cls.from_dict(json.loads(text))

    def is_future_schema(self) -> bool:
        return self.schema > SCHEMA_VERSION


def pin_path(project_root) -> Path:
    return Path(project_root) / PIN_FILENAME


def read_pin(project_root) -> LibraryPin | None:
    """The project's pin, or None when it has never been pinned.

    A malformed pin RAISES. Treating unreadable JSON as "unpinned" would quietly offer to overwrite
    a file someone hand-edited, which is the silent-fallback shape the project bans everywhere else.
    """
    path = pin_path(project_root)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return LibraryPin.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"{PIN_FILENAME} is not readable as a library pin: {exc}") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_remote(url: str) -> str:
    """A comparable form of a git remote URL.

    The SAME GitHub repository is legitimately written `https://host/o/r`, `https://host/o/r.git`,
    `git@host:o/r.git` and with any capitalisation, and a peer who cloned it the other way must not
    be told they are on a different library. Only the host and path are compared; the transport, the
    credentials and a trailing slash carry no identity.
    """
    text = (url or "").strip()
    if not text:
        return ""
    # A Windows drive letter (`C:\libs\stockroom`, `C:/libs/stockroom`) is a local PATH that looks
    # exactly like scp-style `host:path`. Parsing it as scp would turn the drive into a hostname and
    # let two different drives normalize onto each other. The owner runs Windows, so a local library
    # on a drive path is an ordinary case here, not an edge one.
    is_windows_path = len(text) > 2 and text[1] == ":" and text[0].isalpha() and text[2] in "\\/"
    # scp-style `git@host:owner/repo.git` -> `host/owner/repo`
    if not is_windows_path and "://" not in text and ":" in text and not text.startswith("/"):
        head, _, tail = text.partition(":")
        host = head.rpartition("@")[2]
        text = f"{host}/{tail}"
    else:
        _scheme, sep, rest = text.partition("://")
        if sep:
            # strip any `user:token@` credentials, which differ per machine and carry no identity
            text = rest.rpartition("@")[2] if "@" in rest.split("/", 1)[0] else rest
    text = text.rstrip("/")
    if text.endswith(".git"):
        text = text[: -len(".git")]
    return text.lower()


@dataclass(frozen=True)
class PinVerdict:
    """The comparison result, with everything a surface needs and nothing it must re-derive."""

    status: str
    detail: str
    remedy: str
    severity: str
    # How far apart the two versions are, in commits, when that question has an answer.
    ahead: int = 0
    behind: int = 0
    # The library as it is on THIS machine right now, for the "pinned X, you have Y" sentence.
    library_commit: str = ""
    library_remote: str = ""
    library_profile: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "detail": self.detail,
            "remedy": self.remedy,
            "severity": self.severity,
            "ahead": self.ahead,
            "behind": self.behind,
            "library_commit": self.library_commit,
            "library_short": self.library_commit[:7],
            "library_remote": self.library_remote,
            "library_profile": self.library_profile,
        }


def _verdict(status: str, **kw) -> PinVerdict:
    text = STATUS_TEXT[status]
    return PinVerdict(
        status=status, detail=text.detail, remedy=text.remedy, severity=text.severity, **kw
    )


def evaluate(pin: LibraryPin | None, library_repo: GitRepo, *, profile: str) -> PinVerdict:
    """Compare a project's pin against the library on THIS machine.

    The order of the checks is the point. Identity is settled before any ancestry question is asked,
    because `git merge-base` between two unrelated repositories is not a meaningful answer, and an
    absent commit is separated from a real divergence because the two have completely different
    remedies (fetch versus reconcile).
    """
    is_git = library_repo.is_git_repo()
    head = library_repo.head() if is_git else ""
    remote = library_repo.remote_url() if is_git else ""
    facts = {"library_commit": head, "library_remote": remote, "library_profile": profile}

    if pin is None:
        return _verdict(UNPINNED, **facts)
    if not is_git:
        return _verdict(LIBRARY_NOT_GIT, **facts)
    # A pin that names no remote was taken against a library that had none, so it can only be
    # identified by its commits; that is weaker, and it is exactly what the commit checks below do.
    if pin.remote and remote and normalize_remote(pin.remote) != normalize_remote(remote):
        return _verdict(DIFFERENT_LIBRARY, **facts)
    if pin.profile and profile and pin.profile != profile:
        return _verdict(DIFFERENT_PROFILE, **facts)
    if not library_repo.has_commit(pin.commit):
        return _verdict(UNKNOWN_COMMIT, **facts)
    if pin.commit == head:
        return _verdict(MATCH, **facts)
    pin_behind_head = library_repo.is_ancestor(pin.commit, head)
    head_behind_pin = library_repo.is_ancestor(head, pin.commit)
    if pin_behind_head:
        return _verdict(
            LIBRARY_AHEAD, ahead=library_repo.count_commits(pin.commit, head), **facts
        )
    if head_behind_pin:
        return _verdict(
            LIBRARY_BEHIND, behind=library_repo.count_commits(head, pin.commit), **facts
        )
    return _verdict(
        DIVERGED,
        ahead=library_repo.count_commits(pin.commit, head),
        behind=library_repo.count_commits(head, pin.commit),
        **facts,
    )
