#!/usr/bin/env python3
"""Render the rebuild plan to a single self-contained HTML page, and update its evidence.

The owner asked to "always see everything on this list and ur exact progress with bars for each
one", reachable "by my phone too so tailscale". So: the plan is DATA (docs/progress/rebuild-plan.json),
this renders it to docs/progress/index.html, and a static server + `tailscale serve` publishes it at
https://shdesktop.taild54105.ts.net/progress on the tailnet.

The page deliberately has NO aggregate product-readiness percentage. Engineering checklist steps
are unequal: a schema field, an off-main experiment, and a trusted dual-EDA asset cannot honestly
carry the same product weight. Owner outcomes are independent evidence gates; the old raw step
counter remains visible only as labelled engineering history.

PRIOR ART evaluated before writing this (CLAUDE.md: "say what you evaluated and REJECTED, and why"):
- GitHub task lists in an issue. GitHub renders a NATIVE progress bar for `- [ ]` lists, needs zero
  code, and is reachable from a phone. REJECTED: it gives ONE bar per issue, and the owner asked for
  a bar per item; the repo is also PUBLIC, and this plan carries their verbatim requirements.
- The existing vault tracker `Brain/Agent/Hardware Backlog.md` + the `/backlog` command. Real prior
  art in this exact project. ADOPTED ITS CONVENTION (`[x]` done / `[~]` doing / `[ ]` queued and an
  `[n/m]` counter per group) rather than inventing a second vocabulary. NOT used as the store,
  because it cannot carry per-step evidence and is not reachable from a phone.
- `rich` / `tqdm` for bars. REJECTED: both render to a TERMINAL. The ask was explicitly a page on a
  phone, and neither is a dependency here today.
- Taskwarrior / todo.txt / backlog.md CLI. REJECTED: they own their own state store outside the
  repo, which breaks the device-parity rule the rest of this project is built on, and none emits a
  hostable page.
- A dashboard framework (Streamlit/Dash). REJECTED: a server process and a dependency tree to keep a
  read-only page alive. A static file behind `tailscale serve` has no runtime to break.
What is genuinely hand-rolled here is only the JSON-to-HTML rendering, which is the part no existing
tool does in the shape asked for.

    python scripts/progress.py render                   # write docs/progress/index.html
    python scripts/progress.py tick <item> <n> -e "..." # tick step n, evidence REQUIRED
    python scripts/progress.py untick <item> <n>
    python scripts/progress.py state <item> blocked
    python scripts/progress.py check                    # validate; non-zero on a problem
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "progress" / "rebuild-plan.json"
HTML_OUT = ROOT / "docs" / "progress" / "index.html"

STATES = ("todo", "doing", "blocked", "done")
STEP_STATES = ("todo", "doing", "blocked", "done", "done_off_main", "superseded", "invalidated")
OUTCOME_STATES = ("met", "partial", "not_met", "blocked", "deferred")
ACTIVE_WORK_STATES = ("active", "blocked", "verification", "pending", "completed")
ACTIVE_WORK_MAX_AGE = timedelta(days=7)
PUBLIC_URL = "https://shdesktop.taild54105.ts.net/progress"


def load() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def save(plan: dict) -> None:
    plan["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def active_work_errors(plan: dict, *, now: datetime | None = None) -> list[str]:
    """Validate the manually maintained current-work snapshot.

    This is deliberately separate from outcome gates and engineering-history counters. It says
    what is moving now without assigning product weight or pretending a static page is telemetry.
    """

    bad: list[str] = []
    board = plan.get("active_work")
    if not isinstance(board, dict):
        return ["active_work must be an object"]

    for field in ("last_updated", "objective", "refresh_policy"):
        if not isinstance(board.get(field), str) or not board[field].strip():
            bad.append(f"active_work.{field} must be a non-empty string")

    policy = board.get("refresh_policy", "")
    if isinstance(policy, str):
        normalized_policy = policy.casefold()
        if "manual" not in normalized_policy or "not real-time" not in normalized_policy:
            bad.append(
                "active_work.refresh_policy must say it is manually refreshed "
                "and not real-time telemetry"
            )

    stamp_text = board.get("last_updated")
    if isinstance(stamp_text, str) and stamp_text.strip():
        try:
            if not stamp_text.endswith("Z"):
                raise ValueError
            stamp = datetime.fromisoformat(stamp_text[:-1] + "+00:00")
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                raise ValueError
        except ValueError:
            bad.append("active_work.last_updated must be an ISO-8601 UTC timestamp ending in Z")
        else:
            current = now or _utc_now()
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)
            current = current.astimezone(timezone.utc)
            age = current - stamp.astimezone(timezone.utc)
            if age > ACTIVE_WORK_MAX_AGE:
                bad.append(
                    "active_work.last_updated is stale "
                    f"(older than {ACTIVE_WORK_MAX_AGE.days} days)"
                )
            elif age < -timedelta(minutes=5):
                bad.append("active_work.last_updated is in the future")

    workstreams = board.get("workstreams")
    if not isinstance(workstreams, list) or not 3 <= len(workstreams) <= 6:
        bad.append("active_work.workstreams must contain 3 to 6 workstreams")
        workstreams = []

    seen: set[str] = set()
    for index, stream in enumerate(workstreams):
        label = f"active_work.workstreams[{index}]"
        if not isinstance(stream, dict):
            bad.append(f"{label} must be an object")
            continue
        stream_id = stream.get("id")
        if not isinstance(stream_id, str) or not stream_id.strip():
            bad.append(f"{label}.id must be a non-empty string")
        elif stream_id in seen:
            bad.append(f"duplicate active-work id {stream_id!r}")
        else:
            seen.add(stream_id)
        status = stream.get("status")
        if status not in ACTIVE_WORK_STATES:
            bad.append(f"{stream_id or label}: unknown active-work status {status!r}")
        for field in ("name", "owner", "evidence", "next_action"):
            if not isinstance(stream.get(field), str) or not stream[field].strip():
                bad.append(f"{label}.{field} must be a non-empty string")
        blocker = stream.get("blocker", "")
        if not isinstance(blocker, str):
            bad.append(f"{label}.blocker must be a string")
    return bad


def projects(plan: dict) -> list[dict]:
    """Every project on the board.

    Owner, 2026-07-27: *"it should hold everything your working on big projects and subprojects"*.
    The file used to be ONE project's plan, so a second piece of work had nowhere to live and
    simply went unrecorded -- which is the same invisibility complaint the activity feed fixed from
    the other end.

    BACK-COMPATIBLE by construction: a file with top-level `waves` and no `projects` is wrapped
    into a single project on read, so nothing has to be migrated and an older file still renders.
    """
    if plan.get("projects"):
        return plan["projects"]
    return [{
        "id": "main",
        "name": plan.get("title", "Project"),
        "why": plan.get("note", ""),
        "waves": plan.get("waves", []),
    }]


def waves(plan: dict):
    """Every wave across every project, so existing per-wave logic keeps working unchanged."""
    for proj in projects(plan):
        yield from proj.get("waves", [])


def items(plan: dict):
    for wave in waves(plan):
        for item in wave["items"]:
            yield wave, item


def find(plan: dict, item_id: str):
    for wave, item in items(plan):
        if item["id"] == item_id:
            return wave, item
    known = ", ".join(i["id"] for _, i in items(plan))
    raise SystemExit(f"no item with id {item_id!r}. Known: {known}")


def step_status(step: dict) -> str:
    """Return the explicit lifecycle state, with the old done boolean as a read-only fallback."""
    status = step.get("status")
    if status:
        return status
    return "done" if step.get("done") else "todo"


def item_progress(item: dict) -> tuple[int, int]:
    steps = item["steps"]
    # Only work delivered on the current product line counts. An invalidated claim, a superseded
    # approach, or a commit that exists only off-main is useful history, not shipped progress.
    return sum(1 for s in steps if step_status(s) == "done"), len(steps)


def wave_progress(wave: dict) -> tuple[int, int]:
    done = total = 0
    for item in wave["items"]:
        d, t = item_progress(item)
        done, total = done + d, total + t
    return done, total


def project_progress(proj: dict) -> tuple[int, int]:
    done = total = 0
    for wave in proj.get("waves", []):
        d, t = wave_progress(wave)
        done += d
        total += t
    return done, total


def overall(plan: dict) -> tuple[int, int]:
    done = total = 0
    for wave in waves(plan):
        d, t = wave_progress(wave)
        done, total = done + d, total + t
    return done, total


def derive_state(item: dict) -> str:
    """DERIVED from the steps, never stored, so it can never disagree with them.

    Same principle the part schema uses for trust (spec D2): store facts, compute the judgement.
    'blocked' is the one thing a human must assert, so that survives as an override.
    """
    if item.get("state") == "blocked":
        return "blocked"
    statuses = [step_status(step) for step in item["steps"]]
    if "blocked" in statuses:
        return "blocked"
    done, total = item_progress(item)
    if total and done == total:
        return "done"
    return "doing" if any(status != "todo" for status in statuses) else "todo"


def pct(done: int, total: int) -> int:
    return round(100 * done / total) if total else 0


# ---------------------------------------------------------------------------------------- html

# ---------------------------------------------------------------------------- the activity feed
#
# Owner, 2026-07-27: *"make the page show everything youre doing moving forward"*, after a session
# that landed six commits of real work and moved this page by one step -- so from the page it read
# as idle. The plan tracks the DESTINATION; it had no way to show the WORK. Fixing a defect,
# hardening a gate, or building a tool is invisible to a step counter, and most of a real session
# is exactly that.
#
# Derived from `git log`, deliberately, so it is AUTOMATIC and cannot drift: a commit is a real,
# timestamped, verifiable unit of work that already exists. Nothing here is hand-maintained, so
# there is no bookkeeping step to forget -- which is the only way "everything, moving forward" can
# be true. `scripts/hooks/post-commit` re-renders on every commit; `scripts/install-hooks.sh`
# wires it.
#
# REJECTED: a hand-written changelog in the JSON (drifts the moment anyone forgets, and the whole
# complaint was about invisible work); parsing the vault ledger (not in this repo, so a fresh
# clone could not render its own page); a CI feed (needs a network round trip for a static file).

_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # (label, substrings that identify it). First match wins, so the order is the priority.
    ("fix", ("fix", "stop ", "repair", "defect", "instead of", "no longer", "follow the reference")),
    ("tool", ("gate", "script", "harness", "shot", "tooling", "waitable", "detach")),
    ("build", ()),
)

# The LEADING VERB wins over anything later in the sentence. Without this, "Record the cold-eyes
# review findings and their FIXES" read as a fix, and "Record the index schema work and REPAIR an
# evidence string" read as a fix -- both are notes. A verb at the start states what the commit IS;
# a word in the middle only says what it is about.
_LEADING_VERBS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("revert", ("revert",)),
    ("record", ("record", "log", "document", "note")),
)


def _commit_kind(subject: str, code_files: int, data_files: int) -> str:
    """What KIND of work a commit was, so the feed can show that most of a session is not steps.

    A heuristic over the subject line, and labelled as one: it decides a LABEL on a feed, never a
    number anyone relies on. Getting it wrong mis-tints one row and misleads nobody about progress,
    which is why a rough rule is acceptable here and would not be inside `overall()`.

    `data` is decided by PATHS, not by words: a commit touching only the library or the built
    bundle is imported records or a build artifact, not engineering, and calling it a build made
    the biggest numbers on the page belong to the least work.
    """
    if data_files and not code_files:
        return "data"
    first = subject.strip().split(" ", 1)[0].lower().rstrip(":")
    for label, verbs in _LEADING_VERBS:
        if first in verbs:
            return label
    low = subject.lower()
    for label, needles in _KIND_RULES:
        if any(n in low for n in needles):
            return label
    return "build"


# Paths whose churn is not engineering effort: the part records and their raw evidence are IMPORTED
# DATA, and `frontend-dist` is a build artifact committed because the backend serves it. Counting
# either as work put "+210270 / 474 files" next to a records import and "+511" next to a real
# feature, which reads as the exact opposite of the truth.
# How many changes stay open before the rest fold away.
FEED_OPEN = 8

_DATA_PREFIXES = ("libraries/", "app/frontend-dist/", "docs/progress/")


def _is_data_path(path: str) -> bool:
    return path.startswith(_DATA_PREFIXES)


def activity(limit: int = 40) -> list[dict]:
    """Recent commits, newest first: when, what, how much, and what kind of work it was.

    Returns [] on ANY git failure rather than raising. This is a feed on a status page; a repo
    without git history, or a shallow clone, must still render the plan.
    """
    import subprocess

    sep = "\x1f"
    fmt = sep.join(["%H", "%h", "%cI", "%s"])
    try:
        out = subprocess.run(
            ["git", "log", f"-{limit}", f"--format={fmt}", "--numstat"],
            cwd=ROOT, capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except Exception:  # noqa: BLE001 - a feed must never take the page down
        return []
    rows: list[dict] = []
    current: dict | None = None

    def close(row: dict | None) -> None:
        if row is None:
            return
        row["kind"] = _commit_kind(row["subject"], row["files"], row["data_files"])
        rows.append(row)

    for line in out.splitlines():
        if sep in line:
            close(current)
            full, short, when, subject = line.split(sep, 3)
            current = {
                "sha": short, "full": full, "when": when, "subject": subject,
                "kind": "build", "files": 0, "ins": 0, "dels": 0, "data_files": 0,
            }
        elif current and line.strip():
            # `--numstat`: "<added>\t<deleted>\t<path>", with "-" for a binary file. Per-PATH, so
            # the churn shown can EXCLUDE data. `--shortstat` gave only a total, which is why the
            # first version put "+210270" beside a records import and made the biggest number on
            # the page belong to the least engineering.
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            if _is_data_path(path):
                current["data_files"] += 1
                continue
            current["files"] += 1
            current["ins"] += int(added) if added.isdigit() else 0
            current["dels"] += int(deleted) if deleted.isdigit() else 0
    close(current)
    return rows


def _render_active_work(board: dict, e) -> list[str]:
    status_labels = {
        "active": "Active",
        "blocked": "Blocked",
        "verification": "Verification",
        "pending": "Pending",
        "completed": "Completed",
    }
    rows = [
        '<section class="activework" aria-labelledby="active-work-title">',
        '<div class="awhead"><div>',
        '<p class="aweyebrow">Manual checkpoint snapshot</p>',
        '<h2 id="active-work-title">Codex Active Work</h2>',
        "</div>",
        f'<time datetime="{e(board["last_updated"])}">Updated '
        f'{e(board["last_updated"].replace("T", " ").replace("Z", " UTC"))}</time></div>',
        '<div class="awobjective"><span>Current objective</span>'
        f'<p>{e(board["objective"])}</p></div>',
        f'<p class="awpolicy">{e(board["refresh_policy"])}</p>',
        '<div class="awgrid">',
    ]
    for stream in board["workstreams"]:
        status = stream["status"]
        blocker = stream.get("blocker", "").strip()
        rows += [
            f'<article class="workstream ws-{e(status)}">',
            '<div class="wstop">',
            f'<h3>{e(stream["name"])}</h3>',
            f'<span class="tag t-{e(status)}">{e(status_labels[status])}</span>',
            "</div>",
            f'<p class="awowner"><span>Owner</span>{e(stream["owner"])}</p>',
            "<dl>",
            f'<div><dt>Current evidence</dt><dd>{e(stream["evidence"])}</dd></div>',
        ]
        if blocker:
            rows.append(f"<div><dt>Blocker</dt><dd>{e(blocker)}</dd></div>")
        rows += [
            f'<div><dt>Next action</dt><dd>{e(stream["next_action"])}</dd></div>',
            "</dl>",
            "</article>",
        ]
    rows += ["</div>", "</section>"]
    return rows


def render_html(plan: dict) -> str:
    e = html.escape
    d, t = overall(plan)

    def bar(done: int, total: int, state: str, big: bool = False) -> str:
        p = pct(done, total)
        cls = "bar big" if big else "bar"
        return (
            f'<div class="{cls}" role="progressbar" aria-valuenow="{p}" aria-valuemin="0" '
            f'aria-valuemax="100" aria-label="{p} percent"><span class="fill s-{state}" '
            f'style="width:{p}%"></span></div>'
            f'<span class="pct">{p}%</span><span class="frac">{done}/{total}</span>'
        )

    p: list[str] = [
        "<title>Stockroom Rebuild Progress</title>",
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        # The page is a STATIC file regenerated as work lands, so a refresh is the only way it can
        # stay live. There is no push channel on a static host to subscribe to instead.
        '<meta http-equiv="refresh" content="60">',
        '<meta name="color-scheme" content="light dark">',
        STYLE,
        '<div class="wrap">',
        '<header>',
        f"<h1>{e(plan['title'])}</h1>",
        f'<p class="sub">Updated {e(plan.get("updated", "not yet rendered"))}'
        f'<span class="live">auto refresh 60s</span></p>',
        '<p class="truth">Product readiness has no aggregate percentage. '
        'Each owner outcome must pass independently.</p>',
        "</header>",
    ]

    scope = (plan.get("product_scope") or "").strip()
    if scope:
        p += [
            '<section class="scope">',
            '<h2>Current Product Scope</h2>',
            f'<p>{e(scope)}</p>',
            "</section>",
        ]

    active_work = plan.get("active_work")
    if isinstance(active_work, dict):
        p += _render_active_work(active_work, e)

    outcome_labels = {
        "met": "Met",
        "partial": "Partial",
        "not_met": "Not Met",
        "blocked": "Blocked",
        "deferred": "Deferred",
    }
    outcomes = plan.get("outcome_gates", [])
    if outcomes:
        p += [
            '<section class="outcomes">',
            '<div class="outcomehead"><h2>Owner Outcome Gates</h2>'
            '<span>Independent gates; never averaged</span></div>',
            '<div class="outcomegrid">',
        ]
        for gate in outcomes:
            status = gate["status"]
            evidence = gate.get("evidence", [])
            blockers = gate.get("blockers", [])
            p += [
                f'<article class="outcome o-{e(status)}">',
                '<div class="otop">',
                f'<h3>{e(gate["name"])}</h3>',
                f'<span class="tag t-{e(status)}">{e(outcome_labels[status])}</span>',
                "</div>",
                f'<p class="measure">{e(gate["measure"])}</p>',
                f'<p class="why">{e(gate["acceptance"])}</p>',
            ]
            if evidence:
                p.append('<details><summary>Current evidence</summary><ul>')
                p += [f"<li>{e(row)}</li>" for row in evidence]
                p.append("</ul></details>")
            if blockers:
                p.append('<details open><summary>What remains</summary><ul>')
                p += [f"<li>{e(row)}</li>" for row in blockers]
                p.append("</ul></details>")
            p.append("</article>")
        p += ["</div>", "</section>"]

    # WHAT IS BEING WORKED ON RIGHT NOW (owner, 2026-07-27: "also add what youre currently working
    # on" / "in the html"). Placed above everything else because it answers the question a person
    # opens this page to ask, and a percentage cannot: 52% does not say whether anything is moving.
    # Absent rather than an empty box when nothing is set - a blank "Now:" reads as stalled.
    now = (plan.get("now") or "").strip()
    now_at = (plan.get("now_updated") or "").strip()
    # `now` is the live checkpoint; `active_work` is the broader manually refreshed board.
    # They are complementary. Hiding the live line whenever the board exists made the `now`
    # command report success while the served page continued showing only a stale objective.
    if now:
        p += [
            '<section class="now">',
            '<div class="nowhead"><span class="dot"></span><h2>Working on now</h2>'
            + (f'<span class="nowat">{e(now_at)}</span>' if now_at else "")
            + "</div>",
            f'<p class="nowtext">{e(now)}</p>',
            "</section>",
        ]

    # EVERYTHING BEING DONE, not just what moves a step (owner: "make the page show everything
    # youre doing moving forward"). Sits directly under Working-on-now and ABOVE the waves,
    # because the question "is anything happening" is answered by this and cannot be answered by a
    # step counter: most of a real session is defects, tooling and verification, none of which the
    # plan has a box for.
    feed = activity()
    if feed:
        kinds = {}
        for row in feed:
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
        tally = " / ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
        p += [
            '<section class="feed">',
            '<div class="feedhead"><h2>Everything being done</h2>'
            f'<span class="feedtally">{e(tally)}</span></div>',
            '<p class="why">Every change that landed, newest first, straight from the repository. '
            'A step counter only moves when a plan item completes; most of the work is fixing '
            'defects, hardening gates and building tools, and this is where that shows.</p>',
            '<ol class="acts">',
        ]
        def row_html(row: dict) -> str:
            when = row["when"][:16].replace("T", " ")
            if row["kind"] == "data":
                # For a records commit the meaningful size is how many RECORDS moved, not code
                # churn -- which is zero by definition here.
                n = row["data_files"]
                churn = f'{n} record{"" if n == 1 else "s"}' if n else ""
            elif row["files"]:
                churn = (
                    f'{row["files"]} file{"" if row["files"] == 1 else "s"} '
                    f'+{row["ins"]}/-{row["dels"]}'
                )
            else:
                churn = ""
            return (
                f'<li class="act k-{row["kind"]}">'
                f'<span class="akind">{e(row["kind"])}</span>'
                f'<span class="asub">{e(row["subject"])}</span>'
                f'<span class="ameta"><code>{e(row["sha"])}</code>'
                + (f'<span class="achurn">{e(churn)}</span>' if churn else "")
                + f'<time>{e(when)}</time></span></li>'
            )

        # The most recent OPEN, the rest one click away. The whole feed inline pushed the plan --
        # the thing this page is named for -- below forty rows, so answering "is anything moving"
        # cost you the answer to "how far along is it".
        head, tail = feed[:FEED_OPEN], feed[FEED_OPEN:]
        p += [row_html(r) for r in head]
        p.append("</ol>")
        if tail:
            p.append(
                f'<details class="more"><summary>{len(tail)} earlier '
                f'{"change" if len(tail) == 1 else "changes"}</summary><ol class="acts">'
            )
            p += [row_html(r) for r in tail]
            p.append("</ol></details>")
        p.append("</section>")

    p.append('<details class="reqs"><summary>The owner\'s five requirements, verbatim</summary><ol>')
    for r in plan["owner_requirements"]:
        p.append(f"<li>{e(r)}</li>")
    p.append("</ol></details>")

    p += [
        '<section class="engineering">',
        '<div><h2>Engineering Checklist History</h2>'
        '<p>Raw, unweighted implementation steps. This is activity bookkeeping, '
        'not product readiness.</p></div>',
        f'<div class="row">{bar(d, t, "done" if d == t and t else "doing")}</div>',
        "</section>",
    ]

    for proj in projects(plan):
        multi = len(projects(plan)) > 1
        if multi:
            pd, pt = project_progress(proj)
            pstate = "done" if pt and pd == pt else ("doing" if pd else "todo")
            p += [
                '<section class="proj">',
                f'<div class="phead"><h2>{e(proj["name"])}</h2>'
                f'<div class="row">{bar(pd, pt, pstate)}</div></div>',
            ]
            if proj.get("why"):
                p.append(f'<p class="why">{e(proj["why"])}</p>')
        for wave in proj.get("waves", []):
            _render_wave(p, wave, e, bar)
        if multi:
            p.append("</section>")

    p += [
        f'<footer>Generated from <code>{e(PLAN.relative_to(ROOT).as_posix())}</code> by '
        f'<code>scripts/progress.py</code>. A box is only ticked with evidence.</footer>',
        "</div>",
    ]
    return "\n".join(p) + "\n"


def _render_wave(p: list, wave: dict, e, bar) -> None:
    """One wave and everything under it. Extracted so the project loop above reads as a loop
    rather than as four levels of nesting."""
    if True:
        wd, wt = wave_progress(wave)
        wstate = "done" if wt and wd == wt else ("doing" if wd else "todo")
        p += [
            '<section class="wave">',
            f'<div class="whead"><h2>{e(wave["name"])}</h2>'
            f'<div class="row">{bar(wd, wt, wstate)}</div></div>',
            f'<p class="why">{e(wave["why"])}</p>',
        ]
        for item in wave["items"]:
            i_d, i_t = item_progress(item)
            st = derive_state(item)
            label = {"done": "Done", "doing": "In Progress",
                     "blocked": "Blocked", "todo": "Not Started"}[st]
            # Collapsed by default, EXPANDED only while a thing is actually moving. The first
            # version rendered every step of every item and came to 11,626px on a 844px phone:
            # about 14 screens, most of it greyed-out "Not Started" text. The owner asked to SEE
            # the bars, so the bars must fit on a screen and the detail must be one tap away.
            openattr = " open" if st in ("doing", "blocked") else ""
            p += [
                f'<details class="item s-{st}"{openattr}>',
                f'<summary><div class="ihead"><h3>{e(item["name"])}</h3>'
                f'<span class="tag t-{st}">{label}</span></div>'
                f'<div class="row">{bar(i_d, i_t, st)}</div></summary>',
                f'<p class="why">{e(item["why"])}</p>',
                '<ul class="steps">',
            ]
            for s in item["steps"]:
                status = step_status(s)
                step_labels = {
                    "todo": "Queued",
                    "doing": "In Progress",
                    "blocked": "Blocked",
                    "done": "Delivered",
                    "done_off_main": "Off Main",
                    "superseded": "Superseded",
                    "invalidated": "Invalidated",
                }
                boxes = {
                    "todo": "&nbsp;",
                    "doing": "~",
                    "blocked": "!",
                    "done": "&#10003;",
                    "done_off_main": "&#8599;",
                    "superseded": "&#8635;",
                    "invalidated": "&#215;",
                }
                ev = (f'<details class="evwrap"><summary>evidence</summary>'
                      f'<div class="ev">{e(s["evidence"])}</div></details>'
                      if s.get("evidence") else "")
                p.append(f'<li class="step st-{e(status)}">'
                         f'<span class="box">{boxes[status]}</span>'
                         f'<div class="stext"><div class="t">{e(s["t"])}'
                         f'<span class="stepstate">{e(step_labels[status])}</span></div>'
                         f'{ev}</div></li>')
            p += ["</ul>", "</details>"]
        p.append("</section>")


STYLE = """<style>
.truth{margin:8px 0 0;padding:9px 11px;border-left:3px solid var(--accent);
  background:var(--card);font-size:13px;color:var(--ink)}
