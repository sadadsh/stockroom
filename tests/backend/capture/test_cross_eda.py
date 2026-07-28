from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.capture.cross_eda import (
    CrossEdaVerificationError,
    read_altium_footprint,
    read_altium_symbol,
    read_kicad_symbol,
    verify_cross_eda_component,
    verify_kicad_component,
)
from stockroom.kicad.stock import find_kicad_share_dir
from stockroom.planning import ExactPartIdentity

ALTIUM_FIXTURES = Path(__file__).parents[1] / "altium" / "fixtures"


def _write_kicad_pair(
    root: Path,
    *,
    pad_offset: float = 2.14,
    duplicate_pin_names: bool = False,
) -> tuple[Path, Path]:
    symbol = root / "S1M.kicad_sym"
    footprint = root / "D_SMA.kicad_mod"
    second_name = "K" if duplicate_pin_names else "A"
    symbol.write_text(
        f"""(kicad_symbol_lib
  (version 20240101)
  (generator stockroom-test)
  (symbol "S1M"
    (property "Reference" "D" (at 0 0 0))
    (property "Value" "S1M" (at 0 0 0))
    (property "Footprint" "Test:D_SMA" (at 0 0 0))
    (property "Manufacturer" "ON Semiconductor" (at 0 0 0))
    (property "Manufacturer Part Number" "S1M" (at 0 0 0))
    (symbol "S1M_0_1"
      (pin passive line (at -5 0 0) (length 2.54)
        (name "K" (effects (font (size 1 1))))
        (number "1" (effects (font (size 1 1)))))
      (pin passive line (at 5 0 180) (length 2.54)
        (name "{second_name}" (effects (font (size 1 1))))
        (number "2" (effects (font (size 1 1))))))))
""",
        encoding="utf-8",
    )
    footprint.write_text(
        f"""(footprint "D_SMA"
  (version 20240108)
  (generator stockroom-test)
  (layer "F.Cu")
  (pad "1" smd rect (at {-pad_offset} 0) (size 2.33 1.56) (layers "F.Cu"))
  (pad "2" smd rect (at {pad_offset} 0) (size 2.33 1.56) (layers "F.Cu"))
  (model "${{KICAD10_3DMODEL_DIR}}/Diode_SMD.3dshapes/D_SMA.step"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))))
""",
        encoding="utf-8",
    )
    return symbol, footprint


def _system_step() -> Path:
    try:
        root = find_kicad_share_dir()
    except Exception as exc:
        pytest.skip(f"installed KiCad library is unavailable: {exc}")
    step = root / "3dmodels" / "Diode_SMD.3dshapes" / "D_SMA.step"
    if not step.is_file():
        pytest.skip("installed KiCad D_SMA STEP model is unavailable")
    return step


def test_native_altium_readback_observes_identity_pins_and_pad_geometry() -> None:
    symbol = read_altium_symbol(ALTIUM_FIXTURES / "sample.SchLib", "S1M")
    footprint = read_altium_footprint(ALTIUM_FIXTURES / "sample.PcbLib", "S1M")

    assert (symbol.manufacturer, symbol.mpn) == ("ON Semiconductor", "S1M")
    assert [(pin.number, pin.name) for pin in symbol.pins] == [("A", "A"), ("C", "K")]
    assert [(pad.number, round(pad.x_mm, 2)) for pad in footprint.pads] == [
        ("C", -2.14),
        ("A", 2.14),
    ]
    assert all(round(pad.width_mm, 2) == 2.33 for pad in footprint.pads)
    assert all(round(pad.height_mm, 2) == 1.56 for pad in footprint.pads)


def test_cross_eda_readback_proves_real_s1m_artifacts(tmp_path: Path) -> None:
    symbol, footprint = _write_kicad_pair(tmp_path)
    step = tmp_path / "D_SMA.step"
    shutil.copyfile(_system_step(), step)

    report = verify_cross_eda_component(
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        kicad_symbol=symbol,
        kicad_footprint=footprint,
        step_model=step,
        altium_sources=(
            ALTIUM_FIXTURES / "sample.SchLib",
            ALTIUM_FIXTURES / "sample.PcbLib",
        ),
    )

    assert report["valid"] is True
    assert report["terminal_map"] == [
        {"altium": "C", "kicad": "1"},
        {"altium": "A", "kicad": "2"},
    ]
    assert report["kicad"]["pad_count"] == report["altium"]["pad_count"] == 2
    assert report["geometry"]["method"] == "mapped-pad-distance-and-size-signatures"
    assert report["step"]["geometry_reader"] == "cascadio"


def test_cross_eda_rejects_geometry_drift_before_model_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    symbol, footprint = _write_kicad_pair(tmp_path, pad_offset=3.0)
    step = tmp_path / "D_SMA.step"
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.model_to_glb",
        lambda _path: b"glTF-test-geometry",
    )

    with pytest.raises(CrossEdaVerificationError, match="pad spacing differs"):
        verify_cross_eda_component(
            identity=ExactPartIdentity("ON Semiconductor", "S1M"),
            kicad_symbol=symbol,
            kicad_footprint=footprint,
            step_model=step,
            altium_sources=(
                ALTIUM_FIXTURES / "sample.SchLib",
                ALTIUM_FIXTURES / "sample.PcbLib",
            ),
        )


def test_cross_eda_rejects_ambiguous_pin_name_mapping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    symbol, footprint = _write_kicad_pair(tmp_path, duplicate_pin_names=True)
    step = tmp_path / "D_SMA.step"
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.model_to_glb",
        lambda _path: b"glTF-test-geometry",
    )

    with pytest.raises(CrossEdaVerificationError, match="pin names do not prove"):
        verify_cross_eda_component(
            identity=ExactPartIdentity("ON Semiconductor", "S1M"),
            kicad_symbol=symbol,
            kicad_footprint=footprint,
            step_model=step,
            altium_sources=(
                ALTIUM_FIXTURES / "sample.SchLib",
                ALTIUM_FIXTURES / "sample.PcbLib",
            ),
        )


def test_identity_fields_accept_capitalization_only_duplicates(tmp_path: Path) -> None:
    symbol, _footprint = _write_kicad_pair(tmp_path)
    text = symbol.read_text(encoding="utf-8")
    symbol.write_text(
        text.replace(
            '(property "Manufacturer Part Number" "S1M" (at 0 0 0))',
            '(property "Manufacturer Name" "On Semiconductor" (at 0 0 0))\n'
            '    (property "Manufacturer Part Number" "S1M" (at 0 0 0))',
        ),
        encoding="utf-8",
    )

    observed = read_kicad_symbol(symbol, "S1M")

    assert observed.manufacturer in {"ON Semiconductor", "On Semiconductor"}


def test_provider_footprint_may_ship_model_as_a_separate_companion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    symbol, footprint = _write_kicad_pair(tmp_path)
    footprint.write_text(
        footprint.read_text(encoding="utf-8").split("  (model ", 1)[0] + ")\n",
        encoding="utf-8",
    )
    step = tmp_path / "D_SMA.step"
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.model_to_glb",
        lambda _path: b"glTF-test-geometry",
    )

    report = verify_kicad_component(
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        kicad_symbol=symbol,
        kicad_footprint=footprint,
        step_model=step,
    )

    assert report["model_link"] == "installed-during-attach"
