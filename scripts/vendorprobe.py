"""Look at a CAD vendor's REAL page and report the controls guided capture has to drive.

Owner, 2026-07-27: *"cant you click around yourself and find the answer you have full access to
my pc"*. This is that, made repeatable.

WHY IT EXISTS
`host/vendor_drivers/drivers.py` carries selectors marked `OWNER-VALIDATE: first-guess selectors`
for Ultra Librarian, SnapEDA and SamacSys. A first guess is a blind spot: the driver clicks
nothing, reports a guidance message, and the run looks merely "manual" rather than broken. The
vendor pages are login-gated and change, so the answer cannot come from documentation - it has to
be read off the live DOM, on a machine that is signed in. That machine is the owner's.

WHAT IT DOES, AND DELIBERATELY DOES NOT
It OPENS a page and READS it. It clicks nothing, downloads nothing, and submits nothing, so it
stays inside every vendor's terms exactly as `enrich/cad_sources.py` does - that module resolves
the URLs and this one surveys what is on them. `--click` exists for one narrow purpose (opening a
vendor's own export dialog so its formats can be surveyed) and names what it clicked.

THE PROFILE IS PERSISTENT AND SEPARATE
`--profile` defaults to a directory of its own, never the owner's Edge profile: a second Edge
instance cannot share a live profile, and their browsing session is not ours to hold open. Because
it persists, a sign-in done once during `open` is still there on the next run - the same
sign-in-once model the app's WebView2 capture profile uses.

USAGE (Windows-side; CDP binds to Windows loopback, which WSL cannot reach)
    py scripts\\vendorprobe.py open TPD6E05U06RVZR --vendor ultralibrarian
    py scripts\\vendorprobe.py survey
    py scripts\\vendorprobe.py survey --json out.json
    py scripts\\vendorprobe.py shot page.png
    py scripts\\vendorprobe.py close

PRIOR ART ADOPTED, not reimplemented: `stockroom.host.cdp_probe` (targets, websocket, evaluate)
and `scripts/windrive.py`'s connection shape. The vendor URLs come from
`enrich.cad_sources.resolve_cad_sources`, so this tool and guided capture can never disagree
about which page a vendor's part lives on.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "app" / "backend",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from stockroom.enrich.cad_sources import resolve_cad_sources  # noqa: E402
from stockroom.host.cdp_probe import CDPClient, list_targets  # noqa: E402

DEFAULT_PORT = 9333

_EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


class ProbeError(RuntimeError):
    """Something the caller has to fix, stated with which side it was looked at from."""


def _side() -> str:
    return "WSL" if Path("/proc/version").exists() else "Windows"


def _browser_exe() -> str:
    """The installed Edge, DISCOVERED rather than hardcoded to one machine's layout."""
    for candidate in _EDGE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    override = os.environ.get("STOCKROOM_BROWSER")
    if override and Path(override).exists():
        return override
    raise ProbeError(
        "no Microsoft Edge found at either Program Files location. Set STOCKROOM_BROWSER to a "
        "Chromium-based browser executable."
    )


def _profile_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise ProbeError("LOCALAPPDATA is unset; pass --profile explicitly.")
    return Path(base) / "Stockroom" / "vendorprobe-profile"


def _is_web_page(target: dict) -> bool:
    """True for a real web page, false for the browser's own chrome.

    Edge opens first-run and sync-promo pages (`edge://`, `chrome://`) as REAL page targets, and
    on a fresh profile one of them is created BEFORE the vendor URL. Taking the first page target
    therefore surveyed Microsoft's "we are now syncing your browsing data" dialog rather than the
    vendor (observed 2026-07-27 on the owner's machine, first run of this tool). Scheme is the
    fact that separates them.
    """
    if target.get("type") != "page" or not target.get("webSocketDebuggerUrl"):
        return False
    url = (target.get("url") or "").lower()
    return url.startswith("http://") or url.startswith("https://")


def _page_ws(port: int) -> str:
    pages = [t for t in list_targets(port) if _is_web_page(t)]
    if not pages:
        raise ProbeError(
            f"no http(s) page answering on 127.0.0.1:{port} (looked from {_side()}). "
            + (
                "CDP binds to WINDOWS loopback, which WSL cannot reach - run this with a Windows "
                "python, e.g. `py scripts\\vendorprobe.py ...`."
                if _side() == "WSL"
                else "Open one first with `vendorprobe.py open <mpn>`."
            )
        )
    return pages[0]["webSocketDebuggerUrl"]