.scope{margin:14px 0;padding:12px 14px;border:1px solid var(--line);background:var(--card);
  border-radius:var(--r-card)}
.scope h2{margin-bottom:5px}.scope p{margin:0;font-size:13px;color:var(--ink)}
.activework{margin:18px 0 26px;padding:16px;border:1px solid var(--accent);
  border-radius:var(--r-card);background:var(--card)}
.awhead{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
  padding-bottom:12px;border-bottom:1px solid var(--line)}
.awhead h2{font-size:18px;line-height:1.25;letter-spacing:-.01em;text-transform:none;
  color:var(--ink);white-space:normal}
.awhead time{font:11.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
  white-space:nowrap}
.aweyebrow{margin:0 0 3px;color:var(--accent);font-size:10.5px;font-weight:700;
  letter-spacing:.09em;text-transform:uppercase}
.awobjective{margin:12px 0 0}.awobjective span,.awowner span{display:block;color:var(--dim);
  font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.awobjective p{margin:3px 0 0;font-size:15px;line-height:1.45}
.awpolicy{margin:8px 0 0;color:var(--dim);font-size:11.5px}
.awgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:14px}
.workstream{padding:12px 13px;border:1px solid var(--line);border-left:3px solid var(--todo);
  border-radius:var(--r-card);background:var(--bg)}
