from __future__ import annotations

import shutil
import struct
from pathlib import Path

import olefile
import pytest

from stockroom.capture.cross_eda import (
    CrossEdaVerificationError,
    _geometry_tolerance_ratio,
    _PadGeometry,
    _Pin,
    _read_altium_symbol_stream,
    _resolve_component_data_stream,
    _SymbolReadback,
    _terminal_map,
    _verify_geometry,
    _verify_identity,
    read_altium_footprint,
    read_altium_symbol,
    read_kicad_footprint,
    read_kicad_symbol,
    verify_cross_eda_component,
    verify_kicad_component,
)
from stockroom.kicad.stock import find_kicad_share_dir
from stockroom.planning import ExactPartIdentity

ALTIUM_FIXTURES = Path(__file__).parents[1] / "altium" / "fixtures"


class _OleDirectory:
    def __init__(self, streams: list[list[str]]) -> None:
        self._streams = streams

    def exists(self, path: list[str]) -> bool:
        return path in self._streams

    def listdir(self, *, streams: bool, storages: bool) -> list[list[str]]:
        assert streams and not storages
        return self._streams


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
    if root is None:
        pytest.skip("installed KiCad library is unavailable")
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


def test_altium_readback_resolves_ole_truncated_component_storage() -> None:
    entry = "SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR"
    truncated = entry[:31]
    container = _OleDirectory([["Library", "Data"], [truncated, "Data"]])

    assert _resolve_component_data_stream(container, entry) == [truncated, "Data"]


def test_native_altium_readback_separates_exact_source_mpn_from_sanitized_entry() -> None:
    path = ALTIUM_FIXTURES / "sample.SchLib"
    with olefile.OleFileIO(str(path)) as container:
        raw = container.openstream(["S1M", "Data"]).read()
    raw = raw.replace(b"S1M", b"S/1")

    symbol = _read_altium_symbol_stream(
        raw,
        "S_1",
        source_identity="S/1",
    )

    assert symbol.entry == "S_1"
    assert symbol.mpn == "S/1"
    assert symbol.footprint_entries == ("DIOM5227X270N",)


def test_kicad_readback_ignores_unnumbered_paste_apertures(tmp_path: Path) -> None:
    _symbol, footprint = _write_kicad_pair(tmp_path)
    footprint.write_text(
        footprint.read_text(encoding="utf-8").replace(
            '  (pad "2" smd rect',
            '  (pad "" smd rect (at 0 0) (size 1 1) (layers "F.Paste"))\n'
            '  (pad "2" smd rect',
        ),
        encoding="utf-8",
    )

    observed = read_kicad_footprint(footprint, _system_step())

    assert [pad.number for pad in observed.pads] == ["1", "2"]


def test_native_altium_readback_accepts_an_unnamed_numbered_pin() -> None:
    header = b"|RECORD=1|LIBREFERENCE=TEST|ALLPINCOUNT=1|"
    pin = b"\0" * 26 + b"\0" + b"\x011"
    stream = (
        struct.pack("<I", len(header))
        + header
        + struct.pack("<I", (1 << 24) | len(pin))
        + pin
    )

    symbol = _read_altium_symbol_stream(stream, "TEST")

    assert [(item.number, item.name) for item in symbol.pins] == [("1", "")]


def test_metadata_light_altium_identity_requires_exact_external_attestation() -> None:
    expected = ExactPartIdentity("Texas Instruments", "TPD6E05U06RVZR")
    metadata_light = _SymbolReadback(
        entry="TPD6E05U06RVZR",
        manufacturer="",
        mpn="TPD6E05U06RVZR",
        pins=(),
    )

    with pytest.raises(CrossEdaVerificationError, match="does not carry both"):
        _verify_identity(metadata_light, expected, "Altium")

    assert _verify_identity(metadata_light, expected, "Altium", expected) == ("manufacturer",)

    conflicting = _SymbolReadback(
        entry=metadata_light.entry,
        manufacturer="Other Manufacturer",
        mpn=metadata_light.mpn,
        pins=(),
    )
    with pytest.raises(CrossEdaVerificationError, match="does not equal"):
        _verify_identity(conflicting, expected, "Altium", expected)


