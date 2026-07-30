from __future__ import annotations

import argparse
import hashlib
import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = REPOSITORY_ROOT / "app/backend/stockroom/host/assets/stockroom.ico"
FRONTEND_FAVICON = REPOSITORY_ROOT / "app/frontend/public/favicon.ico"

ICON_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256)
SHELL_TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 44, 48, 60, 64, 72, 80, 96, 256)

TRANSPARENT = (0, 0, 0, 0)
GRAPHITE = (24, 24, 24, 255)
PAPER = (242, 242, 242, 255)
TOP_FACE = (72, 72, 72, 255)
LEFT_FACE = (50, 50, 50, 255)
RIGHT_FACE = (36, 36, 36, 255)
LIGHT_TOP_FACE = (246, 246, 246, 255)
LIGHT_LEFT_FACE = (224, 224, 224, 255)
LIGHT_RIGHT_FACE = (198, 198, 198, 255)

TOP = (24.0, 6.5)
RIGHT = (40.0, 15.8)
MID = (24.0, 25.1)
LEFT = (8.0, 15.8)
BOTTOM = (24.0, 41.5)
LEFT_BOTTOM = (8.0, 32.2)
RIGHT_BOTTOM = (40.0, 32.2)


def _scale_points(
    points: tuple[tuple[float, float], ...],
    scale: float,
) -> list[tuple[int, int]]:
    return [(round(x * scale), round(y * scale)) for x, y in points]


def _panel_joint() -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for index in range(97):
        progress = index / 96
        x = 24 - 7.0 * math.sin(2 * math.pi * progress) * math.sin(
            math.pi * progress
        )
        y = TOP[1] + (MID[1] - TOP[1]) * progress
        points.append((x, y))
    points.extend((MID, BOTTOM))
    return tuple(points)


def render_png(size: int, *, variant: str = "tile") -> Image.Image:
    if size <= 0:
        raise ValueError("size must be positive")
    if variant not in {"tile", "unplated-dark", "unplated-light"}:
        raise ValueError("variant must be tile, unplated-dark, or unplated-light")

    supersample = max(8, math.ceil(size * 8 / 48))
    scale = supersample
    image = Image.new("RGBA", (48 * scale, 48 * scale), TRANSPARENT)
    draw = ImageDraw.Draw(image)

    if variant == "tile":
        draw.rounded_rectangle(
            (2 * scale, 2 * scale, 46 * scale - 1, 46 * scale - 1),
            radius=10 * scale,
            fill=GRAPHITE,
        )
        edge = PAPER
        top_face, left_face, right_face = TOP_FACE, LEFT_FACE, RIGHT_FACE
    elif variant == "unplated-dark":
        edge = PAPER
        top_face, left_face, right_face = TOP_FACE, LEFT_FACE, RIGHT_FACE
    else:
        edge = GRAPHITE
        top_face = LIGHT_TOP_FACE
        left_face = LIGHT_LEFT_FACE
        right_face = LIGHT_RIGHT_FACE

    draw.polygon(_scale_points((TOP, RIGHT, MID, LEFT), scale), fill=top_face)
    draw.polygon(
        _scale_points((LEFT, MID, BOTTOM, LEFT_BOTTOM), scale),
        fill=left_face,
    )
    draw.polygon(
        _scale_points((MID, RIGHT, RIGHT_BOTTOM, BOTTOM), scale),
        fill=right_face,
    )

    edge_width = max(1, round(2.25 * scale))
    for path in (
        (TOP, LEFT, LEFT_BOTTOM, BOTTOM, RIGHT_BOTTOM, RIGHT, TOP),
        (LEFT, MID, RIGHT),
        _panel_joint(),
    ):
        draw.line(
            _scale_points(path, scale),
            fill=edge,
            width=edge_width,
            joint="curve",
        )

    radius = edge_width / 2
    for x, y in (TOP, MID, BOTTOM):
        center_x = x * scale
        center_y = y * scale
        draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=edge,
        )

    rendered = image.resize((size, size), Image.Resampling.LANCZOS)
    red, green, blue, alpha = rendered.split()
    alpha = alpha.point(lambda value: 0 if value < 4 else value)
    return Image.merge("RGBA", (red, green, blue, alpha))


def render_png_bytes(size: int, *, variant: str = "tile") -> bytes:
    output = io.BytesIO()
    render_png(size, variant=variant).save(
        output,
        format="PNG",
        compress_level=9,
        optimize=False,
    )
    return output.getvalue()


def render_ico_bytes() -> bytes:
    payloads = tuple(render_png_bytes(size) for size in ICON_SIZES)
    directory_size = 6 + 16 * len(payloads)
    offset = directory_size
    entries: list[bytes] = []
    for size, payload in zip(ICON_SIZES, payloads, strict=True):
        encoded_size = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                encoded_size,
                encoded_size,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)
    return b"".join(
        (
            struct.pack("<HHH", 0, 1, len(payloads)),
            *entries,
            *payloads,
        )
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_icon() -> None:
    payload = render_ico_bytes()
    for target in (SOURCE_ICON, FRONTEND_FAVICON):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        print(f"Wrote {target} ({len(payload)} bytes, sha256:{_sha256(payload)})")


def _check_icon() -> None:
    expected = render_ico_bytes()
    for target in (SOURCE_ICON, FRONTEND_FAVICON):
        if not target.is_file():
            raise SystemExit(f"Missing generated icon: {target}")
        actual = target.read_bytes()
        if actual != expected:
            raise SystemExit(
                "Generated Stockroom icon is stale: "
                f"{target} expected sha256:{_sha256(expected)}, "
                f"actual sha256:{_sha256(actual)}. "
                "Run `uv run python packaging/brand_assets.py --write`."
            )
        print(f"Stockroom icon is current: {target} (sha256:{_sha256(actual)})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or verify Stockroom's deterministic Windows icon."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="write the tracked ICO")
    action.add_argument("--check", action="store_true", help="verify the tracked ICO")
    arguments = parser.parse_args()

    if arguments.write:
        _write_icon()
    else:
        _check_icon()


if __name__ == "__main__":
    main()