.workstream.ws-active{border-left-color:var(--doing)}
.workstream.ws-blocked{border-left-color:var(--blocked)}
.workstream.ws-verification{border-left-color:var(--accent)}
.workstream.ws-completed{border-left-color:var(--done)}
.wstop{display:flex;align-items:flex-start;gap:8px}.wstop h3{flex:1;font-size:14px;line-height:1.35}
.awowner{margin:7px 0 0;color:var(--dim);font-size:11.5px}
.awowner span{display:inline;margin-right:5px}
.workstream dl{margin:10px 0 0}.workstream dl div{margin-top:8px}
.workstream dt{color:var(--dim);font-size:10px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase}
.workstream dd{margin:2px 0 0;font-size:12px;line-height:1.45}
.tag.t-active{color:var(--doing);border-color:var(--doing)}
.tag.t-verification{color:var(--accent);border-color:var(--accent)}
.tag.t-pending{color:var(--dim)}.tag.t-completed{color:var(--done);border-color:var(--done)}
.outcomes{margin:18px 0 24px}
.outcomehead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  border-bottom:1px solid var(--line);padding-bottom:8px}
.outcomehead span{font-size:11.5px;color:var(--dim)}
.outcomegrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}
.outcome{padding:13px 14px;background:var(--card);border:1px solid var(--line);
  border-left:3px solid var(--todo);border-radius:var(--r-card)}
