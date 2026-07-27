#!/usr/bin/env python3
"""Render the rebuild plan to a single self-contained HTML page, and tick its boxes.

The owner asked to "always see everything on this list and ur exact progress with bars for each
one", reachable "by my phone too so tailscale". So: the plan is DATA (docs/progress/rebuild-plan.json),
this renders it to docs/progress/index.html, and a static server + `tailscale serve` publishes it at
https://shdesktop.taild54105.ts.net/progress on the tailnet.

PRIOR ART evaluated before writing this (local instructions: "say what you evaluated and REJECTED, and why"):
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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "progress" / "rebuild-plan.json"
HTML_OUT = ROOT / "docs" / "progress" / "index.html"

STATES = ("todo", "doing", "blocked", "done")
PUBLIC_URL = "https://shdesktop.taild54105.ts.net/progress"


def load() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def save(plan: dict) -> None:
    plan["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    PLAN.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def items(plan: dict):
    for wave in plan["waves"]:
        for item in wave["items"]:
            yield wave, item


def find(plan: dict, item_id: str):
    for wave, item in items(plan):
        if item["id"] == item_id:
            return wave, item
    known = ", ".join(i["id"] for _, i in items(plan))
    raise SystemExit(f"no item with id {item_id!r}. Known: {known}")


def item_progress(item: dict) -> tuple[int, int]:
    steps = item["steps"]
    return sum(1 for s in steps if s.get("done")), len(steps)


def wave_progress(wave: dict) -> tuple[int, int]:
    done = total = 0
    for item in wave["items"]:
        d, t = item_progress(item)
        done, total = done + d, total + t
    return done, total


def overall(plan: dict) -> tuple[int, int]:
    done = total = 0
    for wave in plan["waves"]:
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
    done, total = item_progress(item)
    if total and done == total:
        return "done"
    return "doing" if done else "todo"


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
        f'<div class="row big">{bar(d, t, "done" if d == t and t else "doing", big=True)}</div>',
        "</header>",
    ]

    # WHAT IS BEING WORKED ON RIGHT NOW (owner, 2026-07-27: "also add what youre currently working
    # on" / "in the html"). Placed above everything else because it answers the question a person
    # opens this page to ask, and a percentage cannot: 52% does not say whether anything is moving.
    # Absent rather than an empty box when nothing is set - a blank "Now:" reads as stalled.
    now = (plan.get("now") or "").strip()
    now_at = (plan.get("now_updated") or "").strip()
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

    for wave in plan["waves"]:
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
                done = bool(s.get("done"))
                box = "&#10003;" if done else "&nbsp;"
                ev = (f'<details class="evwrap"><summary>evidence</summary>'
                      f'<div class="ev">{e(s["evidence"])}</div></details>'
                      if done and s.get("evidence") else "")
                p.append(f'<li class="step{" done" if done else ""}">'
                         f'<span class="box">{box}</span>'
                         f'<div class="stext"><div class="t">{e(s["t"])}</div>{ev}</div></li>')
            p += ["</ul>", "</details>"]
        p.append("</section>")

    p += [
        f'<footer>Generated from <code>{e(PLAN.relative_to(ROOT).as_posix())}</code> by '
        f'<code>scripts/progress.py</code>. A box is only ticked with evidence.</footer>',
        "</div>",
    ]
    return "\n".join(p) + "\n"


STYLE = """<style>
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
.step.done{color:var(--ink)}
.stext{min-width:0;flex:1}
.box{flex:none;width:16px;height:16px;margin-top:1px;border:1px solid var(--line);
  border-radius:var(--r-ctl);text-align:center;line-height:14px;font-size:10px;color:transparent}
.step.done .box{background:var(--done);border-color:var(--done);color:#fff}
.ev{margin-top:3px;font:11.5px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
  padding-left:8px;border-left:2px solid var(--line);overflow-x:auto;word-break:break-word}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);color:var(--dim);
  font-size:11.5px}
@media (max-width:520px){
  .wrap{padding:18px 12px 48px} h1{font-size:18px} .frac{display:none}
  .whead{flex-wrap:wrap} h2{width:100%}
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
</style>"""


# ----------------------------------------------------------------------------------------- cli

def cmd_render(plan: dict) -> None:
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(render_html(plan), encoding="utf-8")
    d, t = overall(plan)
    print(f"wrote {HTML_OUT.relative_to(ROOT).as_posix()}  ({d}/{t} steps, {pct(d, t)}%)")
    print(f"live at {PUBLIC_URL}")


def cmd_check(plan: dict) -> int:
    bad: list[str] = []
    seen: set[str] = set()
    for _, item in items(plan):
        if item["id"] in seen:
            bad.append(f"duplicate item id {item['id']!r}")
        seen.add(item["id"])
        if not item["steps"]:
            bad.append(f"{item['id']}: no steps, so its bar can never mean anything")
        for n, s in enumerate(item["steps"]):
            if s.get("done") and not s.get("evidence"):
                bad.append(f"{item['id']} step {n} ticked with NO evidence: {s['t']!r}")
        if item.get("state") and item["state"] not in STATES:
            bad.append(f"{item['id']}: unknown state {item['state']!r}")
    for b in bad:
        print(f"  FAIL {b}")
    if bad:
        print(f"\n{len(bad)} problem(s) in {PLAN.relative_to(ROOT).as_posix()}")
        return 1
    d, t = overall(plan)
    print(f"plan OK: {len(seen)} items, {t} steps, {d} done ({pct(d, t)}%), every tick has evidence")
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
    a = ap.parse_args()

    plan = load()
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
        step["evidence"] = a.evidence if a.cmd == "tick" else ""
        print(f"{a.cmd}ed {a.item}[{a.step}]: {step['t']}")
    else:
        item["state"] = a.state
        print(f"{a.item} state -> {a.state}")

    save(plan)
    cmd_render(plan)
    d, t = item_progress(item)
    print(f"{item['name']}: {pct(d, t)}% ({d}/{t})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