def _connect(port: int) -> CDPClient:
    client = CDPClient(_page_ws(port))
    if not client.connect():
        raise ProbeError("the page target exists but the websocket refused the connection")
    client.enable()
    return client


# The survey. Reports the controls a driver would have to find, as DATA: every element whose text
# or attributes name a CAD tool or a download, plus every radio/checkbox/select (a format chooser
# is usually one of those, and whether it is a RADIO or a CHECKBOX is exactly the question - a
# radio group means one format per download and the driver must sequence them).
_SURVEY_JS = r"""
(function(){
  function vis(el){try{return !!(el&&el.offsetParent!==null&&el.getClientRects().length);}
    catch(e){return false;}}
  function txt(el){try{return (el.textContent||'').replace(/\s+/g,' ').trim().slice(0,120);}
    catch(e){return '';}}
  function sel(el){
    if(el.id) return '#'+el.id;
    var parts=[el.tagName.toLowerCase()];
    if(el.getAttribute('name')) parts.push('[name="'+el.getAttribute('name')+'"]');
    if(el.className&&typeof el.className==='string'){
      var c=el.className.trim().split(/\s+/).slice(0,3).join('.');
      if(c) parts.push('.'+c);
    }
    return parts.join('');
  }
  function attrs(el){
    var out={};
    try{
      for(var i=0;i<el.attributes.length;i++){
        var a=el.attributes[i];
        if(/^(id|name|type|class|href|value|for|title|aria-label|role|checked|disabled)$/.test(a.name)
           || a.name.indexOf('data-')===0){
          out[a.name]=String(a.value).slice(0,120);
        }
      }
    }catch(e){}
    return out;
  }
  var KEY=/kicad|altium|eagle|orcad|allegro|pads|pulsonix|diptrace|download|format|export|3d model|step/i;
  var seen=[], out=[];
  function push(el, why){
    if(seen.indexOf(el)>=0) return;
    seen.push(el);
    out.push({why:why, tag:el.tagName.toLowerCase(), selector:sel(el), visible:vis(el),
              text:txt(el), attrs:attrs(el)});
  }
  var nodes=document.querySelectorAll('a,button,input,select,label,[role=button],[role=radio],[role=tab]');
  for(var i=0;i<nodes.length;i++){
    var el=nodes[i], t=el.tagName.toLowerCase();
    var type=(el.getAttribute('type')||'').toLowerCase();
    if(t==='input'&&(type==='radio'||type==='checkbox')){ push(el,'choice:'+type); continue; }
    if(t==='select'){ push(el,'choice:select'); continue; }
    var hay=txt(el)+' '+JSON.stringify(attrs(el));
    if(KEY.test(hay)) push(el,'keyword');
  }
  // Radio GROUPS are the decisive fact: a shared name means the formats are mutually exclusive,
  // so two formats require two downloads.
  var groups={};
  var radios=document.querySelectorAll('input[type=radio]');
  for(var j=0;j<radios.length;j++){
    var n=radios[j].getAttribute('name')||'(unnamed)';
    groups[n]=(groups[n]||0)+1;
  }
  var dialogs=[];
  var dl=document.querySelectorAll('[role=dialog],[class*=modal],[class*=Modal],[class*=dialog]');
  for(var k=0;k<dl.length;k++){ if(vis(dl[k])) dialogs.push({selector:sel(dl[k]), text:txt(dl[k])}); }
  return JSON.stringify({url:location.href, title:document.title,
                         radioGroups:groups, visibleDialogs:dialogs, controls:out});
})()
"""


def _survey(client: CDPClient) -> dict:
    raw = client.evaluate(_SURVEY_JS, timeout=20.0)
    if not isinstance(raw, str):
        raise ProbeError(f"the survey did not return a string (got {type(raw).__name__})")
    return json.loads(raw)


