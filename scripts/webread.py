#!/usr/bin/env python3
"""Look at a web page in a real browser and report what is actually on it.

THE ONE TOOL for "read / inspect a page". Owner, 2026-07-27: *"one tool for each purpose that gets
updated or deleted, make sure no other tools exist. too many times we have rebuilt something that
can just be fixed"*.

It absorbed `scripts/vendorprobe.py`, which was written earlier the SAME DAY to survey vendor
controls and did the same job through a second browser. That file is deleted, not deprecated. What
came across: the control survey (`--controls`), the persistent profile so a signed-in page can be
read (`--profile`), vendor URL resolution (`--vendor/--mpn`), and readiness by a REAL signal
(`--expect`) instead of a fixed wait.

WHY IT EXISTS AT ALL. Half the vendor pages that matter here - Component Search Engine's results,
Ultra Librarian's export panel, Octopart's API reference - are client-rendered or bot-guarded, so
`curl`/WebFetch return an empty shell or a 403. Reading those shells produced three separate wrong
conclusions in one session on 2026-07-27, including a coverage probe that could not tell a real
part number from `ZZZNOTAREALPART123` because it was grepping a shell both times. When the data
only exists after JS runs, a real browser IS the data layer.

IT DOES NOT LAUNCH ITS OWN BROWSER. It goes through `stockroom.capture.browser`, which is the one
module that owns launching, so the stealth engine, profile handling and teardown have a single home.

IT READS, IT NEVER DRIVES. Stockroom does not operate provider controls - the person does - so this
tool has no sign-in, no format selection, and no download modes. `--controls` reports what is on a
page as data, which is how a provider's real search form (and therefore the URL Stockroom builds
for it) gets measured instead of guessed.

Usage:
    uv run python scripts/webread.py <url> [--grep TERM ...] [--controls] [--expect CSS]
    uv run python scripts/webread.py --vendor ultralibrarian --mpn TPD6E05U06RVZR --controls
    uv run python scripts/webread.py <url> --profile ~/.stockroom-read --headed   # signed-in page
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "app" / "backend",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

# Every element a driver might have to find, reported as DATA. Whether a format chooser is a RADIO
# group or a CHECKBOX group is the single most consequential fact about a vendor page - it decides
# whether two formats need two downloads - so radio groups are counted explicitly.
_CONTROLS_JS = r"""
(() => {
  const vis = (el) => { try { return !!(el && el.offsetParent !== null && el.getClientRects().length); }
                        catch (e) { return false; } };
  const txt = (el) => { try { return (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 90); }
                        catch (e) { return ''; } };
  const labelled = (el) => {
    try {
      return Array.from(el.labels || []).map(txt).filter(Boolean).join(' | ').slice(0, 120);
    } catch (e) { return ''; }
  };
  const sel = (el) => {
    if (el.id) return '#' + el.id;
    const bits = [el.tagName.toLowerCase()];
    for (const a of ['data-format', 'data-target', 'data-testid', 'name', 'type']) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) bits.push(`[${a}="${v}"]`);
    }
    if (el.className && typeof el.className === 'string') {
      const c = el.className.trim().split(/\s+/).slice(0, 3).join('.');
      if (c) bits.push('.' + c);
    }
    return bits.join('');
  };
  const KEY = /kicad|altium|eagle|orcad|allegro|pads|pulsonix|diptrace|download|format|export|3d|step|sign ?in|login/i;
  const out = [], seen = [];
  const push = (el, why) => {
    if (seen.indexOf(el) >= 0) return;
    seen.push(el);
    const attrs = {};
    const secret = el.tagName === 'INPUT'
      && /^(password|hidden)$/i.test(el.getAttribute('type') || '');
    try {
      for (const a of el.attributes) {
        // NEVER read the value of a password or hidden field. `value` is otherwise the most useful
        // attribute here (it names a radio's choice), so it is excluded per-element rather than
        // dropped for everyone - the same rule capturerec.py already applies to recorded fields.
        if (a.name === 'value' && secret) continue;
        if (/^(id|name|type|href|value|for|aria-label|role|checked|disabled|placeholder)$/.test(a.name)
            || a.name.indexOf('data-') === 0) attrs[a.name] = String(a.value).slice(0, 120);
      }
    } catch (e) {}
    out.push({why, tag: el.tagName.toLowerCase(), selector: sel(el), visible: vis(el),
              text: txt(el) || labelled(el), attrs});
  };
  // EVERY field, unconditionally. Filtering inputs through the keyword regex made this tool blind
  // to exactly the controls a sign-in needs: a bare `input[type=email]` carries no matching text,
  // so a login form surveyed as "12 controls, all marketing links" while its two fields sat right
  // there (measured on SnapMagic's login page, 2026-07-27). A field is a control by definition.
  for (const el of document.querySelectorAll('a,button,input,select,textarea,label,[role=button],[role=tab]')) {
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (el.tagName === 'INPUT') { push(el, 'field:' + (type || 'text')); continue; }
    if (el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') { push(el, 'field:' + el.tagName.toLowerCase()); continue; }
    if (KEY.test(txt(el) + ' ' + el.outerHTML.slice(0, 300))) push(el, 'keyword');
  }
  const groups = {};
  for (const r of document.querySelectorAll('input[type=radio]')) {
    const n = r.getAttribute('name') || '(unnamed)';
    groups[n] = (groups[n] || 0) + 1;
  }
  return JSON.stringify({url: location.href, title: document.title, radioGroups: groups, controls: out});
})()
"""


def _resolve_vendor_url(vendor: str, mpn: str) -> str:
    from stockroom.enrich.cad_sources import resolve_cad_sources

    for source in resolve_cad_sources(mpn):
        if source.key == vendor:
            return source.url
    raise SystemExit(f"no URL for vendor {vendor!r} (offers: "
                     + ", ".join(s.key for s in resolve_cad_sources(mpn or "X")) + ")")


def _print_controls(data: dict) -> None:
    groups = data.get("radioGroups") or {}
    if groups:
        print("\nRADIO GROUPS (a shared name = mutually exclusive = one download per choice)")
        for name, count in sorted(groups.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>3}x  name={name!r}")
    else:
        print("\nRADIO GROUPS  none (choices here are not mutually exclusive)")
    all_controls = data.get("controls") or []
    shown = [c for c in all_controls if c.get("visible")]
    hidden = [c for c in all_controls if not c.get("visible")]
    # A hidden FIELD is the interesting kind of hidden: a sign-in form sitting inside a modal that
    # has not been opened is invisible and is exactly what a survey is looking for. Hidden links
    # stay collapsed to a count, because a page carries dozens and none of them explain anything.
    hidden_fields = [c for c in hidden if str(c.get("why", "")).startswith("field:")]
    print(f"\nCONTROLS  {len(shown)} visible ({len(hidden)} hidden, "
          f"{len(hidden_fields)} of them fields)")
    for c in shown + hidden_fields:
        if not c.get("visible"):
            print("  (hidden)")
        print(f"  [{c['why']}] {c['selector']}")
        if c.get("text"):
            print(f"        text: {c['text']}")
        attrs = {k: v for k, v in (c.get("attrs") or {}).items() if k != "class"}
        if attrs:
            print(f"        attrs: {json.dumps(attrs)[:200]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", nargs="?", default="")
    ap.add_argument("--vendor", default="", help="resolve the URL from the CAD-source registry")
    ap.add_argument("--mpn", default="", help="part number, with --vendor")
    ap.add_argument("--grep", action="append", default=[], metavar="TERM")
    ap.add_argument("--context", type=int, default=240)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--links", action="store_true")
    ap.add_argument("--controls", action="store_true", help="report the page's controls as data")
    ap.add_argument("--expect", default="", help="CSS selector that means the page is ready")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--profile", default="", help="persistent profile dir (keeps a sign-in)")
    ap.add_argument("--headed", action="store_true", help="show the browser (to sign in by hand)")
    args = ap.parse_args()

    url = args.url or (_resolve_vendor_url(args.vendor, args.mpn) if args.vendor else "")
    if not url:
        raise SystemExit("give a URL, or --vendor with --mpn")

    from stockroom.capture.browser import PlaywrightCaptureBrowser, chromium_unavailable_reason

    blocked = chromium_unavailable_reason()
    if blocked:
        print(blocked, file=sys.stderr)
        return 2

    browser = PlaywrightCaptureBrowser(
        download_dir=Path(args.profile or ".") / "_webread-downloads"
        if args.profile
        else Path("/tmp/webread-downloads"),
        profile_dir=Path(args.profile) if args.profile else None,
        headless=not args.headed,
    )

    with browser.session() as page:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Readiness by a REAL signal when one is named, never a fixed wait. A page that never
        # produces it says so, instead of being read half-rendered and reported as fact.
        if args.expect:
            try:
                page.locator(args.expect).first.wait_for(
                    state="attached", timeout=int(args.timeout * 1000)
                )
            except Exception:  # noqa: BLE001
                print(f"WARNING: {args.expect!r} never appeared within {args.timeout:.0f}s; "
                      "what follows may be a partial page")
        else:
            # Ad-supported provider pages can keep analytics and ad requests alive forever.
            # `domcontentloaded` above already established a real document; network-idle is a
            # useful extra signal, not a reason to discard the inspectable page after 45 seconds.
            try:
                page.wait_for_load_state("networkidle", timeout=int(args.timeout * 1000))
            except Exception:  # noqa: BLE001 - continue with the loaded document and say so
                print(
                    f"WARNING: network did not become idle within {args.timeout:.0f}s; "
                    "continuing with the loaded document"
                )

        text = re.sub(r"\n{2,}", "\n", page.inner_text("body"))
        print(f"url: {page.url}")
        print(f"title: {page.title()}")
        print(f"chars: {len(text)}")
        if not text.strip():
            print("EMPTY BODY - a shell or a block, NOT evidence that the page is blank")
        low = text.lower()
        if "just a moment" in low or "verify you are" in low or "security verification" in low:
            print("BOT WALL - this is an interstitial, not the page. Re-run with "
                  "--profile <dir> --headed and clear it once; the profile keeps the clearance.")

        if args.controls:
            _print_controls(json.loads(page.evaluate(_CONTROLS_JS)))

        if args.links:
            for a in page.query_selector_all("a"):
                href = a.get_attribute("href") or ""
                label = (a.inner_text() or "").strip()
                if not args.grep or any(t.lower() in f"{href} {label}".lower() for t in args.grep):
                    print(f"LINK  {label[:50]!r} -> {href}")

        if args.controls or args.links:
            pass
        elif args.dump or not args.grep:
            print(text if args.dump else text[:4000])
        else:
            for term in args.grep:
                hits = list(re.finditer(re.escape(term), text, re.I))
                print(f"\n=== {term!r}: {len(hits)} hit(s) ===")
                for m in hits[:6]:
                    start = max(0, m.start() - args.context)
                    print(f"...{text[start:m.start() + args.context]}...\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
