"""The main window must declare a MINIMUM SIZE.

MEASURED in the real WebView2 window on Windows (2026-07-25) by driving the actual OS window
through `MoveWindow` across five widths: the sheet degrades cleanly from 1600 down to a 884px
viewport (three columns -> two -> one, no overflow anywhere), and GARBLES at 744px, where eight
elements overflow horizontally (`detail.root`, `detail.title`, `detail.identity`, both asset tiles,
`detail.specs`, `detail.spec-group`, `components.detail-pane`).

The cause is structural, not a styling bug: the rail (190px) and the picker (320px) are FIXED, so
below roughly a 900px viewport the detail pane is squeezed under 200px and there is no layout that
can rescue it. A responsive rule cannot fix a pane that has no room left; the window simply must not
be allowed to get that small. pywebview takes `min_size` and nothing was passing it.

The floor is set from the measurement, not guessed: 884px was still clean, 744px was not.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_webview(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A stand-in pywebview, since it is Windows-only and `run_window` imports it lazily."""
    mod = types.ModuleType("webview")
    mod.settings = {}
    mod.create_window = MagicMock(return_value=MagicMock())
    mod.start = MagicMock()
    monkeypatch.setitem(sys.modules, "webview", mod)
    return mod


def test_main_window_declares_a_minimum_size(fake_webview, monkeypatch, tmp_path):
    from stockroom.host import window as W

    monkeypatch.setattr(W, "_install_capture_logfile", lambda: None, raising=False)
    monkeypatch.setattr(
        "stockroom.store.machine_config.config_dir", lambda: tmp_path, raising=False
    )

    W.run_window("http://127.0.0.1:1234/", "tok")

    assert fake_webview.create_window.called, "the main window was never created"
    kwargs = fake_webview.create_window.call_args.kwargs
    min_size = kwargs.get("min_size")
    assert min_size is not None, "the main window passes no min_size, so it can be dragged to a width that garbles the sheet"
    width, height = min_size
    # 884px viewport was measured CLEAN and 744px measured BROKEN, so the floor must sit above the
    # broken width. Asserting a range rather than an exact pair keeps this a behaviour test.
    assert 880 <= width <= 1024, f"min width {width} does not match the measured safe floor"
    assert height >= 560, f"min height {height} is below a usable sheet"