.outcome.o-met{border-left-color:var(--done)}.outcome.o-partial{border-left-color:var(--doing)}
.outcome.o-not_met,.outcome.o-blocked{border-left-color:var(--blocked)}
.outcome.o-deferred{border-left-color:var(--dim)}
.otop{display:flex;gap:8px;align-items:flex-start}.otop h3{font-size:14px;line-height:1.3;flex:1}
.measure{margin:8px 0 0;font:600 13px ui-monospace,SFMono-Regular,Menlo,monospace}
.outcome details{margin-top:9px;color:var(--dim);font-size:11.5px}
.outcome details summary{color:var(--accent)}.outcome ul{margin:5px 0 0;padding-left:18px}
.outcome li{margin:3px 0}
.tag.t-met{color:var(--done);border-color:var(--done)}
.tag.t-partial{color:var(--doing);border-color:var(--doing)}
.tag.t-not_met,.tag.t-blocked{color:var(--blocked);border-color:var(--blocked)}
.tag.t-deferred{color:var(--dim)}
.engineering{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,1fr);
  gap:18px;align-items:center;margin:18px 0 4px;padding:12px 14px;border:1px dashed var(--line)}
.engineering h2{margin:0}.engineering p{margin:4px 0 0;color:var(--dim);font-size:11.5px}
.now{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--doing);
  border-radius:var(--r-card);padding:10px 12px;margin:14px 0}
