#!/usr/bin/env python3
"""Crop a region out of a screenshot, for reading a detail without re-reading the whole frame.

WHY THIS EXISTS. Reviewing a UI change means shooting it, then looking at ONE region - a header
band, a control bar, a spec list. Doing that inline is a `cp` plus a four-line PIL snippet, retyped
every time, and reading a full 2800x2000 frame to inspect a 300px control is the single most
expensive habit in a review session. This makes it one command with a real CLI.

It also accepts a WINDOWS path directly, because `windrive.py shot` writes to `C:\\srdrive\\...`
and the copy back across the boundary was the other half of the retyped step.

PRIOR ART, evaluated and rejected:
- `scripts/pixelprobe.py` (ours) MEASURES a region (colours, ink, contrast) but never writes one out
  to look at. Complementary: probe for numbers, this for eyes.
- `uishot.py --measure` reports boxes, not imagery.
- ImageMagick `convert -crop` would do it, but it is not a dependency here and would not know the
  Windows path convention or the upscale-for-legibility default that makes a 14px glyph readable.

Usage
-----
    uv run python scripts/shotcrop.py <png> --region 690,380,1050,800 -o out.png
    uv run python scripts/shotcrop.py 'C:\\srdrive\\screens\\x\\drive-1.png' --region ... --scale 2
    uv run python scripts/shotcrop.py <png> --grid          # print a coordinate grid to aim with
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from PIL import Image


def to_linux_path(raw: str) -> Path:
    """Accept a Windows path (C:\\... or \\\\?\\...) as well as a native one."""
    p = raw.strip().strip('"')
    if len(p) > 2 and p[1] == ":" and p[2] in "\\/":
        try:
            out = subprocess.run(["wslpath", "-u", p], capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                return Path(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
        # wslpath absent (native Windows): the path is already usable
        return Path(p)
    return Path(p)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", help="PNG to crop; a Windows path is accepted")
    ap.add_argument("--region", help="X0,Y0,X1,Y1 in image pixels")
    ap.add_argument("-o", "--out", help="where to write (default: alongside, named -crop)")
    ap.add_argument("--scale", type=float, default=0.0,
                    help="resize factor; default picks one so the crop lands near 900px wide, "
                         "because a 14px glyph is unreadable at 1:1 and misleading when upscaled "
                         "with NEAREST (pixelprobe's --zoom lesson)")
    ap.add_argument("--grid", action="store_true",
                    help="print a coordinate grid instead of cropping, to aim the next --region")
    args = ap.parse_args()

    src = to_linux_path(args.image)
    if not src.exists():
        print(f"not found: {src}", file=sys.stderr)
        return 2
    im = Image.open(src)
    print(f"{src.name}  {im.width}x{im.height}")

    if args.grid or not args.region:
        step_x, step_y = im.width // 8, im.height // 8
        print("  x:", ", ".join(str(i * step_x) for i in range(9)))
        print("  y:", ", ".join(str(i * step_y) for i in range(9)))
        if not args.region:
            print("  (pass --region X0,Y0,X1,Y1 to crop)")
            return 0

    try:
        x0, y0, x1, y1 = (int(v) for v in args.region.split(","))
    except ValueError:
        print("--region wants four integers: X0,Y0,X1,Y1", file=sys.stderr)
        return 2
    box = (max(0, x0), max(0, y0), min(im.width, x1), min(im.height, y1))
    if box[2] <= box[0] or box[3] <= box[1]:
        print(f"empty region after clamping to the image: {box}", file=sys.stderr)
        return 2

    crop = im.crop(box)
    scale = args.scale or max(1.0, min(3.0, 900 / max(1, crop.width)))
    if scale != 1.0:
        # LANCZOS, never NEAREST: nearest turns a couple of levels of ripple into hard bands that
        # are not in the artifact, which is how a 2-LSB gradient once got diagnosed as "rings".
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)

    out = Path(args.out) if args.out else src.with_name(f"{src.stem}-crop.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out)
    print(f"  crop {box} x{scale:.2f} -> {out}  ({crop.width}x{crop.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
