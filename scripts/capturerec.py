"""Open a real browser for the OWNER to drive, and record what they do.

Owner, 2026-07-27: *"i can clear the wall if u give me some sort of ui to do it on and then also
record what i do so that u see the workflow"*.

WHY THIS EXISTS - two blockers, one tool
1. **Some vendors cannot be automated at all until a human clears a wall.** Measured 2026-07-27:
   SnapEDA serves a Cloudflare Turnstile interstitial to a headless browser (title "Just a
   moment...", the only input on the page is `cf-turnstile-response`). Ultra Librarian does not.
   A person clearing that check ONCE, in a persistent profile, unblocks every later run - and the
   repo already learned in 2026-07-24 that auto-clicking Turnstile only trips detection harder.
2. **Selectors were guessed for months and every guess was wrong.** Watching the real journey is
   strictly better evidence than reading a page: it captures the ORDER, the waits, and the steps a
   DOM dump cannot show (which control had to be clicked before another appeared).

So: this opens a HEADED browser on the persistent capture profile, records every click,
navigation, input (passwords redacted) and download, and writes a trace an adapter can be authored
from.

IT RECORDS, IT DOES NOT ACT. Nothing here clicks anything on the owner's behalf - that is the whole
point. The person drives; the tool watches and writes it down.

RUNS THE SAME ON WINDOWS AND LINUX. It needs a desktop (the browser is visible on purpose), so on a
headless box it will say so rather than pretending.

USAGE
    uv run python scripts/capturerec.py --vendor snapmagic --mpn TPD6E05U06RVZR
    uv run python scripts/capturerec.py --url https://example.com/part --label my-flow

Finish by closing the browser window. The recording is written to
`build/capture-recordings/<label>/` as `actions.json` (+ `trace.zip` unless --no-trace), and the
sign-in / wall clearance stays in the profile for later automated runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent / "app" / "backend",):
    if _candidate.is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

DEFAULT_OUT = _HERE.parent / "build" / "capture-recordings"

# Injected into every page. Records what the person does, with enough selector detail to author an
# adapter from. Values of password fields are NEVER read - only that a password field was filled.
_RECORDER_JS = r"""
(() => {
  if (window.__SR_REC__) return;
  window.__SR_REC__ = [];
  const sel = (el) => {
    if (!el || !el.tagName) return '';
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
  const label = (el) => {
    try { return (el.innerText || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 60); }
    catch (e) { return ''; }
  };
  const push = (rec) => {
    const entry = Object.assign({t: Date.now(), url: location.href}, rec);
    // Kept for the tests, which inject this script directly with no binding present.
    try { window.__SR_REC__.push(entry); } catch (e) {}
    // PUSHED to Python the moment it happens. This array is per-DOCUMENT and resets on every
    // navigation, so polling its length lost every action after the first page change - and the
    // journey being recorded (search -> part -> export panel) is mostly navigations.
    try { if (window.__srRecord) window.__srRecord(entry); } catch (e) {}
  };
  document.addEventListener('click', (e) => {
    const el = e.target && e.target.closest ? (e.target.closest('a,button,input,label,[role=button]') || e.target) : e.target;
    push({kind: 'click', selector: sel(el), text: label(el), tag: el && el.tagName});
  }, true);
  const onEdit = (e) => {
    const el = e.target;
    if (!el || !el.tagName) return;
    const type = (el.getAttribute && el.getAttribute('type') || '').toLowerCase();
    if (type === 'checkbox' || type === 'radio') {
      push({kind: 'check', selector: sel(el), checked: !!el.checked, text: label(el)});
      return;
    }
    const s = sel(el);
    // Coalesce: keep ONE entry per field holding its final value, rather than one per keystroke.
    // Both 'input' and 'change' are listened to because a real person blurs (change) while
    // programmatic fills only emit input - missing either loses part of the workflow.
    const last = window.__SR_REC__[window.__SR_REC__.length - 1];
    const entry = (type === 'password')
      ? {kind: 'fill', selector: s, secret: true}
      : {kind: 'fill', selector: s, value: String(el.value || '').slice(0, 80)};
    if (last && last.kind === 'fill' && last.selector === s) {
      window.__SR_REC__[window.__SR_REC__.length - 1] = Object.assign(last, entry);
      return;
    }
    push(entry);
  };
  document.addEventListener('change', onEdit, true);
  document.addEventListener('input', onEdit, true);
  push({kind: 'page', text: document.title});
})();
"""


def _out_dir(label: str, base: Path) -> Path:
    path = Path(base) / label
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_url(vendor: str, mpn: str) -> str:
    from stockroom.enrich.cad_sources import resolve_cad_sources

    for source in resolve_cad_sources(mpn):
        if source.key == vendor:
            return source.url
    raise SystemExit(
        f"no URL for vendor {vendor!r}; this build offers "
        + ", ".join(s.key for s in resolve_cad_sources(mpn or "X"))
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--vendor", default="", help="vendor key (snapmagic, ultralibrarian, ...)")
    ap.add_argument("--mpn", default="", help="the part to open the vendor at")
    ap.add_argument("--url", default="", help="an explicit URL instead of --vendor/--mpn")
    ap.add_argument("--label", default="", help="name for this recording (default: vendor+time)")
    ap.add_argument("--profile", default="", help="browser profile dir (defaults to the shared capture profile)")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-trace", action="store_true", help="skip the Playwright trace (smaller output)")
    args = ap.parse_args()

    url = args.url or (_resolve_url(args.vendor, args.mpn) if args.vendor else "")
    if not url:
        raise SystemExit("give either --url, or --vendor with --mpn")

    label = args.label or f"{args.vendor or 'session'}-{time.strftime('%Y%m%d-%H%M%S')}"
    out = _out_dir(label, Path(args.out))
    profile = Path(args.profile) if args.profile else out.parent / "_profile"
    profile.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("playwright is not installed; run `uv sync`") from None

    actions: list[dict] = []
    downloads: list[dict] = []

    def _on_action(entry: dict) -> None:
        if not isinstance(entry, dict):
            return
        actions.append(entry)
        kind = entry.get("kind")
        if kind in ("click", "check"):
            state = "" if kind == "click" else f"  -> {entry.get('checked')}"
            print(f"  {kind:<6} {entry.get('selector', '')}  {entry.get('text', '')[:40]}{state}")
        elif kind == "fill":
            shown = "<redacted>" if entry.get("secret") else entry.get("value", "")
            print(f"  fill   {entry.get('selector', '')}  {shown}")

    print(f"vendor url : {url}")
    print(f"profile    : {profile}   (your sign-in is remembered here)")
    print(f"recording  : {out}")
    print()
    print("A browser window will open. Do the whole thing you want me to learn:")
    print("  clear any 'verify you are human' check, sign in if asked, pick the formats,")
    print("  and download the files.")
    print("CLOSE THE WINDOW when you are done - that ends the recording.")
    print()

    with sync_playwright() as pw:
        try:
            context = pw.chromium.launch_persistent_context(
                str(profile),
                headless=False,  # visible ON PURPOSE: this is a human driving it
                accept_downloads=True,
                args=["--start-maximized"],
                no_viewport=True,
            )
        except Exception as exc:  # noqa: BLE001 - a headless box is a real, nameable situation
            raise SystemExit(
                f"could not open a visible browser: {exc}\n"
                "This tool needs a desktop - it exists so a PERSON can drive the page."
            ) from None

        if not args.no_trace:
            context.tracing.start(screenshots=True, snapshots=True, sources=False)

        # Actions arrive as EVENTS, not by polling: the in-page recorder calls this the instant
        # something happens, and a binding survives navigation where a per-document array does not.
        context.expose_binding("__srRecord", lambda _source, entry: _on_action(entry))
        # Re-inject on every document so a navigation never loses the recorder.
        context.add_init_script(_RECORDER_JS)

        def on_download(download):
            dest = out / (download.suggested_filename or "download")
            try:
                download.save_as(str(dest))
                downloads.append(
                    {"file": dest.name, "bytes": dest.stat().st_size, "url": download.url}
                )
                print(f"  captured download: {dest.name} ({dest.stat().st_size} bytes)")
            except Exception as exc:  # noqa: BLE001 - report, never abort the person's session
                downloads.append({"file": download.suggested_filename, "error": str(exc)})

        def wire(page):
            page.on("download", on_download)
            page.on("framenavigated", lambda f: actions.append(
                {"kind": "navigate", "url": f.url, "t": int(time.time() * 1000)}
            ) if f == page.main_frame else None)

        context.on("page", wire)
        page = context.pages[0] if context.pages else context.new_page()
        wire(page)
        page.goto(url)

        # Wait for the person to finish. Actions already stream in through the binding above, so
        # nothing is being detected here - this only watches for the window closing, which the
        # sync client exposes no push API for. The half-second is a poll INTERVAL on a real signal
        # (`context.pages` going empty), never a duration anything is concluded from, and there is
        # deliberately no timeout: the person takes as long as they take.
        try:
            while context.pages:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nstopping on Ctrl-C")
        finally:
            if not args.no_trace:
                try:
                    context.tracing.stop(path=str(out / "trace.zip"))
                except Exception:  # noqa: BLE001
                    pass
            try:
                context.close()
            except Exception:  # noqa: BLE001
                pass

    payload = {
        "label": label,
        "vendor": args.vendor,
        "mpn": args.mpn,
        "start_url": url,
        "actions": actions,
        "downloads": downloads,
    }
    (out / "actions.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print()
    print(f"recorded {len(actions)} actions and {len(downloads)} download(s)")
    print(f"  {out / 'actions.json'}")
    if not args.no_trace and (out / "trace.zip").exists():
        print(f"  {out / 'trace.zip'}   (view: uv run python -m playwright show-trace <path>)")
    print("Your sign-in / wall clearance stays in the profile for automated runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