.nowhead{display:flex;align-items:center;gap:8px}
.nowhead h2{font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:var(--dim);margin:0}
.nowhead .nowat{margin-left:auto;font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
.now .dot{width:7px;height:7px;border-radius:50%;background:var(--doing);flex:none;
  box-shadow:0 0 0 3px color-mix(in srgb,var(--doing) 25%,transparent)}
.nowtext{margin:6px 0 0;font-size:14px;line-height:1.45;color:var(--ink)}
:root{
  --bg:#0d0f12; --card:#15181e; --line:#242932; --ink:#e9ebee; --dim:#98a1ad;
  --done:#3fb950; --doing:#d29922; --blocked:#f85149; --todo:#3a414b; --accent:#58a6ff;
  --r-card:3px; --r-ctl:2px;
}
@media (prefers-color-scheme:light){:root{
  --bg:#f5f6f8; --card:#fff; --line:#e2e5ea; --ink:#11141a; --dim:#5b6472;
  --done:#1a7f37; --doing:#9a6700; --blocked:#cf222e; --todo:#b9c0c9; --accent:#0969da;}}
:root[data-theme=dark]{
  --bg:#0d0f12; --card:#15181e; --line:#242932; --ink:#e9ebee; --dim:#98a1ad;
  --done:#3fb950; --doing:#d29922; --blocked:#f85149; --todo:#3a414b; --accent:#58a6ff;}
:root[data-theme=light]{
  --bg:#f5f6f8; --card:#fff; --line:#e2e5ea; --ink:#11141a; --dim:#5b6472;
  --done:#1a7f37; --doing:#9a6700; --blocked:#cf222e; --todo:#b9c0c9; --accent:#0969da;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);-webkit-text-size-adjust:100%;
  font:15px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:880px;margin:0 auto;padding:28px 16px 64px}
header{position:sticky;top:0;z-index:5;background:var(--bg);padding:10px 0 14px;
  border-bottom:1px solid var(--line);margin-bottom:8px}
h1{font-size:21px;letter-spacing:-.02em;margin:0 0 4px;line-height:1.25}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);margin:0;
  white-space:nowrap}
h3{font-size:16px;margin:0;letter-spacing:-.01em}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--accent)}
.sub{color:var(--dim);font-size:12px;margin:0 0 10px}
.live{margin-left:8px;padding:1px 7px;border:1px solid var(--line);border-radius:9px;font-size:10.5px}
.row{display:flex;align-items:center;gap:9px;min-width:0}
.bar{flex:1;height:8px;min-width:60px;background:var(--todo);border-radius:var(--r-ctl);overflow:hidden}
.bar.big{height:12px}
.fill{display:block;height:100%;border-radius:var(--r-ctl);transition:width .45s ease}
.fill.s-done{background:var(--done)}.fill.s-doing{background:var(--doing)}
.fill.s-blocked{background:var(--blocked)}.fill.s-todo{background:var(--todo)}
.pct{font:600 12.5px ui-monospace,monospace;min-width:38px;text-align:right}
.frac{font:11.5px ui-monospace,monospace;color:var(--dim);min-width:44px;text-align:right}
.reqs{margin:14px 0;padding:12px 16px;background:var(--card);border:1px solid var(--line);
  border-radius:var(--r-card)}
