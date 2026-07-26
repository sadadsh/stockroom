#!/usr/bin/env python3
"""Measure what a screenshot ACTUALLY contains, instead of judging it by eye.

The standing rule for this repo is that every screenshot gets a ruthless element-by-element
critique, and that a claim about a render is backed by a measured value rather than an
impression. Three questions come up on every visual slice:

  * what colours are really in this region, and in what proportion?
  * how much of a tile is INK versus empty background? (a preview that "looks broken" is
    usually a coverage number, and 2.9% versus 7.3% settles it in one line)
  * is a specific colour present AT ALL? (the load-bearing question when a fix is meant to
    put a material on screen that was previously absent entirely - a dominant-colour list
    misses it precisely when it covers a small area, which is when it matters most)

Every visual session was re-typing a throwaway Pillow snippet to answer them, so this is
that snippet with a real CLI. It reads PNGs; it never writes to the app or the library.

PRIOR ART evaluated before writing this, per the "bring in what already works" rule:
  * **ImageMagick** (`magick shot.png -crop WxH+X+Y +dither -colors N -define
    histogram:unique-colors=true -format %c histogram:info:`) genuinely does the
    dominant-colour half, and does it well. REJECTED as the whole answer: it adds a
    non-Python system binary to a repo whose tooling is uv-managed Python, its histogram
    output has to be regex-parsed back into numbers to be asserted on, and it has no notion
    of either question that actually decides things here - ink-versus-background COVERAGE of
    a tile, and the WCAG CONTRAST RATIO between two regions (the design contract states its
    minimums as ratios, and "-c-stage measures 1.12:1" is the finding, not "looks faint").
  * **dominant_colours** (alexwlchan, Rust/k-means) and **colorscore** (quadule, Ruby +
    ImageMagick + CIE2000). REJECTED: both answer "what are this image's representative
    colours" via k-means, which is the wrong question. k-means INVENTS cluster centres, so a
    material covering 0.1% of the frame is averaged out of existence - and that 0.1% is
    exactly the pixel evidence a fix landed. Exact-colour presence with a tolerance is what
    is needed, not clustering.
  * **pixelmatch / odiff / Playwright `toHaveScreenshot`**. REJECTED for this purpose: they
    are DIFF tools that answer "did this change against a baseline". Useful, and orthogonal -
    they cannot say what a colour IS, only that two images disagree.
So: Pillow (already a dev dependency) plus ~60 lines, rather than a system binary plus a
parser, and it answers the coverage and contrast questions none of the above do.

Examples
--------
Coverage and dominant colours of two named regions::

    uv run python scripts/pixelprobe.py build/shots/components-dark-1600w.png \\
        --region "3d stage=1075,200,1605,1165" --region "footprint=1352,1368,1607,1590"

Ask whether a specific colour reached the screen (a STEP material, a token value)::

    uv run python scripts/pixelprobe.py shot.png --region "body=1120,600,1500,900" \\
        --match 255,87,59 --match 183,183,183 --tol 60

Contrast between two regions, for the "is this stage visible in light theme" class of
question, which is a RATIO and must never be judged by eye::

    uv run python scripts/pixelprobe.py shot.png --contrast 100,100,140,140 --contrast 200,200,240,240
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# A pixel counts as INK when it differs from the region's own background by more than this on
# any channel. Anti-aliasing and a subtle gradient both sit under it; real drawn content does
# not. Deliberately not zero: a compression halo would otherwise report a blank tile as full.
INK_DELTA = 10


def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG relative-luminance contrast ratio. The design contract states its minimums as
    ratios, so the check has to produce a ratio; "it looks visible on my monitor" is a
    different statement and is not checkable."""
    lo, hi = sorted((relative_luminance(a), relative_luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


def parse_region(spec: str, size: tuple[int, int]) -> tuple[str, tuple[int, int, int, int]]:
    """`name=x0,y0,x1,y1`, or a bare `x0,y0,x1,y1`. Coordinates are ORIGINAL image pixels.

    A region falling outside the image is an ERROR rather than a silent clamp: a clamped
    region measures something other than what was asked for and still returns a confident
    number, which is the failure mode this whole script exists to remove."""
    name, _, body = spec.rpartition("=")
    try:
        x0, y0, x1, y1 = (int(v) for v in body.split(","))
    except ValueError:
        raise SystemExit(f"bad region {spec!r}: want [name=]x0,y0,x1,y1") from None
    if x0 >= x1 or y0 >= y1:
        raise SystemExit(f"bad region {spec!r}: x0,y0 must be above and left of x1,y1")
    w, h = size
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        raise SystemExit(f"region {spec!r} falls outside the {w}x{h} image")
    return (name or body), (x0, y0, x1, y1)


def quantise(px: tuple[int, int, int], step: int) -> tuple[int, int, int]:
    """Round a colour into a bucket so a lit gradient reads as one cluster. Rounding, NOT
    k-means: a bucket is a fixed grid, so a rare colour keeps its own bucket instead of being
    absorbed into a bigger neighbour's centroid."""
    return tuple(min(255, round(v / step) * step) for v in px)  # type: ignore[return-value]


def describe(pixels: list[tuple[int, int, int]], step: int, top: int) -> dict:
    background = Counter(pixels).most_common(1)[0][0]
    ink = [p for p in pixels if max(abs(p[i] - background[i]) for i in range(3)) > INK_DELTA]
    clusters = Counter(quantise(p, step) for p in ink)
    return {
        "background": background,
        "ink": len(ink),
        "total": len(pixels),
        "clusters": clusters.most_common(top),
    }


def luma(rgb: tuple[int, int, int]) -> float:
    """Perceived brightness (Rec. 709). One number, so two regions can be ORDERED rather than
    compared channel by channel - which is what "is this darker" actually means."""
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def mean_colour(pixels: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    n = len(pixels)
    return tuple(round(sum(p[i] for p in pixels) / n) for i in range(3))  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure colours, ink coverage and contrast in a screenshot.",
    )
    ap.add_argument("image", type=Path, help="PNG to measure")
    ap.add_argument(
        "--region",
        action="append",
        default=[],
        metavar="[NAME=]X0,Y0,X1,Y1",
        help="a region to describe; repeatable. Defaults to the whole image.",
    )
    ap.add_argument(
        "--match",
        action="append",
        default=[],
        metavar="R,G,B",
        help="report how many pixels sit within --tol of this colour; repeatable. Use it to "
        "assert a colour REACHED the screen; a dominant-colour list misses a small area.",
    )
    ap.add_argument("--tol", type=int, default=40, help="euclidean tolerance for --match (40)")
    ap.add_argument("--step", type=int, default=18, help="colour cluster width (18)")
    ap.add_argument("--top", type=int, default=8, help="how many clusters to list (8)")
    ap.add_argument(
        "--contrast",
        action="append",
        default=[],
        metavar="X0,Y0,X1,Y1",
        help="mean colour of a region; give exactly two to get their WCAG ratio",
    )
    args = ap.parse_args(argv)

    try:
        from PIL import Image
    except ImportError:
        print(
            "pixelprobe needs Pillow: run `uv sync` (it is a dev dependency), or "
            "`uv run --with pillow python scripts/pixelprobe.py ...`",
            file=sys.stderr,
        )
        return 2

    if not args.image.exists():
        print(f"no such image: {args.image}", file=sys.stderr)
        return 2
    im = Image.open(args.image).convert("RGB")
    print(f"{args.image}  {im.size[0]}x{im.size[1]}")

    wanted: list[tuple[int, int, int]] = []
    for spec in args.match:
        try:
            r, g, b = (int(v) for v in spec.split(","))
        except ValueError:
            raise SystemExit(f"bad --match {spec!r}: want R,G,B") from None
        wanted.append((r, g, b))

    for spec in args.region or [f"whole image=0,0,{im.size[0]},{im.size[1]}"]:
        name, box = parse_region(spec, im.size)
        pixels = list(im.crop(box).getdata())
        info = describe(pixels, args.step, args.top)
        w, h = box[2] - box[0], box[3] - box[1]
        print(f"\n== {name}  ({w}x{h} = {info['total']} px)")
        # The MEAN colour of the whole region, reported always. It is the question every
        # lighting / shading change actually asks - "is this area darker than that one" - and it
        # was being answered by a hand-written Pillow loop each time, three times in one session.
        # A dominant-colour list cannot answer it: clustering reports the most COMMON colour, while
        # a shading gradient is a change in the AVERAGE that may have no repeated value at all.
        print(f"   mean       rgb{mean_colour(pixels)}  (luma {luma(mean_colour(pixels)):.1f})")
        print(f"   background rgb{info['background']}")
        print(f"   ink        {info['ink']} px = {100 * info['ink'] / info['total']:.2f}% of region")
        for colour, n in info["clusters"]:
            print(f"     ~rgb{colour}  {100 * n / max(info['ink'], 1):5.1f}% of ink")
        for want in wanted:
            hits = [
                p for p in pixels if sum((p[i] - want[i]) ** 2 for i in range(3)) <= args.tol**2
            ]
            example = f"  e.g. rgb{hits[0]}" if hits else ""
            print(
                f"     match rgb{want} +/-{args.tol}: "
                f"{'PRESENT' if hits else 'ABSENT '} {len(hits)} px{example}"
            )

    means = []
    for spec in args.contrast:
        _, box = parse_region(spec, im.size)
        avg = mean_colour(list(im.crop(box).getdata()))
        means.append(avg)
        print(f"\n== contrast sample {spec}: mean rgb{avg}")
    if len(means) == 2:
        print(f"   ratio {contrast_ratio(means[0], means[1]):.2f}:1")
    elif len(means) > 2:
        print("   (give exactly two --contrast regions to get a ratio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
