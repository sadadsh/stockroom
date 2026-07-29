from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from stockroom.capture import evidence as evidence_module
from stockroom.capture.cross_eda import CrossEdaVerificationError
from stockroom.capture.evidence import (
    BROWSER_CAPTURE_ADAPTER_VERSION,
    record_browser_cad_evidence,
)
from stockroom.capture.guided import GuidedCaptureSource
from stockroom.capture.requirements import Requirement
from stockroom.evidence import EvidenceStore
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.asset import Asset, AssetOrigin, AssetRef, EdaAssets
from stockroom.planning import KICAD_CAD_OPERATION, ExactPartIdentity

_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_DETAIL_URL = "https://www.snapeda.com/parts/S1M/ON%20Semiconductor/view-part/"
_ALTIUM_FIXTURES = Path(__file__).parents[1] / "altium" / "fixtures"


@pytest.fixture(autouse=True)
def _deterministic_step_geometry_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evidence tests exercise the readback seam without depending on a machine KiCad install.

    The real cascadio conversion is covered by ``test_cross_eda_readback_proves_real_s1m_artifacts``.
    """

    monkeypatch.setattr(
        "stockroom.capture.cross_eda.model_to_glb",
        lambda _path: b"glTF-test-geometry",
    )


@dataclass
class _Record:
    id: str = "s1m"
    manufacturer: str = "ON Semiconductor"
    mpn: str = "S1M"


@dataclass
class _InstalledRecord(_Record):
    category: str = "Diodes"
    assets: dict[str, EdaAssets] = field(
        default_factory=lambda: {
            "kicad": EdaAssets(),
            "altium": EdaAssets(),
        }
    )

    def assets_for(self, tool: str) -> EdaAssets:
        return self.assets[tool]


def _candidate(tmp_path: Path, *, model: bool = True) -> StagingCandidate:
    symbol = tmp_path / "S1M.kicad_sym"
    footprint = tmp_path / "S1M.kicad_mod"
    step = tmp_path / "S1M.step"
    symbol.write_text(
        """(kicad_symbol_lib
  (version 20240101)
  (symbol "S1M"
    (property "Manufacturer" "ON Semiconductor" (at 0 0 0))
    (property "Manufacturer Part Number" "S1M" (at 0 0 0))
    (symbol "S1M_0_1"
      (pin passive line (at -5 0 0) (length 2.54)
        (name "K" (effects (font (size 1 1))))
        (number "1" (effects (font (size 1 1))))))))
