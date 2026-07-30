from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageChops
from PIL.IcoImagePlugin import IcoImageFile

from packaging.brand_assets import (
    FRONTEND_FAVICON,
    GRAPHITE,
    ICON_SIZES,
    LEFT_FACE,
    PAPER,
    RIGHT_FACE,
    SOURCE_ICON,
    TOP_FACE,
    render_ico_bytes,
    render_png,
)


def test_tracked_icon_is_the_deterministic_brand_asset() -> None:
    first = render_ico_bytes()
    second = render_ico_bytes()

    assert first == second
    assert SOURCE_ICON.read_bytes() == first
    assert FRONTEND_FAVICON.read_bytes() == first
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_icon_contains_every_windows_size_and_uses_only_grayscale() -> None:
    payload = render_ico_bytes()
    with Image.open(io.BytesIO(payload)) as icon:
        assert isinstance(icon, IcoImageFile)
        assert icon.ico.sizes() == {(size, size) for size in ICON_SIZES}

        for size in ICON_SIZES:
            frame = icon.ico.getimage((size, size)).convert("RGBA")
            assert frame.size == (size, size)
            assert ImageChops.difference(frame, render_png(size)).getbbox() is None
            red, green, blue, alpha = frame.split()
            midpoint = size // 2
            assert alpha.crop((0, 0, 1, 1)).getbbox() is None
            assert alpha.crop((midpoint, midpoint, midpoint + 1, midpoint + 1)).getbbox()
            assert ImageChops.difference(red, green).getbbox() is None
            assert ImageChops.difference(green, blue).getbbox() is None


def test_brand_palette_is_grayscale_with_distinct_cube_planes() -> None:
    assert GRAPHITE[0] < RIGHT_FACE[0] < LEFT_FACE[0] < TOP_FACE[0] < PAPER[0]
    for color in (GRAPHITE, RIGHT_FACE, LEFT_FACE, TOP_FACE, PAPER):
        assert color[0] == color[1] == color[2]