def _print_survey(data: dict) -> None:
    print(f"URL    {data.get('url','')}")
    print(f"TITLE  {data.get('title','')}")
    groups = data.get("radioGroups") or {}
    if groups:
        print("\nRADIO GROUPS (a shared name = formats are mutually exclusive = one per download)")
        for name, count in sorted(groups.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>3}x  name={name!r}")
    else:
        print("\nRADIO GROUPS  none on this page")
    dialogs = data.get("visibleDialogs") or []
    if dialogs:
        print("\nVISIBLE DIALOGS")
        for d in dialogs:
            print(f"  {d.get('selector','')}  {d.get('text','')[:90]}")
    controls = data.get("controls") or []
    shown = [c for c in controls if c.get("visible")]
    hidden = len(controls) - len(shown)
    print(f"\nCONTROLS  {len(shown)} visible ({hidden} hidden, not shown)")
    for c in shown:
        label = c.get("text") or c.get("attrs", {}).get("aria-label") or ""
        print(f"  [{c.get('why','')}] {c.get('selector','')}")
        if label:
            print(f"        text: {label}")
        interesting = {
            k: v
            for k, v in (c.get("attrs") or {}).items()
            if k not in ("class", "text") and v
        }
        if interesting:
            print(f"        attrs: {json.dumps(interesting)[:220]}")


def _navigate(client: CDPClient, url: str, *, settle: float) -> None:
    client.send("Page.enable", {})
    client.send("Page.navigate", {"url": url}, timeout=20.0)
    time.sleep(settle)


def _resolve_url(mpn: str, vendor: str) -> tuple[str, str]:
    sources = resolve_cad_sources(mpn)
    if not sources:
        raise ProbeError(f"no CAD source resolves for MPN {mpn!r} (a blank MPN resolves to none)")
    keys = [s.key for s in sources]
    for source in sources:
        if source.key == vendor:
            return source.url, source.label
    raise ProbeError(f"unknown vendor {vendor!r}; this build offers {', '.join(keys)}")


def cmd_open(args) -> int:
    exe = _browser_exe()
    profile = _profile_dir(args.profile)
    profile.mkdir(parents=True, exist_ok=True)
    url, label = _resolve_url(args.mpn, args.vendor)
    print(f"vendor   {label} ({args.vendor})")
    print(f"url      {url}")
    print(f"profile  {profile}")
    subprocess.Popen(
        [
            exe,
            f"--remote-debugging-port={args.port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            _page_ws(args.port)
            break
        except ProbeError:
            time.sleep(0.4)
    else:
        raise ProbeError(
            f"the browser did not answer CDP on port {args.port} within {args.timeout:.0f}s"
        )
    print(f"open     CDP ready on 127.0.0.1:{args.port}")
    print("\nSign in in that window if the vendor asks; the profile keeps it for the next run.")
    print("Then:  py scripts\\vendorprobe.py survey")
    return 0


def cmd_goto(args) -> int:
    url, label = _resolve_url(args.mpn, args.vendor)
    client = _connect(args.port)
    try:
        print(f"vendor   {label} ({args.vendor})")
        print(f"url      {url}")
        _navigate(client, url, settle=args.settle)
        data = _survey(client)
        print()
        _print_survey(data)
    finally:
        client.close()
    return 0


def cmd_survey(args) -> int:
    client = _connect(args.port)
    try:
        if args.click:
            clicked = client.evaluate(
                "(function(){var el=document.querySelector("
                + json.dumps(args.click)
                + ");if(!el)return 'NOT FOUND';el.click();return 'clicked';})()",
                timeout=10.0,
            )
            print(f"click    {args.click} -> {clicked}")
            time.sleep(args.settle)
        data = _survey(client)
        _print_survey(data)
        if args.json:
            Path(args.json).write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"\nwrote {args.json}")
    finally:
        client.close()
    return 0


def cmd_shot(args) -> int:
    client = _connect(args.port)
    try:
        result = client.send("Page.captureScreenshot", {"format": "png"}, timeout=25.0)
        data = (result or {}).get("result", {}).get("data")
        if not data:
            raise ProbeError("the browser returned no screenshot data")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(data))
        print(f"wrote {out} ({out.stat().st_size} bytes)")
    finally:
        client.close()
    return 0


