#!/usr/bin/env python3
"""Render the rebuild plan to a single self-contained HTML page, and tick its boxes.

The owner asked to "always see everything on this list and ur exact progress with bars for each
one", reachable "by my phone too so tailscale". So: the plan is DATA (docs/progress/rebuild-plan.json),
this renders it to docs/progress/index.html, and a static server + `tailscale serve` publishes it at
https://shdesktop.taild54105.ts.net/progress on the tailnet.

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
            p += [
                f'<article class="item s-{st}">',
                f'<div class="ihead"><h3>{e(item["name"])}</h3>'
                f'<span class="tag t-{st}">{label}</span></div>',
                f'<div class="row">{bar(i_d, i_t, st)}</div>',
                f'<p class="why">{e(item["why"])}</p>',
                '<ul class="steps">',
            ]
            for s in item["steps"]:
                done = bool(s.get("done"))
                box = "&#10003;" if done else "&nbsp;"
                ev = (f'<div class="ev">{e(s["evidence"])}</div>'
                      if done and s.get("evidence") else "")
                p.append(f'<li class="step{" done" if done else ""}">'
                         f'<span class="box">{box}</span>'
                         f'<div class="stext"><div class="t">{e(s["t"])}</div>{ev}</div></li>')
            p += ["</ul>", "</article>"]
        p.append("</section>")

    p += [
        f'<footer>Generated from <code>{e(PLAN.relative_to(ROOT).as_posix())}</code> by '
        f'<code>scripts/progress.py</code>. A box is only ticked with evidence.</footer>',
        "</div>",
    ]
    return "\n".join(p) + "\n"


STYLE = """<style>
:root{
  --bg:#0d0f12; --card:#15181e; --line:#242932; --ink:#e9ebee; --dim:#98a1ad;
  --done:#3fb950; --doing:#d29922; --blocked:#f85149; --todo:#3a414b; --accent:#58a6ff;
  --r-card:3px; --r-ctl:2px;
}
@media (prefers-color-scheme:light){:root{
  --bg:#f5f6f8; --card:#fff; --line:#e2e5ea; --ink:#11141a; --dim:#5b6472;
  --done:#1a7f37; --doing:#9a6700; --blocked:#cf222e; --todo:#d2d7dd; --accent:#0969da;}}
:root[data-theme=dark]{
  --bg:#0d0f12; --card:#15181e; --line:#242932; --ink:#e9ebee; --dim:#98a1ad;
  --done:#3fb950; --doing:#d29922; --blocked:#f85149; --todo:#3a414b; --accent:#58a6ff;}
:root[data-theme=light]{
  --bg:#f5f6f8; --card:#fff; --line:#e2e5ea; --ink:#11141a; --dim:#5b6472;
  --done:#1a7f37; --doing:#9a6700; --blocked:#cf222e; --todo:#d2d7dd; --accent:#0969da;}
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
    a = ap.parse_args()

    plan = load()
    if a.cmd == "render":
        cmd_render(plan)
        return 0
    if a.cmd == "check":
        return cmd_check(plan)

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
