from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.capture.projection import (
    InstalledProjectionError,
    verify_installed_projection,
)
from stockroom.model.asset import Asset, AssetRef, EdaAssets
from stockroom.store.profile import ProfileLibrary


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path):
    library = ProfileLibrary(tmp_path / "Library")
    library.ensure_layout()
    files = {
        "KiCad Symbol Artifact Path": ("EDA/KiCad/Symbol.kicad_sym", b"symbol"),
        "KiCad Footprint Artifact Path": ("EDA/KiCad/Part.kicad_mod", b"footprint"),
        "Altium Symbol Artifact Path": ("EDA/Altium/Part.SchLib", b"schlib"),
        "Altium Footprint Artifact Path": ("EDA/Altium/Part.PcbLib", b"pcblib"),
    }
    row: dict[str, str] = {}
    for column, (relative, data) in files.items():
        path = library.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        row[column] = relative
        row[column.replace("Path", "Digest")] = _digest(data)
    model = library.root / "EDA/KiCad/Part.step"
    model.write_bytes(b"model")

    kicad = EdaAssets(
        symbol=Asset(ref=AssetRef(lib="Stockroom_part", name="PART")),
        footprint=Asset(ref=AssetRef(lib="Stockroom_part", name="PART_FP")),
        model=Asset(ref=AssetRef(file="EDA/KiCad/Part.step")),
    )
    altium = EdaAssets(
        symbol=Asset(ref=AssetRef(lib="EDA/Altium/Part.SchLib", name="PART")),
        footprint=Asset(ref=AssetRef(lib="EDA/Altium/Part.PcbLib", name="PART_FP")),
    )
    record = SimpleNamespace(
        manufacturer="Example Semiconductor",
        mpn="PART",
        category="ICs",
        extra={
            "production_publication": {
                "schema": "stockroom.production-publication/1",
                "catalog_row": row,
            }
        },
        assets_for=lambda tool: kicad if tool == "kicad" else altium,
    )
    resolved = {
        "kicad": SimpleNamespace(data={"model": b"model"}),
        "altium": SimpleNamespace(data={"symbol": b"unused", "footprint": b"unused"}),
    }
    return library, record, resolved


def test_projection_readback_binds_published_bytes_and_native_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, record, resolved = _fixture(tmp_path)
    monkeypatch.setattr(
        "stockroom.capture.projection.read_kicad_symbol",
        lambda *_args, **_kwargs: SimpleNamespace(
            entry="PART",
            pins=(SimpleNamespace(number="1"),),
        ),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.read_kicad_footprint",
        lambda *_args, **_kwargs: SimpleNamespace(
            entry="PART_FP",
            pads=(SimpleNamespace(number="1"),),
        ),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.verify_kicad_component",
        lambda **_kwargs: {"valid": True},
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.read_altium_symbol",
        lambda *_args, **_kwargs: SimpleNamespace(entry="PART"),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.read_altium_footprint",
        lambda *_args, **_kwargs: SimpleNamespace(entry="PART_FP"),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.verify_cross_eda_component",
        lambda **_kwargs: {
            "kicad": {"symbol_entry": "PART", "footprint_entry": "PART_FP"},
            "altium": {"symbol_entry": "PART", "footprint_entry": "PART_FP"},
        },
    )

    verify_installed_projection(library, record, resolved)  # type: ignore[arg-type]

    footprint = library.root / "EDA/KiCad/Part.kicad_mod"
    footprint.write_bytes(b"tampered")
    with pytest.raises(InstalledProjectionError, match="published artifact digest"):
        verify_installed_projection(library, record, resolved)  # type: ignore[arg-type]


def test_projection_readback_rejects_a_missing_installed_file(tmp_path: Path) -> None:
    library, record, resolved = _fixture(tmp_path)
    (library.root / "EDA/KiCad/Part.kicad_mod").unlink()

    with pytest.raises(InstalledProjectionError, match="footprint is missing"):
        verify_installed_projection(library, record, resolved)  # type: ignore[arg-type]


def test_altium_only_projection_rejects_an_unbound_native_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, record, resolved = _fixture(tmp_path)
    monkeypatch.setattr(
        "stockroom.capture.projection.read_altium_symbol",
        lambda *_args, **_kwargs: SimpleNamespace(entry="PART"),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.read_altium_footprint",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("entry missing")),
    )

    with pytest.raises(InstalledProjectionError, match="unreadable or unbound"):
        verify_installed_projection(
            library,
            record,
            {"altium": resolved["altium"]},
        )  # type: ignore[arg-type]


def test_kicad_projection_uses_only_the_immutable_proved_pad_allowance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, record, resolved = _fixture(tmp_path)
    observed: list[frozenset[str]] = []
    monkeypatch.setattr(
        "stockroom.capture.projection.read_kicad_symbol",
        lambda *_args, **_kwargs: SimpleNamespace(entry="PART"),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.read_kicad_footprint",
        lambda *_args, **_kwargs: SimpleNamespace(entry="PART_FP"),
    )
    monkeypatch.setattr(
        "stockroom.capture.projection.verify_kicad_component",
        lambda **kwargs: observed.append(kwargs["allowed_unrepresented_pads"]),
    )
    validation = {
        "kicad": {
            "cross_eda": {
                "report": {"kicad": {"unrepresented_pad_numbers": ["EP"]}},
                "status": "verified",
            },
            "valid": True,
        }
    }

    verify_installed_projection(
        library,
        record,
        {"kicad": resolved["kicad"]},
        validation_reports=validation,
    )  # type: ignore[arg-type]
    verify_installed_projection(
        library,
        record,
        {"kicad": resolved["kicad"]},
        validation_reports={"kicad": {"valid": True}},
    )  # type: ignore[arg-type]

    assert observed == [frozenset({"EP"}), frozenset()]
