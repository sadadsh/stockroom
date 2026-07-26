"""The pure logic in `scripts/wingui.py`: monitor bounds and path conversion.

The PowerShell half needs a real Windows desktop and is exercised by hand. What is worth pinning
here is the PARSING, because a monitor origin this code guesses rather than reads is exactly the bug
that drove the pointer off every display and clicked nothing while reporting success.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "wingui", Path(__file__).resolve().parents[2] / "scripts" / "wingui.py"
)
wingui = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(wingui)

_LISTING = (
    "SCREEN \\\\.\\DISPLAY1 {X=0,Y=0,Width=1920,Height=1080}\n"
    "SCREEN \\\\.\\DISPLAY2 {X=-1920,Y=0,Width=1920,Height=1080}\n"
    "WINDOW 5901142 'Home Page - Altium Designer Professional (26.8.1)'\n"
)


def test_a_negative_monitor_origin_is_READ_not_assumed():
    """The whole point. This machine's second display starts at x = -1920, so anything assuming
    monitors begin at 0 aims the pointer at a coordinate that does not exist."""
    screens = wingui.parse_screens(_LISTING)
    assert len(screens) == 2
    assert screens[0] == {"X": 0, "Y": 0, "Width": 1920, "Height": 1080}
    assert screens[1]["X"] == -1920


def test_window_lines_and_malformed_bounds_are_ignored():
    """A WINDOW line sits in the same output; parsing it as a screen would invent a monitor."""
    assert wingui.parse_screens("WINDOW 1 'x'\nnonsense\n") == []
    assert wingui.parse_screens("SCREEN broken {X=a,Y=0}") == []


def test_an_already_windows_path_is_left_alone():
    """`wslpath -w` mangles a path that is already Windows-shaped, and callers pass either form."""
    assert wingui.to_windows_path("C:\\srplace\\x.png") == "C:\\srplace\\x.png"