def cmd_close(args) -> int:
    try:
        client = _connect(args.port)
    except ProbeError as exc:
        print(f"nothing to close: {exc}")
        return 0
    try:
        client.send("Browser.close", {}, timeout=5.0)
    except Exception:  # noqa: BLE001 - the browser exiting mid-call is the success case
        pass
    finally:
        client.close()
    print("closed")
    return 0


def cmd_eval(args) -> int:
    """Evaluate an expression read from a FILE.

    Read from a file, never from argv: WSL -> cmd.exe interop re-splits the command line, so any
    expression carrying quotes or parentheses arrives shredded. `windrive.py` learned the same
    thing and uses the same `@file` shape.
    """
    expression = Path(args.file).read_text(encoding="utf-8")
    client = _connect(args.port)
    try:
        value = client.evaluate(expression, timeout=20.0)
        print(value if isinstance(value, str) else json.dumps(value, indent=2, default=str))
        if args.settle:
            time.sleep(args.settle)
    finally:
        client.close()
    return 0


def cmd_url(args) -> int:
    """Navigate to a literal URL and report where the browser actually LANDED.

    The landing URL is the point: a vendor that 404s, redirects to a search, or bounces to a login
    is invisible to any check that only looks at the URL we asked for.
    """
    client = _connect(args.port)
    try:
        _navigate(client, args.target, settle=args.settle)
        landed = client.evaluate(
            "JSON.stringify({url:location.href,title:document.title,"
            "notFound:/404|not found|page not found/i.test(document.title||'')})",
            timeout=10.0,
        )
        print(f"asked  {args.target}")
        print(f"landed {landed}")
    finally:
        client.close()
    return 0


def cmd_targets(args) -> int:
    targets = list_targets(args.port)
    if not targets:
        print(f"no CDP targets on 127.0.0.1:{args.port} (looked from {_side()})")
        return 0
    chosen = next((t for t in targets if _is_web_page(t)), None)
    for target in targets:
        mark = "->" if target is chosen else "  "
        print(f"{mark} {target.get('type','?'):<12} {(target.get('url') or '')[:96]}")
    if chosen is None:
        print("\nNONE of these is an http(s) page, so `survey` has nothing to read.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--profile", default=None, help="persistent browser profile dir")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_open = sub.add_parser("open", help="launch the browser at a vendor's page for an MPN")
    p_open.add_argument("mpn")
    p_open.add_argument("--vendor", default="ultralibrarian")
    p_open.add_argument("--timeout", type=float, default=45.0)
    p_open.set_defaults(func=cmd_open)

    p_goto = sub.add_parser("goto", help="navigate the open browser to another vendor/MPN, then survey")
    p_goto.add_argument("mpn")
    p_goto.add_argument("--vendor", default="ultralibrarian")
    p_goto.add_argument("--settle", type=float, default=6.0)
    p_goto.set_defaults(func=cmd_goto)

    p_survey = sub.add_parser("survey", help="report the download/format controls on the open page")
    p_survey.add_argument("--click", default=None, help="CSS selector to click first (e.g. a Download button that opens the format dialog)")
    p_survey.add_argument("--settle", type=float, default=2.5)
    p_survey.add_argument("--json", default=None, help="also write the raw survey here")
    p_survey.set_defaults(func=cmd_survey)

    p_shot = sub.add_parser("shot", help="screenshot the open page")
    p_shot.add_argument("out")
    p_shot.set_defaults(func=cmd_shot)

    p_close = sub.add_parser("close", help="close the probe browser")
    p_close.set_defaults(func=cmd_close)

    p_targets = sub.add_parser("targets", help="list every CDP target, and which one is surveyed")
    p_targets.set_defaults(func=cmd_targets)

    p_eval = sub.add_parser("eval", help="evaluate a JS expression read from a FILE, on the open page")
    p_eval.add_argument("file", help="path to a file holding the expression")
    p_eval.add_argument("--settle", type=float, default=0.0, help="seconds to wait after evaluating")
    p_eval.set_defaults(func=cmd_eval)

    p_url = sub.add_parser("url", help="navigate the open page to a literal URL, then report where it landed")
    p_url.add_argument("target")
    p_url.add_argument("--settle", type=float, default=6.0)
    p_url.set_defaults(func=cmd_url)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ProbeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