""",
        encoding="utf-8",
    )
    footprint.write_text(
        """(footprint "D_SMA"
  (version 20240108)
  (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (model "S1M.step"))
""",
        encoding="utf-8",
    )
    step.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    return StagingCandidate(
        vendor="snapmagic",
        symbol_lib_path=symbol,
        symbol_name="S1M",
        footprint_variants=[footprint],
        model_path=step if model else None,
        mpn="S1M",
        manufacturer="ON Semiconductor",
    )


def test_active_kicad_mechanical_pad_allowance_is_bound_to_the_active_manifest() -> None:
    validation = json.dumps(
        {
            "kicad_readback": {
                "unrepresented_pad_numbers": ["1", "2"],
            },
            "valid": True,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    store = SimpleNamespace(
        verified_cad_validation_report=lambda *_args, **_kwargs: json.loads(validation)
    )
    record = SimpleNamespace(
        cad_variants=SimpleNamespace(
            active={"kicad": SimpleNamespace(manifest_digest="sha256:active")}
        )
    )

    assert evidence_module._active_kicad_pad_allowance(
        store=store,
        record=record,
        identity=ExactPartIdentity("Example", "PART-1"),
    ) == frozenset({"1", "2"})


def _altium_pair(tmp_path: Path) -> tuple[Path, Path]:
    symbol = tmp_path / "S1M.SchLib"
    footprint = tmp_path / "S1M.PcbLib"
    symbol.write_bytes(_CFB_MAGIC + b"symbol")
    footprint.write_bytes(_CFB_MAGIC + b"footprint")
    return symbol, footprint


def test_browser_cad_installs_exact_actual_files_with_provider_per_artifact(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    candidate = _candidate(tmp_path)
    altium = _altium_pair(tmp_path)

    digest, cross_eda_verified = record_browser_cad_evidence(
        store=store,
        record=_Record(),
        candidate=candidate,
        provider_key="snapmagic",
        detail_url=_DETAIL_URL,
        altium_sources=altium,
    )

    manifest = store.verify_provider_success(
        digest,
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
    )
    objects = {item["role"]: item for item in manifest["objects"]}
    assert set(objects) == {
        "altium_footprint",
        "altium_symbol",
        "footprint",
        "model",
        "symbol",
        "validation_report",
    }
    assert {item["provider"] for item in objects.values()} == {"snapmagic"}
    assert store.object_bytes(objects["model"]["digest"]) == candidate.model_path.read_bytes()
    report = json.loads(store.object_bytes(objects["validation_report"]["digest"]))
    assert report["identity"] == {
        "authoritative_manufacturer_key": "ON Semiconductor",
        "mpn_canonical": "S1M",
    }
    assert report["cross_eda"]["status"] == "not_verified"
    assert report["kicad_readback"]["valid"] is True
    assert cross_eda_verified is False


def test_exact_provider_page_binds_metadata_light_kicad_symbol(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    candidate = _candidate(tmp_path)
    candidate.symbol_lib_path.write_text(
        """(kicad_symbol_lib
  (version 20240101)
  (symbol "S1M"
    (symbol "S1M_0_1"
      (pin passive line (at -5 0 0) (length 2.54)
        (name "K" (effects (font (size 1 1))))
        (number "1" (effects (font (size 1 1))))))))
""",
        encoding="utf-8",
    )

    digest, verified = record_browser_cad_evidence(
        store=store,
        record=_Record(),
        candidate=candidate,
        provider_key="snapmagic",
        detail_url=_DETAIL_URL,
    )

    manifest = store.verify_provider_success(
        digest,
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        operation=KICAD_CAD_OPERATION,
        provider_key="snapmagic",
        adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
    )
    objects = {item["role"]: item for item in manifest["objects"]}
    symbol_text = store.object_bytes(objects["symbol"]["digest"]).decode("utf-8")
    report = json.loads(store.object_bytes(objects["validation_report"]["digest"]))
    assert '(property "Manufacturer" "ON Semiconductor"' in symbol_text
    assert report["kicad_readback"]["identity_binding"] == {
        "fields_added": ["Manufacturer"],
        "source": "exact-provider-detail-page",
    }
    assert verified is False


def test_provider_identity_binding_never_overwrites_conflicting_symbol_metadata(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    original = candidate.symbol_lib_path.read_text(encoding="utf-8").replace(
        '"ON Semiconductor"',
        '"Other Manufacturer"',
    )
    candidate.symbol_lib_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="not 'ON Semiconductor'"):
        record_browser_cad_evidence(
            store=EvidenceStore(tmp_path / "Evidence"),
            record=_Record(),
            candidate=candidate,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )

    assert "Other Manufacturer" in candidate.symbol_lib_path.read_text(encoding="utf-8")


def test_browser_cad_cannot_record_a_partial_or_near_match(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    incomplete = _candidate(tmp_path, model=False)
    with pytest.raises(ValueError, match="missing STEP model"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=incomplete,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )

    near = _candidate(tmp_path)
    near.mpn = "S1M-13-F"
    near.symbol_name = "S1M-13-F"
    with pytest.raises(ValueError, match="exact candidate"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=near,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )


def test_browser_cad_validity_requires_native_kicad_readback(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")

    no_pins = _candidate(tmp_path)
    no_pins.symbol_lib_path.write_text(
        """(kicad_symbol_lib
  (version 20240101)
  (symbol "S1M"
    (property "Manufacturer" "ON Semiconductor" (at 0 0 0))
    (property "Manufacturer Part Number" "S1M" (at 0 0 0))))
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no readable pins"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=no_pins,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )

    unnumbered_pad = _candidate(tmp_path)
    unnumbered_pad.footprint_variants[0].write_text(
        """(footprint "D_SMA"
  (version 20240108)
  (pad "" smd rect (at 0 0) (size 1 1) (layers "F.Cu"))
  (model "S1M.step"))
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unnumbered pad"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=unnumbered_pad,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )

    malformed_step = _candidate(tmp_path)
    malformed_step.model_path.write_bytes(b"ISO-10303-21;\nHEADER;\n")
    with pytest.raises(ValueError, match="STEP exchange structure is incomplete"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=malformed_step,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
        )


def test_cross_eda_success_requires_explicit_equivalence_proof(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    candidate = _candidate(tmp_path)
    altium = _altium_pair(tmp_path)

    with pytest.raises(ValueError, match="terminal, pad, and package"):
        record_browser_cad_evidence(
            store=store,
            record=_Record(),
            candidate=candidate,
            provider_key="snapmagic",
            detail_url=_DETAIL_URL,
            altium_sources=altium,
            cross_eda_verifier=lambda **_kwargs: {"valid": False},
        )

    digest, verified = record_browser_cad_evidence(
        store=store,
        record=_Record(),
        candidate=candidate,
        provider_key="snapmagic",
        detail_url=_DETAIL_URL,
        altium_sources=altium,
        cross_eda_verifier=lambda **_kwargs: {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        },
    )
    assert digest.startswith("sha256:")
    assert verified is True


def test_guided_attach_persists_digest_and_refuses_unverified_altium(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    bundle = tmp_path / "download.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("S1M.SchLib", _CFB_MAGIC + b"symbol")
        archive.writestr("S1M.PcbLib", _CFB_MAGIC + b"footprint")

    origins = []
    active_variants = []
    altium_calls = []

    class _Pipeline:
        def inspect(self, inputs):
            assert inputs == [bundle]
            return [candidate]

        def attach_assets(self, part_id, selected, origin=None, active_variant=None):
            assert part_id == "s1m"
            assert selected is candidate
            origins.append(origin)
            active_variants.append(active_variant)

        def cleanup(self):
            return None

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "SnapMagic"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="snapmagic",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: altium_calls.append(True),
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        now_iso=lambda: "2026-07-28T00:00:00Z",
    )
    landed = [type("_Captured", (), {"path": bundle})()]

    outcome = source._attach(
        _Record(),
        landed,
        _DETAIL_URL,
        detail_url=_DETAIL_URL,
    )

    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
    }
    assert "cross-EDA terminal, pad, and package equivalence is not verified" in outcome.error
    assert not altium_calls
    assert len(origins) == 1
    digest = origins[0].extra["evidence_manifest_digest"]
    assert digest.startswith("sha256:")
    assert origins[0].extra["evidence_operation"] == "cad:kicad"
    assert len(active_variants) == 1
    assert active_variants[0].manifest_digest == digest
    active_variants[0].validate_for_tool("kicad")


def test_each_route_reloads_the_record_before_selecting_and_attaching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    downloaded = tmp_path / "route.zip"
    downloaded.write_bytes(b"captured")
    current = _Record()
    attached: list[str] = []

    class _Pipeline:
        ops = SimpleNamespace(load_record=lambda part_id: current)

        def inspect(self, inputs):
            assert inputs == [downloaded]
            return [candidate]

        def attach_assets(self, part_id, selected, **_kwargs):
            assert selected is candidate
            attached.append(part_id)

        def cleanup(self):
            return None

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "SnapMagic"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="snapmagic",
        download_root=tmp_path / "Downloads",
    )

    outcome = source._attach(
        _Record(mpn="STALE-BEFORE-EARLIER-ROUTE"),
        [SimpleNamespace(path=downloaded)],
        _DETAIL_URL,
        detail_url=_DETAIL_URL,
    )

    assert outcome.error == ""
    assert attached == ["s1m"]
    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
    }


def test_verified_sibling_kicad_and_altium_files_activate_as_one_coherent_variant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    record = _InstalledRecord()
    kicad_zip = tmp_path / "S1M.zip"
    with zipfile.ZipFile(kicad_zip, "w") as archive:
        archive.writestr("S1M.kicad_sym", candidate.symbol_lib_path.read_bytes())
    intlib = tmp_path / "S1M.IntLib"
    shutil.copyfile(_ALTIUM_FIXTURES / "sample.IntLib", intlib)
    pair_calls = []

    class _Pipeline:
        def inspect(self, inputs):
            if inputs == [kicad_zip]:
                return [candidate]
            if inputs == [intlib]:
                raise ValueError("native Altium library is not a KiCad ingest package")
            raise AssertionError(inputs)

        def attach_coherent_cad_assets(
            self,
            part_id,
            selected,
            *sources,
            kicad_origin=None,
            altium_origin=None,
            now_iso="",
            kicad_active_variant=None,
            altium_active_variant=None,
        ):
            pair_calls.append(
                (
                    part_id,
                    selected,
                    sources,
                    kicad_origin,
                    altium_origin,
                    now_iso,
                    kicad_active_variant,
                    altium_active_variant,
                )
            )
            record.assets["altium"] = EdaAssets(
                symbol=AssetRef(lib="S1M.SchLib", name="S1M"),
                footprint=AssetRef(lib="S1M.PcbLib", name="S1M"),
            )
            return record

        def cleanup(self):
            return None

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "SnapMagic"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="snapmagic",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: pytest.fail(
            "verified pairs must use one coherent transaction"
        ),
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        cross_eda_verifier=lambda **_kwargs: {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        },
    )

    outcome = source._attach(
        record,
        [
            type("_Captured", (), {"path": kicad_zip})(),
            type("_Captured", (), {"path": intlib})(),
        ],
        _DETAIL_URL,
        detail_url=_DETAIL_URL,
    )

    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    }, outcome.error
    assert outcome.error == ""
    assert len(pair_calls) == 1
    _, _, _, _, _, _, kicad_variant, altium_variant = pair_calls[0]
    assert kicad_variant.manifest_digest == altium_variant.manifest_digest
    kicad_variant.validate_for_tool("kicad")
    altium_variant.validate_for_tool("altium")


def test_provider_script_conversion_feeds_the_normal_verified_altium_attach(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    record = _InstalledRecord()
    provider_zip = tmp_path / "Provider.zip"
    with zipfile.ZipFile(provider_zip, "w") as archive:
        archive.writestr("AltiumDesigner/UL_Import.pas", "provider script")
    native = tmp_path / "Native"
    native.mkdir()
    schlib = native / "S1M.SchLib"
    pcblib = native / "S1M.PcbLib"
    shutil.copy2(_ALTIUM_FIXTURES / "sample.SchLib", schlib)
    shutil.copy2(_ALTIUM_FIXTURES / "sample.PcbLib", pcblib)
    conversion_calls = []
    cleanup_calls = []
    pair_calls = []

    class _Pipeline:
        def inspect(self, inputs):
            assert inputs == [provider_zip]
            return [candidate]

        def attach_coherent_cad_assets(
            self,
            part_id,
            selected,
            *sources,
            **kwargs,
        ):
            pair_calls.append((part_id, selected, sources, kwargs))
            record.assets["altium"] = EdaAssets(
                symbol=AssetRef(lib="S1M.SchLib", name="S1M"),
                footprint=AssetRef(lib="S1M.PcbLib", name="S1M"),
            )
            return record

        def cleanup(self):
            return None

    def _convert(inputs, manufacturer, mpn):
        conversion_calls.append((inputs, manufacturer, mpn))
        return type(
            "_Converted",
            (),
            {
                "libraries": (schlib, pcblib),
                "cleanup": lambda _self: cleanup_calls.append("cleaned"),
            },
        )()

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "DigiKey · Ultra Librarian"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="digikey",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: pytest.fail(
            "verified pairs must use one coherent transaction"
        ),
        convert_altium=_convert,
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        cross_eda_verifier=lambda **_kwargs: {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        },
    )

    outcome = source._attach(
        record,
        [type("_Captured", (), {"path": provider_zip})()],
        _DETAIL_URL,
        detail_url=_DETAIL_URL,
    )

    assert conversion_calls == [((provider_zip,), "ON Semiconductor", "S1M")]
    assert cleanup_calls == ["cleaned"]
    assert len(pair_calls) == 1
    assert pair_calls[0][2] == (schlib, pcblib)
    assert Requirement.ALTIUM_SYMBOL in outcome.satisfied
    assert Requirement.ALTIUM_FOOTPRINT in outcome.satisfied


def _installed_kicad(
    tmp_path: Path,
    candidate: StagingCandidate,
) -> tuple[_InstalledRecord, object]:
    root = tmp_path / "Library"

    class _Library:
        def __init__(self) -> None:
            self.root = root

        def symbol_lib_path(self, _category: str) -> Path:
            return root / "symbols" / "Diodes.kicad_sym"

        def footprint_lib_path(self, _category: str) -> Path:
            return root / "footprints" / "Diodes.pretty"

    library = _Library()
    symbol = library.symbol_lib_path("Diodes")
    footprint = library.footprint_lib_path("Diodes") / "D_SMA.kicad_mod"
    model = root / "models" / "S1M.step"
    for path in (symbol, footprint, model):
        path.parent.mkdir(parents=True, exist_ok=True)
    symbol.write_bytes(candidate.symbol_lib_path.read_bytes())
    footprint.write_bytes(candidate.chosen_footprint.read_bytes())
    model.write_bytes(candidate.model_path.read_bytes())

    origin = AssetOrigin(vendor="lcsc")
    record = _InstalledRecord()
    record.assets["kicad"] = EdaAssets(
        symbol=Asset(ref=AssetRef(lib="Diodes", name="S1M"), origin=origin),
        footprint=Asset(ref=AssetRef(lib="Diodes", name="D_SMA"), origin=origin),
        model=Asset(ref=AssetRef(file="models/S1M.step"), origin=origin),
    )
    profile = type("_Profile", (), {"library": library})()
    return record, profile


def test_altium_only_download_composes_with_reverified_active_kicad_without_replacing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    record, profile = _installed_kicad(tmp_path, candidate)
    bundle = tmp_path / "provider-script.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("AltiumDesigner/UL_Import.pas", "reviewed provider script")
        archive.writestr("D_SMA.step", candidate.model_path.read_bytes())
    converted_root = tmp_path / "Converted"
    converted_root.mkdir()
    schlib = converted_root / "S1M.SchLib"
    pcblib = converted_root / "S1M.PcbLib"
    schlib.write_bytes(_CFB_MAGIC + b"symbol")
    pcblib.write_bytes(_CFB_MAGIC + b"footprint")
    anonymous_model = StagingCandidate(
        vendor="partial",
        symbol_lib_path=None,
        symbol_name="",
        footprint_variants=[],
        model_path=candidate.model_path,
    )
    store = EvidenceStore(tmp_path / "Evidence")
    attach_origins = []
    attached_variants = []
    conversion_cleanups = []
    original_kicad = record.assets_for("kicad")

    class _Pipeline:
        def __init__(self) -> None:
            self.profile = profile

        def inspect(self, inputs):
            assert inputs == [bundle]
            return [anonymous_model]

        def cleanup(self):
            return None

    def _attach_altium(
        part_id,
        *sources,
        origin=None,
        active_variant=None,
        compatible_kicad_variant=None,
    ):
        assert part_id == "s1m"
        assert {path.suffix.casefold() for path in sources} == {".schlib", ".pcblib"}
        assert all(path.read_bytes().startswith(_CFB_MAGIC) for path in sources)
        attach_origins.append(origin)
        attached_variants.append((active_variant, compatible_kicad_variant))
        record.assets["altium"] = EdaAssets(
            symbol=AssetRef(lib="S1M", name="S1M"),
            footprint=AssetRef(lib="S1M", name="S1M"),
        )
        return record

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "Ultra Librarian"})()},
        )(),
    )

    def _verify_installed_names(**kwargs):
        assert kwargs["kicad_symbol"].name == "Diodes.kicad_sym"
        assert kwargs["kicad_footprint"].name == "D_SMA.kicad_mod"
        assert kwargs["step_model"].name == "S1M.step"
        return {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        }

    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="ultralibrarian",
        download_root=tmp_path / "Downloads",
        attach_altium=_attach_altium,
        convert_altium=lambda _inputs, _manufacturer, _mpn: type(
            "_Converted",
            (),
            {
                "libraries": (schlib, pcblib),
                "cleanup": lambda _self: conversion_cleanups.append("cleaned"),
            },
        )(),
        evidence_store=store,
        cross_eda_verifier=_verify_installed_names,
        now_iso=lambda: "2026-07-28T00:00:00Z",
    )

    outcome = source._attach(
        record,
        [type("_Captured", (), {"path": bundle})()],
        _DETAIL_URL.replace("snapeda.com", "ultralibrarian.com"),
        detail_url=("https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M"),
    )

    assert set(outcome.satisfied) == {
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    }
    assert outcome.error == ""
    assert conversion_cleanups == ["cleaned"]
    assert record.assets_for("kicad") is original_kicad
    assert len(attach_origins) == 1
    origin = attach_origins[0]
    assert origin.extra["evidence_operation"] == "cad:altium"
    manifest = store.verify_role_artifact_success(
        origin.extra["evidence_manifest_digest"],
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        required_roles=("altium_symbol", "altium_footprint"),
    )
    assert manifest["provider"] == "ultralibrarian"
    assert len(manifest["source_manifests"]) == 1
    assert len(attached_variants) == 1
    active_altium, compatible_kicad = attached_variants[0]
    assert active_altium.manifest_digest == origin.extra["evidence_manifest_digest"]
    assert active_altium.source_manifests == (compatible_kicad.manifest_digest,)
    active_altium.validate_for_tool("altium")
    compatible_kicad.validate_for_tool("kicad")
    assert [
        item.provider_key
        for item in store.list_role_variants(
            identity=ExactPartIdentity("ON Semiconductor", "S1M"),
            role="altium_symbol",
        )
    ] == ["ultralibrarian"]


def test_altium_only_download_switches_to_a_compatible_retained_kicad_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active_candidate = _candidate(tmp_path)
    record, profile = _installed_kicad(tmp_path, active_candidate)
    retained_root = tmp_path / "Retained"
    retained_root.mkdir()
    retained_candidate = _candidate(retained_root)
    retained_candidate.symbol_lib_path.write_bytes(
        retained_candidate.symbol_lib_path.read_bytes() + b"\n"
    )
    retained_candidate.chosen_footprint.write_bytes(
        retained_candidate.chosen_footprint.read_bytes() + b"\n"
    )
    retained_candidate.model_path.write_bytes(
        retained_candidate.model_path.read_bytes() + b"\n"
    )
    store = EvidenceStore(tmp_path / "Evidence")
    retained_manifest, _ = record_browser_cad_evidence(
        store=store,
        record=record,
        candidate=retained_candidate,
        provider_key="ultralibrarian",
        detail_url="https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M",
    )
    bundle = tmp_path / "altium-only.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("S1M.SchLib", _CFB_MAGIC + b"symbol")
        archive.writestr("S1M.PcbLib", _CFB_MAGIC + b"footprint")
    pair_calls = []

    class _Pipeline:
        def __init__(self) -> None:
            self.profile = profile

        def inspect(self, inputs):
            assert inputs == [bundle]
            return []

        def attach_coherent_cad_assets(self, part_id, selected, *sources, **kwargs):
            assert part_id == record.id
            assert selected.vendor == "ultralibrarian"
            assert selected.symbol_lib_path.is_file()
            assert all(path.is_file() for path in sources)
            pair_calls.append((selected, sources, kwargs))
            record.assets["altium"] = EdaAssets(
                symbol=AssetRef(lib="S1M.SchLib", name="S1M"),
                footprint=AssetRef(lib="S1M.PcbLib", name="S1M"),
            )
            return record

        def cleanup(self):
            return None

    def _verify(**kwargs):
        if kwargs["kicad_symbol"].name == "Diodes.kicad_sym":
            raise CrossEdaVerificationError(
                "KiCad and Altium pad spacing differs for terminals ('1', '2')"
            )
        return {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
        }

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "Ultra Librarian"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="ultralibrarian",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: pytest.fail(
            "a retained compatible pair must use one coherent transaction"
        ),
        evidence_store=store,
        cross_eda_verifier=_verify,
        now_iso=lambda: "2026-07-29T00:00:00Z",
    )
    outcome = source._attach(
        record,
        [type("_Captured", (), {"path": bundle})()],
        "https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M",
        detail_url="https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M",
    )

    assert set(outcome.satisfied) == {
        Requirement.KICAD_SYMBOL,
        Requirement.KICAD_FOOTPRINT,
        Requirement.KICAD_MODEL,
        Requirement.ALTIUM_SYMBOL,
        Requirement.ALTIUM_FOOTPRINT,
    }
    assert outcome.error == ""
    assert len(pair_calls) == 1
    selected, altium_sources, kwargs = pair_calls[0]
    compatible_manifest = kwargs["kicad_active_variant"].manifest_digest
    assert compatible_manifest != retained_manifest
    assert kwargs["altium_active_variant"].source_manifests == (compatible_manifest,)
    assert kwargs["kicad_origin"].vendor == "ultralibrarian"
    store.verify_role_artifact_success(
        compatible_manifest,
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
        required_roles=("symbol", "footprint", "model"),
    )
    report = store.verified_cad_validation_report(
        compatible_manifest,
        identity=ExactPartIdentity("ON Semiconductor", "S1M"),
    )
    assert report["observations"]["promoted_from_retained_manifest"] == retained_manifest
    assert not selected.symbol_lib_path.parent.exists()
    assert not altium_sources[0].parent.exists()


def test_altium_only_download_stays_unattached_without_complete_equivalence_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    record, profile = _installed_kicad(tmp_path, candidate)
    bundle = tmp_path / "altium-only.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("S1M.SchLib", _CFB_MAGIC + b"symbol")
        archive.writestr("S1M.PcbLib", _CFB_MAGIC + b"footprint")
    attached = []

    class _Pipeline:
        def __init__(self) -> None:
            self.profile = profile

        def inspect(self, inputs):
            assert inputs == [bundle]
            return []

        def cleanup(self):
            return None

    monkeypatch.setattr(
        "stockroom.capture.guided.get_adapter",
        lambda _key: type(
            "_Adapter",
            (),
            {"capability": type("_Capability", (), {"label": "Ultra Librarian"})()},
        )(),
    )
    source = GuidedCaptureSource(
        lambda: _Pipeline(),
        vendor="ultralibrarian",
        download_root=tmp_path / "Downloads",
        attach_altium=lambda *_args, **_kwargs: attached.append(True),
        evidence_store=EvidenceStore(tmp_path / "Evidence"),
        cross_eda_verifier=lambda **_kwargs: {"valid": True},
    )

    outcome = source._attach(
        record,
        [type("_Captured", (), {"path": bundle})()],
        "https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M",
        detail_url="https://app.ultralibrarian.com/details/example/ON%20Semiconductor/S1M",
    )

    assert not attached
    assert outcome.satisfied == ()
    assert "terminal, pad, and package equivalence" in outcome.error