.reqs summary{cursor:pointer;font-size:12px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--dim)}
.reqs ol{margin:10px 0 0;padding-left:19px}
.reqs li{margin:7px 0;color:var(--dim);font-size:13px}
.wave{margin:26px 0 0}
.whead{display:flex;align-items:center;gap:12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.whead .row{flex:1}
.why{color:var(--dim);font-size:12.5px;margin:8px 0 0}
.item{margin:12px 0;padding:14px 16px;background:var(--card);border:1px solid var(--line);
  border-left:3px solid var(--todo);border-radius:var(--r-card)}
.item.s-done{border-left-color:var(--done)}.item.s-doing{border-left-color:var(--doing)}
.item.s-blocked{border-left-color:var(--blocked)}
summary{cursor:pointer;list-style:none;outline-offset:3px}
summary::-webkit-details-marker{display:none}
.item>summary:hover .ihead h3{color:var(--accent)}
.item:not([open])>summary{margin:0}
.evwrap{margin-top:3px}
.evwrap summary{font:10.5px ui-monospace,monospace;color:var(--dim);letter-spacing:.05em;text-transform:uppercase}
.ihead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:9px}
.ihead h3{flex:1;min-width:0}
.tag{font-size:10.5px;letter-spacing:.04em;padding:2px 8px;border-radius:9px;
  border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.tag.t-done{color:var(--done);border-color:var(--done)}
.tag.t-doing{color:var(--doing);border-color:var(--doing)}
.tag.t-blocked{color:var(--blocked);border-color:var(--blocked)}
.steps{list-style:none;margin:12px 0 0;padding:0}
.step{display:flex;gap:9px;align-items:flex-start;padding:5px 0;font-size:13px;color:var(--dim)}
.step.st-done{color:var(--ink)}
.stext{min-width:0;flex:1}
.box{flex:none;width:16px;height:16px;margin-top:1px;border:1px solid var(--line);
  border-radius:var(--r-ctl);text-align:center;line-height:14px;font-size:10px;color:transparent}
.step.st-done .box{background:var(--done);border-color:var(--done);color:#fff}
.step.st-doing .box{border-color:var(--doing);color:var(--doing)}
.step.st-blocked .box,.step.st-invalidated .box{border-color:var(--blocked);color:var(--blocked)}
.step.st-done_off_main .box,.step.st-superseded .box{border-color:var(--dim);color:var(--dim)}
.stepstate{display:inline-block;margin-left:7px;padding:0 5px;border:1px solid var(--line);
  border-radius:8px;color:var(--dim);font:9.5px ui-monospace,monospace;vertical-align:1px}
.ev{margin-top:3px;font:11.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
  padding-left:8px;border-left:2px solid var(--line);overflow-x:auto;word-break:break-word}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--dim);
  font-size:11.5px}