def test_pcad_truncated_altium_entry_requires_exact_external_attestation() -> None:
    expected = ExactPartIdentity("Abracon LLC", "ABM13W-32.0000MHZ-5-DH7G-T5")
    converted = _SymbolReadback(
        entry="ABM13W-32.0000MH",
        manufacturer="",
        mpn="ABM13W-32.0000MH",
        pins=(),
        mpn_from_entry=True,
    )

    with pytest.raises(CrossEdaVerificationError, match="does not carry both"):
        _verify_identity(converted, expected, "Altium")

    assert _verify_identity(converted, expected, "Altium", expected) == (
        "manufacturer",
        "mpn",
    )

    wrong = _SymbolReadback(
        entry="ABM13W-32.0000XX",
        manufacturer="",
        mpn="ABM13W-32.0000XX",
        pins=(),
        mpn_from_entry=True,
    )
    with pytest.raises(CrossEdaVerificationError, match="does not equal"):
        _verify_identity(wrong, expected, "Altium", expected)


def test_cross_eda_identity_accepts_only_the_canonical_legal_suffix_difference() -> None:
    expected = ExactPartIdentity("Abracon LLC", "ABM13W-32.0000MHZ-5-DH7G-T5")
    provider_symbol = _SymbolReadback(
        entry=expected.mpn_canonical,
        manufacturer="Abracon",
        mpn=expected.mpn_canonical,
        pins=(),
    )

    assert _verify_identity(provider_symbol, expected, "Altium", expected) == ()

    wrong_mpn = _SymbolReadback(
        entry="ABM13W-32.0000MHZ-5-DH7G-T6",
        manufacturer="Abracon",
        mpn="ABM13W-32.0000MHZ-5-DH7G-T6",
        pins=(),
    )
    with pytest.raises(CrossEdaVerificationError, match="MPN .* does not equal"):
        _verify_identity(wrong_mpn, expected, "Altium", expected)


def test_cross_eda_selects_the_altium_footprint_bound_by_kicad(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identity = ExactPartIdentity("Abracon LLC", "ABM13W-32.0000MHZ-5-DH7G-T5")
    paths = {
        name: tmp_path / name
        for name in ("part.kicad_sym", "ABM13W_ABR.kicad_mod", "part.step", "part.SchLib", "part.PcbLib")
    }
    for path in paths.values():
        path.write_bytes(b"fixture")
    pins = (_Pin("1", "1"), _Pin("2", "2"))
    pads = (
        _PadGeometry("1", -0.4, 0.0, 0.5, 0.5),
        _PadGeometry("2", 0.4, 0.0, 0.5, 0.5),
    )
    observed_preferred = []

    monkeypatch.setattr(
        "stockroom.capture.cross_eda._resolve_altium_sources",
        lambda _sources, _temporary: (paths["part.SchLib"], paths["part.PcbLib"]),
    )
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.read_kicad_symbol",
        lambda _path, _preferred: _SymbolReadback(
            identity.mpn_canonical,
            "Abracon LLC",
            identity.mpn_canonical,
            pins,
        ),
    )
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.read_altium_symbol",
        lambda _path, _preferred: _SymbolReadback(
            identity.mpn_canonical,
            "Abracon",
            identity.mpn_canonical,
            pins,
        ),
    )
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.read_kicad_footprint",
        lambda _path, _model: type(
            "_Footprint",
            (),
            {"entry": "ABM13W_ABR", "pads": pads, "model_path": "part.step"},
        )(),
    )

    def _altium_footprint(_path, preferred):
        observed_preferred.append(preferred)
        return type(
            "_Footprint",
            (),
            {"entry": preferred, "pads": pads, "model_path": "part.step"},
        )()

    monkeypatch.setattr(
        "stockroom.capture.cross_eda.read_altium_footprint",
        _altium_footprint,
    )
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.verify_kicad_component",
        lambda **_kwargs: {"valid": True, "step": {"valid": True}},
    )
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.read_embedded_model_payloads",
        lambda _path: (),
    )

    report = verify_cross_eda_component(
        identity=identity,
        kicad_symbol=paths["part.kicad_sym"],
        kicad_footprint=paths["ABM13W_ABR.kicad_mod"],
        step_model=paths["part.step"],
        altium_sources=(paths["part.SchLib"], paths["part.PcbLib"]),
    )

    assert observed_preferred == ["ABM13W_ABR"]
    assert report["altium"]["footprint_entry"] == "ABM13W_ABR"


