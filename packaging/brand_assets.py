from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ICON = REPOSITORY_ROOT / "app/backend/stockroom/host/assets/stockroom.ico"

MASTER_SIZE = 1024
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

TRANSPARENT = (0, 0, 0, 0)
GRAPHITE = (43, 43, 43, 255)
PAPER = (242, 242, 242, 255)
ACTIVE_PAD = (164, 164, 164, 255)

# Nine component pads form an isometric 1-2-3-2-1 field. It reads as a
# land-pattern, one organized package, and a compact inventory without relying
# on letters or literal warehouse imagery.
PAD_CENTERS = (
    (128, 55),
    (91, 87),
    (165, 87),
    (54, 119),
    (128, 119),
    (202, 119),
    (91, 151),
    (165, 151),
    (128, 183),
)


def _scaled(value: float) -> int:
    return round(value * MASTER_SIZE / 256)


def _render_pad(color: tuple[int, int, int, int]) -> Image.Image:
    width = _scaled(28)
    height = _scaled(18)
    radius = _scaled(6)
    pad = Image.new("RGBA", (width, height), TRANSPARENT)
    ImageDraw.Draw(pad).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=radius,
        fill=color,
    )
    return pad.rotate(
        30,
        resample=Image.Resampling.BICUBIC,
        expand=True,
    )


def render_master() -> Image.Image:
    image = Image.new("RGBA", (MASTER_SIZE, MASTER_SIZE), TRANSPARENT)
    ImageDraw.Draw(image).rounded_rectangle(
        (
            _scaled(10),
            _scaled(10),
            MASTER_SIZE - _scaled(10) - 1,
            MASTER_SIZE - _scaled(10) - 1,
        ),
        radius=_scaled(48),
        fill=GRAPHITE,
    )

    paper_pad = _render_pad(PAPER)
    active_pad = _render_pad(ACTIVE_PAD)
    for index, (center_x, center_y) in enumerate(PAD_CENTERS):
        pad = active_pad if index == 4 else paper_pad
        image.alpha_composite(
            pad,
            (
                _scaled(center_x) - pad.width // 2,
                _scaled(center_y) - pad.height // 2,
            ),
        )
    return image


def render_png(size: int) -> Image.Image:
    if size <= 0:
        raise ValueError("size must be positive")
    rendered = render_master().resize((size, size), Image.Resampling.LANCZOS)
    red, green, blue, alpha = rendered.split()
    # Lanczos can ring a nominally transparent corner up to alpha 1-3. Clamp
    # that invisible fringe so Windows never paints a faint square halo.
    alpha = alpha.point(lambda value: 0 if value < 4 else value)
    return Image.merge("RGBA", (red, green, blue, alpha))


def render_ico_bytes() -> bytes:
    output = io.BytesIO()
    frames = [render_png(size) for size in ICON_SIZES]
    frames[-1].save(
        output,
        format="ICO",
        sizes=[(size, size) for size in ICON_SIZES],
        append_images=frames[:-1],
        bitmap_format="png",
    )
    return output.getvalue()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_icon() -> None:
    payload = render_ico_bytes()
    SOURCE_ICON.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_ICON.write_bytes(payload)
    print(f"Wrote {SOURCE_ICON} ({len(payload)} bytes, sha256:{_sha256(payload)})")


def _check_icon() -> None:
    expected = render_ico_bytes()
    if not SOURCE_ICON.is_file():
        raise SystemExit(f"Missing generated icon: {SOURCE_ICON}")
    actual = SOURCE_ICON.read_bytes()
    if actual != expected:
        raise SystemExit(
            "Generated Stockroom icon is stale: "
            f"expected sha256:{_sha256(expected)}, actual sha256:{_sha256(actual)}. "
            "Run `uv run python packaging/brand_assets.py --write`."
        )
    print(f"Stockroom icon is current (sha256:{_sha256(actual)})")


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