@media (max-width:520px){
  .wrap{padding:18px 12px 48px} h1{font-size:18px} .frac{display:none}
  .whead{flex-wrap:wrap} h2{width:100%}
  .awhead{display:block}.awhead time{display:block;margin-top:7px;white-space:normal}
  .awgrid,.outcomegrid{grid-template-columns:1fr}.engineering{grid-template-columns:1fr}
}

.feed{margin:18px 0 22px;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.feedhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.feedhead h2{margin:0;font-size:15px}
.feedtally{font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums}
.acts{list-style:none;margin:10px 0 0;padding:0;display:flex;flex-direction:column}
.act{display:grid;grid-template-columns:64px 1fr auto;gap:10px;align-items:baseline;
  padding:7px 0;border-top:1px solid var(--line)}
.act:first-child{border-top:0}
.akind{font-size:10px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;
  padding:2px 6px;border-radius:4px;text-align:center}
.k-fix .akind{background:rgba(224,138,42,.16);color:#e08a2a}
.k-tool .akind{background:rgba(90,140,255,.16);color:#6f9bff}
.k-build .akind{background:rgba(58,170,110,.16);color:#3aaa6e}
.k-record .akind{background:rgba(140,140,150,.16);color:var(--dim)}
.asub{min-width:0;font-size:13px;line-height:1.45}
.ameta{display:flex;align-items:baseline;gap:10px;white-space:nowrap;font-size:11px;color:var(--dim);
  font-variant-numeric:tabular-nums}
.ameta code{font-size:11px}
@media(max-width:640px){
  .act{grid-template-columns:56px 1fr;grid-template-areas:"k s" ". m"}
  .akind{grid-area:k}.asub{grid-area:s}.ameta{grid-area:m;margin-top:2px}
}

.k-data .akind{background:rgba(150,120,200,.16);color:#a98fd6}
.k-revert .akind{background:rgba(200,90,90,.16);color:#d08a8a}
.more{margin-top:6px}
.more summary{cursor:pointer;font-size:12px;color:var(--dim);padding:6px 0;list-style:none}
.more summary::-webkit-details-marker{display:none}
/* An explicit affordance: the default marker is suppressed by the reset, so without this the
   toggle rendered as plain grey text and read as a caption rather than a control. */
.more summary::before{content:"\25B8";display:inline-block;margin-right:6px;transition:transform .12s}
.more[open] summary::before{transform:rotate(90deg)}
.more summary:hover{color:var(--fg)}
.more .acts{margin-top:2px}

.proj{margin:26px 0 8px}
.phead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding-bottom:8px;
  border-bottom:2px solid var(--line)}
.phead h2{margin:0;font-size:19px;letter-spacing:-.01em}
.phead .row{flex:1;min-width:220px}
</style>"""


# ----------------------------------------------------------------------------------------- cli

def cmd_render(plan: dict) -> None:
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(render_html(plan), encoding="utf-8")
    d, t = overall(plan)
    print(
        f"wrote {HTML_OUT.relative_to(ROOT).as_posix()}  "
        f"(engineering history: {d}/{t} unweighted steps, {pct(d, t)}%; "
        "not product readiness)"
    )
    print(f"live at {PUBLIC_URL}")


def cmd_check(plan: dict) -> int:
    bad: list[str] = []
    seen: set[str] = set()
    if plan.get("progress_schema") != 2:
        bad.append("progress_schema must be 2 (independent outcome gates)")
    if not (plan.get("product_scope") or "").strip():
        bad.append("product_scope is empty")
    bad.extend(active_work_errors(plan))

    outcome_ids: set[str] = set()
    outcomes = plan.get("outcome_gates")
    if not isinstance(outcomes, list) or not outcomes:
        bad.append("outcome_gates must be a non-empty list")
        outcomes = []
    for gate in outcomes:
        gate_id = gate.get("id", "")
        if not gate_id:
            bad.append("outcome gate has no id")
        elif gate_id in outcome_ids:
            bad.append(f"duplicate outcome gate id {gate_id!r}")
        outcome_ids.add(gate_id)
        if gate.get("status") not in OUTCOME_STATES:
            bad.append(f"{gate_id or '(unnamed outcome)'}: unknown outcome state "
                       f"{gate.get('status')!r}")
        for field in ("name", "measure", "acceptance"):
            if not (gate.get(field) or "").strip():
                bad.append(f"{gate_id or '(unnamed outcome)'}: empty {field}")
        evidence = gate.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(row, str) and row.strip() for row in evidence
        ):
            bad.append(f"{gate_id or '(unnamed outcome)'}: evidence must be non-empty strings")
        blockers = gate.get("blockers", [])
        if not isinstance(blockers, list) or not all(
            isinstance(row, str) and row.strip() for row in blockers
        ):
            bad.append(f"{gate_id or '(unnamed outcome)'}: blockers must be strings")

    for _, item in items(plan):
        if item["id"] in seen:
            bad.append(f"duplicate item id {item['id']!r}")
        seen.add(item["id"])
        if not item["steps"]:
            bad.append(f"{item['id']}: no steps, so its bar can never mean anything")
        for n, s in enumerate(item["steps"]):
            status = step_status(s)
            if status not in STEP_STATES:
                bad.append(f"{item['id']} step {n}: unknown step state {status!r}")
                continue
            if status != "todo" and not (s.get("evidence") or "").strip():
                bad.append(
                    f"{item['id']} step {n} is {status} with NO evidence: {s['t']!r}"
                )
            if "status" in s:
                should_be_done = status == "done"
                if bool(s.get("done")) != should_be_done:
                    bad.append(
                        f"{item['id']} step {n}: done={bool(s.get('done'))} "
                        f"disagrees with explicit status={status!r}"
                    )
        if item.get("state") and item["state"] not in STATES:
            bad.append(f"{item['id']}: unknown state {item['state']!r}")
    for b in bad:
        print(f"  FAIL {b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in {PLAN.relative_to(ROOT).as_posix()}")
        return 1
    d, t = overall(plan)
    print(
        f"plan OK: {len(outcome_ids)} independent outcome gates; "
        f"{len(seen)} engineering items, {t} unweighted steps, {d} delivered "
        f"({pct(d, t)}% engineering history, not product readiness); every claim has evidence"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("render")
    sub.add_parser("check")
    pt = sub.add_parser("tick")
    pt.add_argument("item")
    pt.add_argument("step", type=int)
    pt.add_argument("-e", "--evidence", required=True,
                    help="what you OBSERVED. A tick without evidence is a claim, and is refused.")
    pu = sub.add_parser("untick")
    pu.add_argument("item")
    pu.add_argument("step", type=int)
    ps = sub.add_parser("state")
    ps.add_argument("item")
    ps.add_argument("state", choices=STATES)
    # `now` is its own subcommand rather than a field to hand-edit, because a stale "working on
    # now" is worse than none: it asserts activity that has stopped. One short command means it
    # actually gets kept current.
    pn = sub.add_parser("now", help="set the WORKING ON NOW banner (empty string clears it)")
    pn.add_argument("text", help="one sentence. Pass '' to clear the banner entirely.")
    pn.add_argument("--at", default="", help="timestamp shown beside it (free-form)")

    # CAPTURE, in one line each. Owner, 2026-07-27: *"make sure whatever system u use to update it
    # is easy so u can always do it it should hold everything your working on big projects and
    # subprojects"*. "Easy" is the load-bearing word: a board I have to hand-edit JSON to extend is
    # a board that silently stops holding everything the first busy hour, which is exactly how the
    # page came to show one project while several were in flight.
    pp = sub.add_parser("add-project", help="a new PROJECT (top level)")
    pp.add_argument("id")
    pp.add_argument("name")
    pp.add_argument("why", nargs="?", default="")
    pg = sub.add_parser("add-group", help="a new GROUP inside a project (a wave)")
    pg.add_argument("project")
    pg.add_argument("id")
    pg.add_argument("name")
    pg.add_argument("why", nargs="?", default="")
    pi = sub.add_parser("add-item", help="a new SUBPROJECT inside a group")
    pi.add_argument("group")
    pi.add_argument("id")
    pi.add_argument("name")
    pi.add_argument("why", nargs="?", default="")
    pst = sub.add_parser("add-step", help="a new STEP on a subproject")
    pst.add_argument("item")
    pst.add_argument("text")
    a = ap.parse_args()

    plan = load()

    def _migrate_to_projects() -> None:
        """Move a legacy top-level `waves` under `projects` the first time a project is added, so
        the one-project file and the many-project file are never both live at once."""
        if "projects" not in plan:
            plan["projects"] = [{
                "id": "stockroom", "name": plan.get("title", "Project"),
                "why": plan.get("note", ""), "waves": plan.pop("waves", []),
            }]

    if a.cmd == "add-project":
        _migrate_to_projects()
        if any(pr["id"] == a.id for pr in plan["projects"]):
            raise SystemExit(f"project {a.id!r} already exists")
        plan["projects"].append({"id": a.id, "name": a.name, "why": a.why, "waves": []})
        save(plan)
        cmd_render(plan)
        print(f"project {a.id}: {a.name}")
        return 0
    if a.cmd == "add-group":
        _migrate_to_projects()
        proj = next((pr for pr in plan["projects"] if pr["id"] == a.project), None)
        if proj is None:
            raise SystemExit(f"no such project: {a.project}")
        proj.setdefault("waves", []).append(
            {"id": a.id, "name": a.name, "why": a.why, "items": []}
        )
        save(plan)
        cmd_render(plan)
        print(f"group {a.id}: {a.name}")
        return 0
    if a.cmd == "add-item":
        group = next((w for w in waves(plan) if w["id"] == a.group), None)
        if group is None:
            raise SystemExit(f"no such group: {a.group}")
        group.setdefault("items", []).append(
            {"id": a.id, "name": a.name, "why": a.why, "steps": []}
        )
        save(plan)
        cmd_render(plan)
        print(f"item {a.id}: {a.name}")
        return 0
    if a.cmd == "add-step":
        _, item = find(plan, a.item)
        item.setdefault("steps", []).append({"t": a.text, "done": False, "evidence": ""})
        save(plan)
        cmd_render(plan)
        print(f"{a.item} step {len(item['steps']) - 1}: {a.text}")
        return 0

    if a.cmd == "render":
        cmd_render(plan)
        return 0
    if a.cmd == "check":
        return cmd_check(plan)
    if a.cmd == "now":
        text = a.text.strip()
        plan["now"] = text
        plan["now_updated"] = a.at.strip()
        save(plan)
        cmd_render(plan)
        print(f"now: {text or '(cleared)'}")
        return 0

    _, item = find(plan, a.item)
    if a.cmd in ("tick", "untick"):
        if not 0 <= a.step < len(item["steps"]):
            raise SystemExit(f"{a.item} has steps 0..{len(item['steps']) - 1}, not {a.step}")
        step = item["steps"][a.step]
        step["done"] = a.cmd == "tick"
        step["status"] = "done" if a.cmd == "tick" else "todo"
        step["evidence"] = a.evidence if a.cmd == "tick" else ""
        print(f"{a.cmd}ed {a.item}[{a.step}]: {step['t']}")
    else:
        item["state"] = a.state
        print(f"{a.item} state -> {a.state}")

    save(plan)
    cmd_render(plan)
    d, t = item_progress(item)
    print(f"{item['name']}: {d}/{t} delivered engineering steps (unweighted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
