#!/usr/bin/env python3
"""Render a JS page in a real browser and print its TEXT. Research tooling, not app code.

WHY THIS EXISTS. Half the vendor pages that matter to this project - Nexar's plan comparison,
Component Search Engine's results, Octopart's API reference - are client-rendered or bot-guarded,
so `curl`/WebFetch return an empty shell or a 403. Reading those shells produced three separate
wrong conclusions in one session on 2026-07-27, including a coverage probe that could not tell a
real part number from `ZZZNOTAREALPART123` because it was grepping a shell both times.

The global rule this serves: *go to the DATA LAYER, never the rendered surface* - and when the data
only exists after JS runs, a real browser IS the data layer. Playwright is already a dependency
(`scripts/uishot.py` drives it for screenshots), so this adds no new one.

Usage:
    uv run python scripts/webread.py <url> [--grep TERM ...] [--context N] [--wait MS] [--dump]

    --grep    print only windows around each TERM (repeatable, case-insensitive)
    --context characters of surrounding text per hit (default 240)
    --wait    extra settle time after DOMContentLoaded, ms (default 6000)
    --dump    print the whole extracted text instead of windows
    --links   also print every href whose text or target matches a --grep TERM

Prints the final URL and character count first, so an empty body is OBVIOUS rather than silently
read as "the page says nothing" - which is exactly how a shell gets mistaken for content.
"""
from __future__ import annotations

import argparse
import re
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url")
    ap.add_argument("--grep", action="append", default=[], metavar="TERM")
    ap.add_argument("--context", type=int, default=240)
    ap.add_argument("--wait", type=int, default=6000)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--links", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed in this environment", file=sys.stderr)
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(args.wait)
            text = re.sub(r"\n{2,}", "\n", page.inner_text("body"))
            # The header is the honesty check: 0 chars means a shell or a block, and saying so
            # up front stops an empty read being reported as an absence of content.
            print(f"url: {page.url}")
            print(f"title: {page.title()}")
            print(f"chars: {len(text)}")
            if not text.strip():
                print("EMPTY BODY - this is a shell or a block, NOT evidence that the page is blank")

            if args.links:
                for a in page.query_selector_all("a"):
                    href = a.get_attribute("href") or ""
                    label = (a.inner_text() or "").strip()
                    hay = f"{href} {label}".lower()
                    if any(t.lower() in hay for t in args.grep):
                        print(f"LINK  {label[:50]!r} -> {href}")

            if args.dump or not args.grep:
                print(text if args.dump else text[:4000])
            else:
                for term in args.grep:
                    hits = list(re.finditer(re.escape(term), text, re.I))
                    print(f"\n=== {term!r}: {len(hits)} hit(s) ===")
                    for m in hits[:6]:
                        start = max(0, m.start() - args.context)
                        print(f"...{text[start:m.start() + args.context]}...\n")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
