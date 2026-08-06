#!/usr/bin/env python3
"""Prove two frontend bundles draw the same pixels, for the layout-as-data parity gate.

WHY THIS EXISTS
---------------
Phase 1 of the Design Mode plan replaces the opened component's hardcoded JSX arrangement
with a renderer walking a layout document, under a gate of ZERO visual change. The Phase 0
baseline audit established that the committed `app/frontend-dist` and a fresh build differ
in version-bearing bytes (`__APP_VERSION__` bakes the git SHA), so comparing a fresh build
of the NEW renderer against shots of the OLD committed bundle would compare two build
pipelines as well as two renderers. The honest comparison builds BOTH renderers with the
same pipeline to scratch directories and photographs both through the same harness:

    uv run python scripts/design_parity.py shoot --dist <scratch-dist> --out <dir> \
        --select "AAA Vendor Data Probe" --width 1366 --height 768
    uv run python scripts/design_parity.py compare --a build/parity/old --b build/parity/new

`shoot` substitutes the given dist for the committed one by patching the ONE module-level
constant the backend reads (`stockroom.api.app._FRONTEND_DIST`) before the app boots, then
delegates every capture decision to `scripts/uishot.py` unchanged - same seed, same waits,
same probe - so the two sides differ in nothing but the bundle under test. The committed
`app/frontend-dist` is never written.

`compare` is hash-first: byte-identical pairs pass without decoding. A differing pair is
decoded (Pillow, already a dev dependency) and judged per pixel with an antialiasing
tolerance: a pixel counts as CHANGED only when some channel moves by more than `--aa-tol`
(default 0: any difference fails until a measured reason says otherwise - the Phase 0
determinism check proved byte-identical captures across independent boots, so tolerance is
a concession this gate should not start by making). Exit is non-zero on any changed pixel,
and every failing pair reports its changed-pixel count, worst channel delta, and bounding
box so the diff is a finding rather than a feeling.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shoot(args: argparse.Namespace) -> int:
    dist = Path(args.dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        print(f"not a built frontend dist (no index.html): {dist}")
        return 2

    # The backend package must be importable BEFORE the patch, exactly as uishot.run arranges
    # for itself; doing it here first means the patched module object is the one uishot's own
    # deferred imports resolve. `_FRONTEND_DIST` is read at call time by both the StaticFiles
    # mount (api/app.py) and the token-injecting index route (host/run.py), so one assignment
    # redirects the whole served bundle.
    sys.path.insert(0, str(REPO / "app" / "backend"))
    import stockroom.api.app as api_app

    api_app._FRONTEND_DIST = dist
    print(f"serving frontend from {dist}")

    sys.path.insert(0, str(REPO / "scripts"))
    import uishot

    return uishot.run(
        argparse.Namespace(
            click=[],
            surface=args.surface,
            fill=[],
            hover=[],
            select=args.select,
            measure=[],
            seed=True,  # ALWAYS the deterministic seeded library: parity is only meaningful
            # against identical data, and the seed is how Phase 0's hashes were reproducible.
            themes=args.themes,
            width=args.width,
            height=args.height,
            scale=args.scale,
            full_page=False,
            out=args.out,
            library=str(REPO / "libraries"),
        )
    )


def compare(args: argparse.Namespace) -> int:
    a_root, b_root = Path(args.a).resolve(), Path(args.b).resolve()
    a_files = sorted(p for p in a_root.rglob("*.png"))
    if not a_files:
        print(f"no PNGs under {a_root}")
        return 2
    failures: list[str] = []
    report: list[dict[str, object]] = []
    for a_path in a_files:
        rel = a_path.relative_to(a_root)
        b_path = b_root / rel
        if not b_path.is_file():
            failures.append(f"{rel}: missing on the B side")
            continue
        a_hash, b_hash = _sha256(a_path), _sha256(b_path)
        entry: dict[str, object] = {"pair": str(rel), "aSha256": a_hash, "bSha256": b_hash}
        if a_hash == b_hash:
            entry["verdict"] = "byte-identical"
            print(f"  ok  {rel}  byte-identical")
        else:
            # Decode and judge per pixel. Only a channel delta beyond the antialiasing
            # tolerance counts as a change; at the default tolerance of 0 this is simply
            # "any differing pixel", which is the gate Phase 0's determinism results earn.
            from PIL import Image, ImageChops

            with Image.open(a_path) as ia, Image.open(b_path) as ib:
                a_img, b_img = ia.convert("RGBA"), ib.convert("RGBA")
                if a_img.size != b_img.size:
                    entry["verdict"] = f"size mismatch {a_img.size} vs {b_img.size}"
                    failures.append(f"{rel}: {entry['verdict']}")
                    report.append(entry)
                    continue
                diff = ImageChops.difference(a_img, b_img)
                extrema = diff.getextrema()
                worst = max(hi for _lo, hi in extrema)
                mask = diff.point(lambda v: 255 if v > args.aa_tol else 0).convert("L")
                bbox = mask.getbbox()
                changed = sum(1 for v in mask.getdata() if v)
            entry.update(
                {"worstChannelDelta": worst, "changedPixels": changed, "boundingBox": bbox}
            )
            if changed == 0:
                entry["verdict"] = f"within antialiasing tolerance {args.aa_tol}"
                print(f"  ok  {rel}  hash differs, 0 px beyond tol {args.aa_tol} (worst delta {worst})")
            else:
                entry["verdict"] = "CHANGED"
                failures.append(
                    f"{rel}: {changed} px changed beyond tol {args.aa_tol}, "
                    f"worst channel delta {worst}, bbox {bbox}"
                )
                print(f"  !!  {rel}  {failures[-1]}")
        report.append(entry)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"report -> {args.report}")
    if failures:
        print("PARITY FAILED:")
        for line in failures:
            print(f"  {line}")
        return 1
    print(f"parity ok: {len(report)} pairs")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sh = sub.add_parser("shoot", help="capture through uishot with a substituted frontend dist")
    sh.add_argument("--dist", required=True, help="built frontend dist directory to serve")
    sh.add_argument("--out", required=True)
    sh.add_argument("--surface", default="components")
    sh.add_argument("--select", default="")
    sh.add_argument("--themes", default="dark,light")
    sh.add_argument("--width", type=int, default=1600)
    sh.add_argument("--height", type=int, default=1000)
    sh.add_argument("--scale", type=int, default=2)
    sh.set_defaults(func=shoot)
    cp = sub.add_parser("compare", help="hash-first pixel comparison of two shot directories")
    cp.add_argument("--a", required=True, help="side A root (the OLD renderer's shots)")
    cp.add_argument("--b", required=True, help="side B root (the NEW renderer's shots)")
    cp.add_argument("--aa-tol", type=int, default=0, help="max channel delta that is not a change")
    cp.add_argument("--report", default="", help="write the per-pair JSON verdicts here")
    cp.set_defaults(func=compare)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
