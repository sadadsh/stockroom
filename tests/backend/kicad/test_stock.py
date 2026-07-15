"""Locating files in the installed KiCad stock libraries (for passive previews)."""

from __future__ import annotations

import pytest

from stockroom.kicad.stock import (
    find_kicad_share_dir,
    stock_footprint_file,
    stock_model_file,
    stock_symbol_lib_file,
)

_HAS_KICAD = find_kicad_share_dir() is not None
_needs_kicad = pytest.mark.skipif(not _HAS_KICAD, reason="KiCad stock libraries not installed")


def test_missing_lib_resolves_to_none_never_raises():
    # With an explicit share dir that has no such lib, every resolver returns None.
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        share = Path(td)
        assert stock_symbol_lib_file("Device", share=share) is None
        assert stock_footprint_file("Resistor_SMD", "R_0603_1608Metric", share=share) is None
        assert stock_model_file("Resistor_SMD", "R_0603_1608Metric", share=share) is None


@_needs_kicad
def test_resolves_the_real_stock_resistor_assets():
    assert stock_symbol_lib_file("Device") is not None
    fp = stock_footprint_file("Resistor_SMD", "R_0603_1608Metric")
    assert fp is not None and fp.is_file() and fp.name == "R_0603_1608Metric.kicad_mod"
    model = stock_model_file("Resistor_SMD", "R_0603_1608Metric")
    assert model is not None and model.suffix.lower() in {".wrl", ".step", ".stp"}