def test_symbol_may_omit_explicit_no_connect_pins_when_both_footprints_keep_them() -> None:
    kicad = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=(_Pin("1", "NC"), _Pin("2", "IO"), _Pin("3", "GND")),
    )
    altium = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=(_Pin("2", "IO"), _Pin("3", "GND")),
    )
    pads = (
        _PadGeometry("1", 0.0, 0.0, 1.0, 1.0),
        _PadGeometry("2", 1.0, 0.0, 1.0, 1.0),
        _PadGeometry("3", 2.0, 0.0, 1.0, 1.0),
    )

    mapping, kicad_nc, altium_nc = _terminal_map(kicad, altium)
    physical = _verify_geometry(
        pads,
        pads,
        mapping,
        kicad_no_connects=kicad_nc,
        altium_no_connects=altium_nc,
    )

    assert mapping == {"2": "2", "3": "3"}
    assert physical == {"1": "1", "2": "2", "3": "3"}


def test_both_symbols_may_omit_the_same_package_only_pads() -> None:
    kicad = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=(_Pin("2", "IO"), _Pin("3", "GND")),
    )
    altium = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=(_Pin("2", "IO"), _Pin("3", "GND")),
    )
    pads = (
        _PadGeometry("1", 0.0, 0.0, 1.0, 1.0),
        _PadGeometry("2", 1.0, 0.0, 1.0, 1.0),
        _PadGeometry("3", 2.0, 0.0, 1.0, 1.0),
    )

    mapping, kicad_nc, altium_nc = _terminal_map(kicad, altium)
    physical = _verify_geometry(
        pads,
        pads,
        mapping,
        kicad_no_connects=kicad_nc,
        altium_no_connects=altium_nc,
    )

    assert mapping == {"2": "2", "3": "3"}
    assert physical == {"1": "1", "2": "2", "3": "3"}


def test_provider_specific_thermal_vias_do_not_reject_shared_electrical_geometry() -> None:
    kicad = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=(_Pin("1", "VIN"), _Pin("2", "GND")),
    )
    altium = _SymbolReadback(
        entry="PART",
        manufacturer="Acme",
        mpn="PART",
        pins=kicad.pins,
    )
    shared = (
        _PadGeometry("1", -1.0, 0.0, 0.5, 0.5),
        _PadGeometry("2", 1.0, 0.0, 0.5, 0.5),
    )
    altium_pads = (
        *shared,
        _PadGeometry("3", -0.2, 0.0, 0.2, 0.2),
        _PadGeometry("4", 0.2, 0.0, 0.2, 0.2),
    )

    mapping, kicad_nc, altium_nc = _terminal_map(kicad, altium)

    assert _verify_geometry(
        shared,
        altium_pads,
        mapping,
        kicad_no_connects=kicad_nc,
        altium_no_connects=altium_nc,
    ) == {"1": "1", "2": "2"}
    assert _geometry_tolerance_ratio(
        shared,
        altium_pads,
        {"1": "1", "2": "2"},
    ) == 0.0


def test_standalone_kicad_rejects_unrepresented_pads_without_cross_eda_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    symbol, footprint = _write_kicad_pair(tmp_path)
    footprint.write_text(
        footprint.read_text(encoding="utf-8").replace(
            '  (pad "2" smd rect',
            '  (pad "3" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))\n'
            '  (pad "2" smd rect',
        ),
        encoding="utf-8",
    )
    step = tmp_path / "D_SMA.step"
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    monkeypatch.setattr(
        "stockroom.capture.cross_eda.model_to_glb",
        lambda _path: b"glTF-test-geometry",
    )
    kwargs = {
        "identity": ExactPartIdentity("ON Semiconductor", "S1M"),
        "kicad_symbol": symbol,
        "kicad_footprint": footprint,
        "step_model": step,
    }

    with pytest.raises(CrossEdaVerificationError, match="pad numbers"):
        verify_kicad_component(**kwargs)

    report = verify_kicad_component(
        **kwargs,
        allowed_unrepresented_pads=frozenset({"3"}),
    )
    assert report["unrepresented_pad_numbers"] == ["3"]


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
