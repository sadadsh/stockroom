from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.capture.cad_composition import (
    CompatibleKicadVariantNotFound,
    OwnedMaterialization,
    cross_eda_report_is_proved,
    provider_family,
    select_compatible_retained_kicad,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.planning import KICAD_CAD_OPERATION, ExactPartIdentity

_IDENTITY = ExactPartIdentity("Texas Instruments", "TPD6E05U06RVZR")


def _report(provider: str, roles: tuple[str, ...]) -> bytes:
    return json.dumps(
        {
            "identity": {
                "authoritative_manufacturer_key": _IDENTITY.authoritative_manufacturer_key,
                "mpn_canonical": _IDENTITY.mpn_canonical,
            },
            "observations": {},
            "operation": KICAD_CAD_OPERATION.label,
            "provider": provider,
            "roles": sorted(roles),
            "schema": "stockroom.cad-role-validation/1",
            "source_manifests": [],
            "valid": True,
            "verification": {"valid": True},
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _record_kicad(store: EvidenceStore, provider: str, marker: str) -> str:
    artifacts = (
        EvidenceArtifact(
            "symbol",
            f'(kicad_symbol_lib (symbol "{marker}"))'.encode(),
            "application/vnd.kicad.symbol-library",
            f"{marker}.kicad_sym",
        ),
        EvidenceArtifact(
            "footprint",
            f'(footprint "{marker}")'.encode(),
            "application/vnd.kicad.footprint",
            f"{marker}.kicad_mod",
        ),
        EvidenceArtifact(
            "model",
            f"ISO-10303-21;\n/* {marker} */\nEND-ISO-10303-21;\n".encode(),
            "model/step",
            f"{marker}.step",
        ),
    )
    roles = tuple(artifact.role for artifact in artifacts)
    return store.record_role_artifact_success(
        identity=_IDENTITY,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider,
        adapter_version="test-v1",
        artifacts=artifacts,
        validation_report=_report(provider, roles),
    )


def _altium_pair(tmp_path: Path) -> tuple[Path, Path]:
    schlib = tmp_path / "Converted.SchLib"
    pcblib = tmp_path / "Converted.PcbLib"
    schlib.write_bytes(b"native-symbol")
    pcblib.write_bytes(b"native-footprint")
    return schlib, pcblib


def _explicit_success() -> dict[str, object]:
    return {
        "package_equivalence": True,
        "pad_equivalence": True,
        "terminal_equivalence": True,
        "valid": True,
    }


def test_digikey_ultralibrarian_prefers_retained_ul_family_over_active_snapmagic(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    snap = _record_kicad(store, "snapmagic", "snap")
    ultra = _record_kicad(store, "ultralibrarian", "ultra")
    calls: list[str] = []

    def verifier(**kwargs):
        marker = kwargs["kicad_symbol"].read_text(encoding="utf-8")
        calls.append("ultra" if "ultra" in marker else "snap")
        if "snap" in marker:
            raise ValueError("geometry mismatch")
        return _explicit_success()

    selected = select_compatible_retained_kicad(
        store,
        identity=_IDENTITY,
        altium_provider_key="digikey-ultralibrarian",
        altium_sources=_altium_pair(tmp_path),
        verifier=verifier,
        temporary_parent=tmp_path,
    )

    assert selected.resolved.descriptor.manifest_digest == ultra
    assert selected.resolved.descriptor.manifest_digest != snap
    assert selected.resolved.descriptor.provider == "ultralibrarian"
    assert calls == ["ultra"]
    assert [attempt.provider for attempt in selected.attempts] == ["ultralibrarian"]
    assert not list(tmp_path.glob("stockroom-compatible-kicad-*"))


def test_exact_route_then_family_then_existing_trust_order_is_deterministic(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    _record_kicad(store, "snapmagic", "snap")
    _record_kicad(store, "ultralibrarian", "ultra")
    exact = _record_kicad(store, "digikey-ultralibrarian", "digikey")
    calls: list[str] = []

    def verifier(**kwargs):
        marker = kwargs["kicad_symbol"].read_text(encoding="utf-8")
        calls.append(marker)
        return _explicit_success()

    selected = select_compatible_retained_kicad(
        store,
        identity=_IDENTITY,
        altium_provider_key="digikey-ultralibrarian",
        altium_sources=_altium_pair(tmp_path),
        verifier=verifier,
    )

    assert selected.resolved.descriptor.manifest_digest == exact
    assert len(calls) == 1
    assert "digikey" in calls[0]


def test_current_installed_snapshot_is_tried_before_provider_family(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    current = _record_kicad(store, "snapmagic", "current")
    _record_kicad(store, "ultralibrarian", "ultra")
    calls: list[str] = []

    def verifier(**kwargs):
        calls.append(kwargs["kicad_symbol"].read_text(encoding="utf-8"))
        return _explicit_success()

    selected = select_compatible_retained_kicad(
        store,
        identity=_IDENTITY,
        altium_provider_key="digikey-ultralibrarian",
        altium_sources=_altium_pair(tmp_path),
        verifier=verifier,
        preferred_manifest_digest=current,
    )

    assert selected.resolved.descriptor.manifest_digest == current
    assert len(calls) == 1
    assert "current" in calls[0]


def test_invalid_same_family_report_falls_back_without_accepting_valid_true_only(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    ultra = _record_kicad(store, "ultralibrarian", "ultra")
    snap = _record_kicad(store, "snapmagic", "snap")
    calls: list[str] = []

    def verifier(**kwargs):
        marker = kwargs["kicad_symbol"].read_text(encoding="utf-8")
        provider = "ultralibrarian" if "ultra" in marker else "snapmagic"
        calls.append(provider)
        return {"valid": True} if provider == "ultralibrarian" else _explicit_success()

    selected = select_compatible_retained_kicad(
        store,
        identity=_IDENTITY,
        altium_provider_key="digikey-ultralibrarian",
        altium_sources=_altium_pair(tmp_path),
        verifier=verifier,
    )

    assert selected.resolved.descriptor.manifest_digest == snap
    assert selected.resolved.descriptor.manifest_digest != ultra
    assert calls == ["ultralibrarian", "snapmagic"]
    assert [attempt.accepted for attempt in selected.attempts] == [False, True]


def test_every_failure_is_reported_and_every_candidate_scratch_tree_is_cleaned(
    tmp_path: Path,
) -> None:
    store = EvidenceStore(tmp_path / "Evidence")
    _record_kicad(store, "ultralibrarian", "ultra")
    _record_kicad(store, "snapmagic", "snap")

    def verifier(**_kwargs):
        raise RuntimeError("incompatible")

    with pytest.raises(CompatibleKicadVariantNotFound) as caught:
        select_compatible_retained_kicad(
            store,
            identity=_IDENTITY,
            altium_provider_key="digikey-ultralibrarian",
            altium_sources=_altium_pair(tmp_path),
            verifier=verifier,
            temporary_parent=tmp_path,
        )

    assert [attempt.provider for attempt in caught.value.attempts] == [
        "ultralibrarian",
        "snapmagic",
    ]
    assert all(attempt.reason == "RuntimeError" for attempt in caught.value.attempts)
    assert not list(tmp_path.glob("stockroom-compatible-kicad-*"))


def test_owned_materialization_has_explicit_idempotent_cleanup(tmp_path: Path) -> None:
    owner = OwnedMaterialization.from_bytes(
        {
            "Converted.SchLib": b"symbol",
            "Converted.PcbLib": b"footprint",
        },
        prefix="stockroom-owned-altium-",
        temporary_parent=tmp_path,
    )

    assert owner.root.is_dir()
    assert all(path.is_file() for path in owner.paths)
    owner.cleanup()
    owner.cleanup()
    assert not owner.root.exists()
    with pytest.raises(RuntimeError):
        owner.__enter__()


def test_owned_materialization_adopts_only_real_files_beneath_its_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Extracted"
    root.mkdir()
    symbol = root / "Part.SchLib"
    footprint = root / "Part.PcbLib"
    symbol.write_bytes(b"symbol")
    footprint.write_bytes(b"footprint")

    owner = OwnedMaterialization.adopt(root, (symbol, footprint))

    assert owner.paths == (symbol, footprint)
    owner.cleanup()
    assert not root.exists()


@pytest.mark.parametrize(
    ("provider", "family"),
    [
        ("ultralibrarian", "ultralibrarian"),
        ("digikey-ultralibrarian", "ultralibrarian"),
        ("snapmagic", "snapmagic"),
        ("digikey-snapmagic", "snapmagic"),
        ("samacsys", "samacsys"),
        ("other-provider", "other-provider"),
    ],
)
def test_provider_family_is_affinity_only(provider: str, family: str) -> None:
    assert provider_family(provider) == family


@pytest.mark.parametrize(
    "report",
    [
        None,
        {"valid": True},
        {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": False,
        },
        {
            "valid": True,
            "terminal_equivalence": True,
            "pad_equivalence": True,
            "package_equivalence": True,
            "not_json": float("nan"),
        },
        {
            "schema": "stockroom.cross-eda-verification/1",
            "valid": True,
            "terminal_map": [{"kicad": "1", "altium": "1"}],
            "geometry": {"method": "wrong"},
            "kicad": {"pin_count": 1, "pad_count": 1},
            "altium": {"pin_count": 1, "pad_count": 1},
        },
    ],
)
def test_cross_eda_report_rejects_incomplete_or_non_json_proof(report: object) -> None:
    assert cross_eda_report_is_proved(report) is False


def test_cross_eda_report_accepts_explicit_and_omitted_no_connect_pins() -> None:
    terminal_map = [
        {"kicad": str(number), "altium": str(number)}
        for number in (5, 8, 9, 10, 11, 12, 13, 14)
    ]
    no_connect_pad_map = [
        {"kicad": str(number), "altium": str(number)}
        for number in (1, 2, 3, 4, 6, 7)
    ]
    report = {
        "schema": "stockroom.cross-eda-verification/1",
        "valid": True,
        "terminal_map": terminal_map,
        "no_connect_pad_map": no_connect_pad_map,
        "geometry": {"method": "mapped-pad-distance-and-size-signatures"},
        "kicad": {"pin_count": 14, "pad_count": 14},
        "altium": {"pin_count": 8, "pad_count": 14},
    }

    assert cross_eda_report_is_proved(report) is True


def test_cross_eda_report_accepts_format_specific_physical_pads() -> None:
    report = {
        "schema": "stockroom.cross-eda-verification/1",
        "valid": True,
        "terminal_map": [
            {"kicad": "1", "altium": "1"},
            {"kicad": "2", "altium": "2"},
        ],
        "no_connect_pad_map": [],
        "provider_specific_pad_numbers": {
            "kicad": [],
            "altium": ["18", "19", "20", "21"],
        },
        "geometry": {"method": "mapped-pad-distance-and-size-signatures"},
        "kicad": {"pin_count": 2, "pad_count": 2},
        "altium": {"pin_count": 2, "pad_count": 6},
    }

    assert cross_eda_report_is_proved(report) is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report.pop("no_connect_pad_map"),
        lambda report: report["no_connect_pad_map"].append(
            {"kicad": "1", "altium": "15"}
        ),
        lambda report: report["terminal_map"].append(
            {"kicad": "15", "altium": "15"}
        ),
    ],
)
def test_cross_eda_report_rejects_incoherent_terminal_maps(mutation) -> None:
    report = {
        "schema": "stockroom.cross-eda-verification/1",
        "valid": True,
        "terminal_map": [{"kicad": "1", "altium": "1"}],
        "no_connect_pad_map": [],
        "geometry": {"method": "mapped-pad-distance-and-size-signatures"},
        "kicad": {"pin_count": 1, "pad_count": 1},
        "altium": {"pin_count": 1, "pad_count": 1},
    }
    mutation(report)

    assert cross_eda_report_is_proved(report) is False
